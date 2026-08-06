"""
scout/api/routes/ddq.py — DDQ Agent API

Endpoints:
  POST   /ddq/documents              — upload KB document (multipart/form-data)
  GET    /ddq/documents              — list KB documents for tenant
  DELETE /ddq/documents/{doc_id}     — delete KB document
  POST   /ddq/analyze                — run DDQ analysis
  GET    /ddq/jobs/{job_id}          — get job status + result

All routes require JWT auth (get_current_user dependency).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.agents.ddq_agent import DDQAgent, DDQResult
from scout.agents.ddq_template_agent import DDQTemplateAgent, DDQTemplateResult
from scout.agents.knowledge_base import KnowledgeBase
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import DDQJob, DDQTemplateJob, KBDocument, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ddq", tags=["ddq"])

kb = KnowledgeBase()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class KBDocumentResponse(BaseModel):
    id: str
    tenant_id: str
    filename: str
    doc_type: str
    chunk_count: int
    created_at: datetime
    created_by: Optional[str] = None


class AnalyzeRequest(BaseModel):
    tenant_id: str
    questions_text: str


class DDQAnswerResponse(BaseModel):
    question_index: int
    question_text: str
    category: str
    drafted_text: str
    confidence: float
    confidence_label: str
    sources: list[str]
    needs_human: bool


class DDQJobResponse(BaseModel):
    job_id: str
    tenant_id: str
    status: str
    total_questions: int
    answered: int
    needs_review: int
    unanswerable: int
    answers: list[DDQAnswerResponse]
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


def _doc_to_response(doc: KBDocument) -> KBDocumentResponse:
    return KBDocumentResponse(
        id=doc.id,
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        doc_type=doc.doc_type,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
        created_by=doc.created_by,
    )


def _result_to_job_response(result: DDQResult, job_id: str) -> DDQJobResponse:
    return DDQJobResponse(
        job_id=job_id,
        tenant_id=result.tenant_id,
        status="done",
        total_questions=result.total_questions,
        answered=result.answered,
        needs_review=result.needs_review,
        unanswerable=result.unanswerable,
        answers=[
            DDQAnswerResponse(
                question_index=a.question_index,
                question_text=a.question_text,
                category=a.category,
                drafted_text=a.drafted_text,
                confidence=a.confidence,
                confidence_label=a.confidence_label,
                sources=a.sources,
                needs_human=a.needs_human,
            )
            for a in result.answers
        ],
        completed_at=result.completed_at,
    )


# ── Document upload ────────────────────────────────────────────────────────────


@router.post("/documents", response_model=KBDocumentResponse)
async def upload_document(
    file: UploadFile,
    doc_type: str = Form("general"),
    tenant_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KBDocumentResponse:
    """
    Upload a document to the tenant's knowledge base.

    Accepts .txt, .pdf, .docx files. Deduplicates by content hash.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided.")

    allowed_extensions = {".txt", ".pdf", ".docx", ".md"}
    fname = file.filename.lower()
    if not any(fname.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}",
        )

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        doc = kb.ingest_bytes(
            raw_bytes=raw_bytes,
            filename=file.filename,
            tenant_id=tenant_id,
            doc_type=doc_type,
            db=db,
            created_by=current_user.email,
        )
    except Exception as exc:
        logger.error("Document ingestion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        ) from exc

    return _doc_to_response(doc)


# ── List documents ─────────────────────────────────────────────────────────────


@router.get("/documents", response_model=list[KBDocumentResponse])
def list_documents(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KBDocumentResponse]:
    """List all KB documents for a tenant."""
    docs = kb.list_documents(tenant_id=tenant_id, db=db)
    return [_doc_to_response(d) for d in docs]


# ── Delete document ────────────────────────────────────────────────────────────


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Delete a KB document and all its chunks."""
    # Fetch doc to verify tenant ownership
    doc = db.execute(
        select(KBDocument).where(KBDocument.id == doc_id)
    ).scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # Ensure the requesting user's tenant owns the document
    if doc.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    deleted = kb.delete_document(doc_id=doc_id, tenant_id=doc.tenant_id, db=db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return {"ok": True}


# ── Analyze DDQ ────────────────────────────────────────────────────────────────


@router.post("/analyze", response_model=DDQJobResponse)
def analyze_ddq(
    body: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DDQJobResponse:
    """
    Run DDQ analysis on the provided questions text.

    Creates a DDQJob record, runs DDQAgent synchronously, persists results.
    Returns full job result including drafted answers.
    """
    if not body.questions_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="questions_text must not be empty.",
        )

    # Create job record
    job = DDQJob(
        tenant_id=body.tenant_id,
        status="running",
        input_text=body.questions_text,
        created_by=current_user.email,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        agent = DDQAgent()
        result = agent.run(
            raw_text=body.questions_text,
            tenant_id=body.tenant_id,
            job_id=job.id,
            db=db,
        )

        # Serialize answers for storage
        answers_list = [
            {
                "question_index": a.question_index,
                "question_text": a.question_text,
                "category": a.category,
                "drafted_text": a.drafted_text,
                "confidence": a.confidence,
                "confidence_label": a.confidence_label,
                "sources": a.sources,
                "needs_human": a.needs_human,
            }
            for a in result.answers
        ]

        # Update job record
        job.status = "done"
        job.total_questions = result.total_questions
        job.answered = result.answered
        job.needs_review = result.needs_review
        job.unanswerable = result.unanswerable
        job.result_json = {"answers": answers_list}
        job.completed_at = result.completed_at
        db.commit()

        return _result_to_job_response(result, job.id)

    except Exception as exc:
        logger.error("DDQ analysis failed for job %s: %s", job.id, exc)
        job.status = "failed"
        job.error = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {exc}",
        ) from exc


# ── Get job ────────────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}", response_model=DDQJobResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DDQJobResponse:
    """Retrieve a DDQ job by ID, including its answers if completed."""
    job = db.execute(
        select(DDQJob).where(DDQJob.id == job_id)
    ).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    answers: list[DDQAnswerResponse] = []
    if job.result_json and "answers" in job.result_json:
        for a in job.result_json["answers"]:
            answers.append(DDQAnswerResponse(**a))

    return DDQJobResponse(
        job_id=job.id,
        tenant_id=job.tenant_id,
        status=job.status,
        total_questions=job.total_questions,
        answered=job.answered,
        needs_review=job.needs_review,
        unanswerable=job.unanswerable,
        answers=answers,
        completed_at=job.completed_at,
        error=job.error,
    )


# ── Sprint 71: Template Fill ────────────────────────────────────────────────────


class DDQTemplateQuestionResponse(BaseModel):
    number: int
    question_text: str
    answer: str
    confidence: float
    confidence_label: str


class DDQTemplateResultResponse(BaseModel):
    job_id: str
    tenant_id: str
    source_filename: str
    total_questions: int
    filled_questions: int
    questions: list[DDQTemplateQuestionResponse]
    filled_docx_b64: str
    can_download: bool
    submitted_at: str
    summary: str


def _template_result_to_response(result: DDQTemplateResult) -> DDQTemplateResultResponse:
    return DDQTemplateResultResponse(
        job_id=result.job_id,
        tenant_id=result.tenant_id,
        source_filename=result.source_filename,
        total_questions=result.total_questions,
        filled_questions=result.filled_questions,
        questions=[
            DDQTemplateQuestionResponse(
                number=q.number,
                question_text=q.question_text,
                answer=q.answer,
                confidence=q.confidence,
                confidence_label=q.confidence_label,
            )
            for q in result.questions
        ],
        filled_docx_b64=result.filled_docx_b64,
        can_download=result.can_download,
        submitted_at=result.submitted_at,
        summary=result.summary,
    )


@router.post("/fill-template", response_model=DDQTemplateResultResponse)
async def fill_template(
    tenant_id: str = Form(...),
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DDQTemplateResultResponse:
    """
    Parse a DDQ template and fill it with AI-drafted answers.

    Accepts:
      - file: optional DOCX/TXT upload — text is extracted from the file
      - text: optional raw question text passed directly
      - If neither is provided, the built-in sample template is used.

    Returns a DDQTemplateResult including a base64-encoded filled DOCX.
    """
    agent = DDQTemplateAgent()

    # Determine source
    if file and file.filename:
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )
        result = agent.process_template(
            filename=file.filename,
            file_content=raw_bytes,
            tenant_id=tenant_id,
            db=db,
        )
    elif text and text.strip():
        result = agent.process_text_template(text=text, tenant_id=tenant_id, db=db)
    else:
        sample_text = agent.get_sample_template_text()
        result = agent.process_text_template(text=sample_text, tenant_id=tenant_id, db=db)
        result.source_filename = "sample_ddq_template.txt"

    # Persist job record
    try:
        job = DDQTemplateJob(
            id=result.job_id,
            tenant_id=tenant_id,
            source_filename=result.source_filename,
            total_questions=result.total_questions,
            result={
                "filled_questions": result.filled_questions,
                "summary": result.summary,
                "questions": [
                    {
                        "number": q.number,
                        "question_text": q.question_text,
                        "answer": q.answer,
                        "confidence": q.confidence,
                        "confidence_label": q.confidence_label,
                    }
                    for q in result.questions
                ],
            },
        )
        db.add(job)
        db.commit()
    except Exception as exc:
        logger.warning("Could not persist DDQTemplateJob: %s", exc)
        # Non-fatal — return result anyway

    return _template_result_to_response(result)


@router.get("/sample-template")
def get_sample_template(
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """
    Return the built-in sample DDQ template text.

    Useful for the frontend "Use Sample Template" button.
    """
    agent = DDQTemplateAgent()
    return {
        "filename": "sample_ddq_template.txt",
        "text": agent.get_sample_template_text(),
    }
