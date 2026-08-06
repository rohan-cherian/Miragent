"""
DDQAgent — Sprint 60

Accepts a raw DDQ (text blob of questions) and drafts answers by:
  1. Parsing the text into individual questions
  2. Classifying each question into a category
  3. Searching the tenant's knowledge base for relevant context
  4. Passing question + context to Claude to draft an answer + confidence
  5. Returning a structured DDQResult

Confidence scoring:
  HIGH   (≥0.75) — KB had a direct source match; answer is specific
  REVIEW (≥0.40) — answer drafted but context was partial
  UNKNOWN(<0.40) — no relevant KB content; human must answer
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from scout.agents.knowledge_base import KnowledgeBase
from scout.config import settings

logger = logging.getLogger(__name__)

# ── Category keyword map ──────────────────────────────────────────────────────

CATEGORIES: dict[str, list[str]] = {
    "security": [
        "security", "encryption", "vulnerability", "penetration", "soc",
        "iso", "access control", "mfa", "authentication", "firewall",
        "intrusion", "patch",
    ],
    "privacy": [
        "privacy", "gdpr", "ccpa", "personal data", "pii", "data subject",
        "consent", "retention", "deletion", "dpa",
    ],
    "compliance": [
        "compliance", "audit", "certification", "regulation", "hipaa", "pci",
        "soc 2", "iso 27001", "nist", "framework",
    ],
    "business": [
        "business continuity", "disaster recovery", "bcp", "rto", "rpo",
        "uptime", "sla", "availability", "incident response",
    ],
    "technical": [
        "architecture", "infrastructure", "cloud", "aws", "azure", "gcp",
        "database", "api", "integration", "deployment", "monitoring",
    ],
    "legal": [
        "contract", "liability", "indemnification", "warranty", "termination",
        "governing law", "jurisdiction", "intellectual property",
    ],
    "financial": [
        "financial", "funding", "revenue", "insurance", "bonding",
        "bankruptcy", "audit report",
    ],
    "vendor": [
        "subprocessor", "third party", "vendor", "supplier",
        "subcontractor", "outsource",
    ],
}


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class DDQQuestion:
    index: int
    raw_text: str
    category: str


@dataclass
class DDQAnswer:
    question_index: int
    question_text: str
    category: str
    drafted_text: str
    confidence: float           # 0.0–1.0
    confidence_label: str       # "High" / "Review" / "Unknown"
    sources: list[str] = field(default_factory=list)
    needs_human: bool = False


@dataclass
class DDQResult:
    job_id: str
    tenant_id: str
    total_questions: int
    answered: int
    needs_review: int
    unanswerable: int
    answers: list[DDQAnswer]
    completed_at: datetime


# ── Agent ─────────────────────────────────────────────────────────────────────


class DDQAgent:
    """Draft answers to a DDQ by searching the tenant KB and calling Claude."""

    def __init__(self) -> None:
        self.kb = KnowledgeBase()
        self._client = None
        if settings.anthropic_api_key:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                logger.warning("anthropic SDK not installed — running in KB-only mode")

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, raw_text: str, tenant_id: str, job_id: str, db: Session) -> DDQResult:
        """Parse questions, draft answers, return DDQResult."""
        questions = self._parse_questions(raw_text)
        logger.info("DDQAgent: parsed %d questions for tenant %s", len(questions), tenant_id)

        answers: list[DDQAnswer] = []
        for q in questions:
            answer = self._draft_answer(q, tenant_id, db)
            answers.append(answer)

        answered = sum(1 for a in answers if a.confidence >= 0.40)
        needs_review = sum(1 for a in answers if 0.40 <= a.confidence < 0.75)
        unanswerable = sum(1 for a in answers if a.confidence < 0.40)

        return DDQResult(
            job_id=job_id,
            tenant_id=tenant_id,
            total_questions=len(questions),
            answered=answered,
            needs_review=needs_review,
            unanswerable=unanswerable,
            answers=answers,
            completed_at=datetime.now(timezone.utc),
        )

    # ── Question parsing ──────────────────────────────────────────────────────

    def _parse_questions(self, text: str) -> list[DDQQuestion]:
        """
        Split raw DDQ text into individual questions.

        Handles formats:
          - "1. Question text"
          - "1) Question text"
          - "Q1: Question text" / "Q1. Question text"
          - "a. Question" / "a) Question"

        Falls back to splitting on double-newlines if no numbered format found.
        Returns a list of DDQQuestion with index, raw_text, and category.
        """
        # Pattern matches: "1." / "1)" / "Q1:" / "Q1." / "a." / "a)"
        numbered_pattern = re.compile(
            r"(?:^|\n)\s*(?:Q\d+[:\.]|\d+[\.\)]|[a-zA-Z][\.\)])\s+",
            re.MULTILINE,
        )

        matches = list(numbered_pattern.finditer(text))

        raw_questions: list[str] = []
        if matches:
            for i, match in enumerate(matches):
                start = match.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                raw_text = text[start:end].strip()
                # Remove any trailing newline that bleeds into the next prefix
                raw_text = re.sub(r"\s*\n\s*$", "", raw_text)
                if raw_text:
                    raw_questions.append(raw_text)
        else:
            # No numbered format — split by double newline; each paragraph is a question
            paragraphs = re.split(r"\n{2,}", text)
            raw_questions = [p.strip() for p in paragraphs if p.strip()]

        questions: list[DDQQuestion] = []
        for idx, raw in enumerate(raw_questions):
            category = self._classify(raw)
            questions.append(DDQQuestion(index=idx, raw_text=raw, category=category))

        return questions

    # ── Classification ────────────────────────────────────────────────────────

    def _classify(self, text: str) -> str:
        """
        Match question text against CATEGORIES keyword lists.

        Multi-word keywords are matched as substrings.
        Returns the category with the most keyword hits, defaulting to 'general'.
        """
        text_lower = text.lower()
        best_category = "general"
        best_score = 0

        for category, keywords in CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    # ── Answer drafting ───────────────────────────────────────────────────────

    def _draft_answer(
        self, question: DDQQuestion, tenant_id: str, db: Session
    ) -> DDQAnswer:
        """
        Draft an answer for a single question.

        Steps:
          1. Search KB for relevant chunks
          2. If no chunks and no LLM client → Unknown answer
          3. Build Claude prompt with question + context
          4. Parse Claude response (answer + confidence)
          5. Determine confidence_label and needs_human
        """
        context_chunks = self.kb.search(question.raw_text, tenant_id, db, k=6)
        source_filenames: list[str] = []

        if context_chunks:
            # Collect unique document filenames via document_id lookups
            seen_ids: set[str] = set()
            for chunk in context_chunks:
                if chunk.document_id not in seen_ids:
                    seen_ids.add(chunk.document_id)
                    if chunk.document and chunk.document.filename:
                        source_filenames.append(chunk.document.filename)

        drafted_text, confidence = self._call_claude(
            question.raw_text, context_chunks, question.category
        )

        # Confidence label
        if confidence >= 0.75:
            confidence_label = "High"
        elif confidence >= 0.40:
            confidence_label = "Review"
        else:
            confidence_label = "Unknown"

        needs_human = confidence < 0.75

        return DDQAnswer(
            question_index=question.index,
            question_text=question.raw_text,
            category=question.category,
            drafted_text=drafted_text,
            confidence=confidence,
            confidence_label=confidence_label,
            sources=source_filenames,
            needs_human=needs_human,
        )

    # ── Claude integration ────────────────────────────────────────────────────

    def _call_claude(
        self,
        question: str,
        context_chunks: list,
        category: str,
    ) -> tuple[str, float]:
        """
        Call Claude to draft an answer given question + KB context chunks.

        Returns (answer_text, confidence) where confidence is 0.0–1.0.

        When no LLM client is available, returns an Unknown placeholder.
        When no KB chunks are found, confidence is set low (0.1).
        """
        if not self._client:
            if not context_chunks:
                return (
                    "No knowledge base content found for this question. Human review required.",
                    0.0,
                )
            # KB chunks found but no LLM — surface the most relevant chunk as a draft
            best_chunk = context_chunks[0]
            excerpt = best_chunk.content[:800].strip()
            return (
                f"[KB excerpt — no LLM configured; review and rewrite]\n\n{excerpt}",
                0.35,
            )

        # Build context block
        if context_chunks:
            context_sections = []
            for i, chunk in enumerate(context_chunks[:5], 1):
                doc_name = ""
                if chunk.document:
                    doc_name = f" (from: {chunk.document.filename})"
                context_sections.append(
                    f"[Source {i}{doc_name}]\n{chunk.content[:600]}"
                )
            context_text = "\n\n---\n\n".join(context_sections)
        else:
            context_text = "(No relevant documents found in the knowledge base for this question.)"

        system_prompt = (
            "You are a senior compliance professional helping a company respond to a "
            "Due Diligence Questionnaire (DDQ) from a prospective customer or investor. "
            "Your role is to draft a professional, accurate answer on behalf of the company. "
            "When you have specific policy or documentation context, be precise and reference it. "
            "When context is limited or absent, be honest about uncertainty and recommend "
            "that a human reviewer confirm or complete the answer. "
            "Always respond in valid JSON with this exact shape: "
            '{"answer": "<drafted answer text>", "confidence": <float 0.0-1.0>, "reasoning": "<brief explanation>"}'
            "\n\nConfidence guide: "
            "0.8+ = you have specific, directly relevant documentation; "
            "0.5-0.79 = partial information, answer is reasonable but needs verification; "
            "0.1-0.49 = minimal context, answer is speculative; "
            "0.0 = no relevant context at all."
        )

        user_prompt = (
            f"Category: {category}\n\n"
            f"Question:\n{question}\n\n"
            f"Relevant context from our policy documents:\n\n{context_text}\n\n"
            "Draft a professional answer to this DDQ question based on the context above. "
            "If the context directly addresses the question, use it to write a specific answer. "
            "If context is absent or weak, draft a reasonable placeholder and set confidence below 0.5. "
            "Respond ONLY with valid JSON."
        )

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
            )
            raw_content = response.content[0].text.strip()

            # Strip markdown code fences if present
            raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content)
            raw_content = re.sub(r"\s*```$", "", raw_content)

            parsed = json.loads(raw_content)
            answer_text = parsed.get("answer", "").strip()
            confidence = float(parsed.get("confidence", 0.3))
            confidence = max(0.0, min(1.0, confidence))

            if not answer_text:
                answer_text = "Unable to draft an answer. Human review required."
                confidence = 0.0

            return answer_text, confidence

        except json.JSONDecodeError as exc:
            logger.warning("Claude returned non-JSON response: %s", exc)
            # Try to salvage raw text
            return raw_content[:1000] if raw_content else "Parse error — human review required.", 0.3
        except Exception as exc:
            logger.error("Claude API call failed: %s", exc)
            return f"Error drafting answer: {exc}. Human review required.", 0.0
