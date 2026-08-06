"""
scout/api/routes/knowledge_base.py — Knowledge Base Manager API

Endpoints:
  GET    /knowledge-base/documents    ?tenant_id=&category=   → list[KBDocumentSummary]
  POST   /knowledge-base/upload       multipart: file + tenant_id + category + description
  DELETE /knowledge-base/documents/{doc_id}  ?tenant_id=      → {success: bool}
  GET    /knowledge-base/search       ?tenant_id=&q=&k=6      → list[KBChunkResult]
  GET    /knowledge-base/stats        ?tenant_id=              → KBStats

Sprint 75: Provides operator-facing document management UI backing.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import Depends

from scout.agents.knowledge_base import KnowledgeBase
from scout.db.database import get_db
from scout.db.models import KBChunk, KBDocument

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])

kb = KnowledgeBase()

# ── Constants ──────────────────────────────────────────────────────────────────

KB_CATEGORIES = [
    "security_policy",
    "hr_policy",
    "finance",
    "legal",
    "product",
    "company_overview",
    "customer_success",
    "compliance",
    "general",
]

AGENTS_POWERED = ["DDQAgent", "ComplianceAgent", "MeetingPrepAgent"]

SEED_DOCUMENTS = [
    {
        "filename": "SOC2_Type_II_Report_2024.pdf",
        "category": "security_policy",
        "description": "Annual SOC 2 Type II audit report covering Security, Availability, and Confidentiality trust service criteria.",
        "content_preview": "INDEPENDENT SERVICE AUDITOR'S REPORT. We have examined Miragent Inc's description of its SaaS platform system and the suitability of design and operating effectiveness of controls...",
        "chunk_count": 24,
        "file_size_bytes": 892400,
    },
    {
        "filename": "Employee_Handbook_2025.pdf",
        "category": "hr_policy",
        "description": "Company employee handbook covering PTO policy, benefits, code of conduct, and HR procedures.",
        "content_preview": "Welcome to Miragent. This handbook outlines our policies, values, and the benefits available to all full-time employees. PTO accrual begins on day one...",
        "chunk_count": 41,
        "file_size_bytes": 1240000,
    },
    {
        "filename": "Security_Policy_v3.docx",
        "category": "security_policy",
        "description": "Information security policy document covering access control, encryption, incident response, and vulnerability management.",
        "content_preview": "1. PURPOSE. This Information Security Policy establishes the framework for protecting Miragent's information assets. 2. SCOPE. This policy applies to all employees, contractors...",
        "chunk_count": 18,
        "file_size_bytes": 245000,
    },
    {
        "filename": "Data_Processing_Agreement.pdf",
        "category": "legal",
        "description": "GDPR-compliant Data Processing Agreement for enterprise customers. Covers data subject rights, subprocessors, and breach notification.",
        "content_preview": "DATA PROCESSING AGREEMENT. This Data Processing Agreement (DPA) forms part of the Master Services Agreement between Miragent Inc (Processor) and Customer (Controller)...",
        "chunk_count": 12,
        "file_size_bytes": 187000,
    },
    {
        "filename": "Company_Overview_Deck.pdf",
        "category": "company_overview",
        "description": "Investor and customer-facing company overview: product, team, traction, and market opportunity.",
        "content_preview": "Miragent: The Agentic CIO in a Box. We connect to your existing business systems, build a digital twin of your operations, and deploy AI workers that find problems and fix them automatically...",
        "chunk_count": 15,
        "file_size_bytes": 4200000,
    },
    {
        "filename": "Penetration_Test_Summary_2024.pdf",
        "category": "security_policy",
        "description": "Annual penetration test executive summary. All critical and high findings remediated. Conducted by CrowdStrike.",
        "content_preview": "EXECUTIVE SUMMARY. CrowdStrike conducted a comprehensive penetration test of Miragent's production infrastructure in October 2024. No critical vulnerabilities were identified...",
        "chunk_count": 8,
        "file_size_bytes": 342000,
    },
    {
        "filename": "Customer_Success_Playbook.pdf",
        "category": "customer_success",
        "description": "Internal CS playbook covering onboarding, QBR process, expansion triggers, and churn prevention.",
        "content_preview": "CUSTOMER SUCCESS PLAYBOOK. Onboarding (Days 1-30): Connect systems, run first scan, review findings with economic buyer. Days 31-90: Drive first action resolution...",
        "chunk_count": 22,
        "file_size_bytes": 678000,
    },
    {
        "filename": "Privacy_Policy_v4.pdf",
        "category": "legal",
        "description": "Public privacy policy covering data collection, usage, retention, and CCPA/GDPR compliance.",
        "content_preview": "PRIVACY POLICY. Last updated: January 1, 2025. Miragent Inc. ('we', 'us') is committed to protecting your privacy. This policy explains how we collect, use, and share information...",
        "chunk_count": 9,
        "file_size_bytes": 124000,
    },
]


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class KBDocumentSummary(BaseModel):
    doc_id: str
    filename: str
    category: str
    description: str
    chunk_count: int
    file_size_bytes: int
    uploaded_at: str
    content_preview: str


class KBStats(BaseModel):
    total_documents: int
    total_chunks: int
    by_category: dict
    agents_powered: list[str]
    last_ingested: Optional[str]


class KBChunkResult(BaseModel):
    doc_id: str
    filename: str
    category: str
    chunk_text: str
    score: int


# ── Internal helpers ───────────────────────────────────────────────────────────


def _doc_to_summary(doc: KBDocument) -> KBDocumentSummary:
    """Convert a KBDocument ORM row to the summary response shape."""
    # Extract metadata stored in created_by as JSON-ish pipe-separated string:
    # "description|content_preview|file_size_bytes"
    # We store extra fields encoded in created_by for the seeded mock docs.
    description = ""
    content_preview = ""
    file_size_bytes = 0

    if doc.created_by and doc.created_by.startswith("__kb_meta__:"):
        raw = doc.created_by[len("__kb_meta__:"):]
        parts = raw.split("|", 2)
        if len(parts) >= 1:
            try:
                file_size_bytes = int(parts[0])
            except ValueError:
                pass
        if len(parts) >= 2:
            description = parts[1]
        if len(parts) >= 3:
            content_preview = parts[2]

    return KBDocumentSummary(
        doc_id=doc.id,
        filename=doc.filename,
        category=doc.doc_type,
        description=description,
        chunk_count=doc.chunk_count,
        file_size_bytes=file_size_bytes,
        uploaded_at=doc.created_at.isoformat(),
        content_preview=content_preview,
    )


def _seed_documents(tenant_id: str, db: Session) -> None:
    """Seed SEED_DOCUMENTS into the DB for a fresh tenant. Called once on first GET."""
    now = datetime.utcnow()
    for i, seed in enumerate(SEED_DOCUMENTS):
        # Create a deterministic fake hash so dedup works
        fake_content = seed["content_preview"] + seed["filename"]
        content_hash = hashlib.sha256(fake_content.encode()).hexdigest()

        # Skip if already seeded (hash match)
        existing = db.execute(
            select(KBDocument).where(
                KBDocument.tenant_id == tenant_id,
                KBDocument.content_hash == content_hash,
            )
        ).scalar_one_or_none()
        if existing:
            continue

        # Encode extra metadata in created_by using a sentinel prefix
        meta = f"__kb_meta__:{seed['file_size_bytes']}|{seed['description']}|{seed['content_preview']}"

        doc = KBDocument(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            filename=seed["filename"],
            doc_type=seed["category"],
            content_hash=content_hash,
            chunk_count=seed["chunk_count"],
            created_at=datetime(2025, 1, 1 + i),
            created_by=meta,
        )
        db.add(doc)

    db.commit()


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/documents", response_model=list[KBDocumentSummary])
def list_documents(
    tenant_id: str,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[KBDocumentSummary]:
    """
    List all KB documents for a tenant.

    Seeds mock documents on first call if the KB is empty.
    Optionally filter by category.
    """
    # Check if tenant has any documents
    count_result = db.execute(
        select(KBDocument).where(KBDocument.tenant_id == tenant_id)
    ).first()

    if count_result is None:
        # First call — seed mock data
        _seed_documents(tenant_id, db)

    query = select(KBDocument).where(KBDocument.tenant_id == tenant_id)
    if category:
        query = query.where(KBDocument.doc_type == category)
    query = query.order_by(KBDocument.created_at.desc())

    docs = db.execute(query).scalars().all()
    return [_doc_to_summary(d) for d in docs]


@router.post("/upload", response_model=KBDocumentSummary)
async def upload_document(
    file: UploadFile,
    tenant_id: str = Form(...),
    category: str = Form("general"),
    description: str = Form(""),
    db: Session = Depends(get_db),
) -> KBDocumentSummary:
    """
    Upload a document to the tenant's knowledge base.

    Accepts .pdf, .docx, .txt files. Deduplicates by content hash.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided.")

    allowed_extensions = {".txt", ".pdf", ".docx", ".md"}
    fname_lower = file.filename.lower()
    if not any(fname_lower.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

    if category not in KB_CATEGORIES:
        category = "general"

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    file_size_bytes = len(raw_bytes)

    try:
        doc = kb.ingest_bytes(
            raw_bytes=raw_bytes,
            filename=file.filename,
            tenant_id=tenant_id,
            doc_type=category,
            db=db,
            created_by=f"__kb_meta__:{file_size_bytes}|{description}|",
        )
    except Exception as exc:
        logger.error("Document ingestion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        ) from exc

    # Extract a content preview from the first chunk if available
    first_chunk = db.execute(
        select(KBChunk)
        .where(KBChunk.document_id == doc.id, KBChunk.chunk_index == 0)
    ).scalar_one_or_none()
    content_preview = (first_chunk.content[:200] if first_chunk else "")[:200]

    return KBDocumentSummary(
        doc_id=doc.id,
        filename=doc.filename,
        category=doc.doc_type,
        description=description,
        chunk_count=doc.chunk_count,
        file_size_bytes=file_size_bytes,
        uploaded_at=doc.created_at.isoformat(),
        content_preview=content_preview,
    )


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a KB document and all its chunks."""
    doc = db.execute(
        select(KBDocument).where(
            KBDocument.id == doc_id,
            KBDocument.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    deleted = kb.delete_document(doc_id=doc_id, tenant_id=tenant_id, db=db)
    return {"success": deleted}


@router.get("/search", response_model=list[KBChunkResult])
def search_documents(
    tenant_id: str,
    q: str,
    k: int = 6,
    db: Session = Depends(get_db),
) -> list[KBChunkResult]:
    """Keyword search across tenant KB chunks. Returns top k results."""
    if not q.strip():
        return []

    chunks = kb.search(query=q, tenant_id=tenant_id, db=db, k=k)

    results: list[KBChunkResult] = []
    for chunk in chunks:
        doc = db.execute(
            select(KBDocument).where(KBDocument.id == chunk.document_id)
        ).scalar_one_or_none()
        if not doc:
            continue

        # Compute score for the result (re-tokenize)
        keywords = kb._tokenize(q)
        score = kb._score_chunk(chunk.content, keywords)

        results.append(KBChunkResult(
            doc_id=chunk.document_id,
            filename=doc.filename,
            category=doc.doc_type,
            chunk_text=chunk.content[:300],
            score=score,
        ))

    return results


@router.get("/stats", response_model=KBStats)
def get_stats(
    tenant_id: str,
    db: Session = Depends(get_db),
) -> KBStats:
    """Return aggregate stats for the tenant's knowledge base."""
    docs = db.execute(
        select(KBDocument).where(KBDocument.tenant_id == tenant_id)
    ).scalars().all()

    total_chunks = sum(d.chunk_count for d in docs)

    by_category: dict[str, int] = {}
    last_ingested: Optional[datetime] = None

    for doc in docs:
        cat = doc.doc_type or "general"
        by_category[cat] = by_category.get(cat, 0) + 1
        if last_ingested is None or doc.created_at > last_ingested:
            last_ingested = doc.created_at

    return KBStats(
        total_documents=len(docs),
        total_chunks=total_chunks,
        by_category=by_category,
        agents_powered=AGENTS_POWERED,
        last_ingested=last_ingested.isoformat() if last_ingested else None,
    )
