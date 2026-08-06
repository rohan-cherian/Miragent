"""
ComplianceResponseAgent — Sprint 69

Answers customer-sent security questionnaires (CAIQ, SIG Lite, vendor assessment
forms) using a hardcoded compliance knowledge base. Unlike DDQAgent (investor
DDQs), this handles outbound responses to customers asking about YOUR security
controls, certifications, and data handling practices.

Business scenario:
  A potential or existing customer uploads / pastes their vendor security
  questionnaire. The agent classifies each question against the KB, drafts an
  answer with a confidence score, flags items that need manual review, and
  returns a structured ComplianceResult ready for human review and export.

Confidence thresholds:
  High    (≥ 0.85) — KB has a direct, specific answer
  Review  (≥ 0.60) — answer exists but may need verification
  Unknown (< 0.60) — no KB match; human must answer
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── Compliance Knowledge Base ──────────────────────────────────────────────────

COMPLIANCE_KB: dict[str, dict] = {
    "soc2": {
        "keywords": ["soc 2", "soc2", "aicpa", "trust service criteria", "type ii", "type 2"],
        "answer": (
            "We maintain SOC 2 Type II certification, audited annually by an independent "
            "third-party auditor. Our most recent report covers the period January 1 – "
            "December 31, 2024. The report is available under NDA upon request. We are "
            "certified across Security, Availability, and Confidentiality trust service criteria."
        ),
        "confidence": 0.95,
        "evidence": "SOC 2 Type II Report (available under NDA)",
    },
    "iso27001": {
        "keywords": ["iso 27001", "iso27001", "information security management", "isms"],
        "answer": (
            "We are working toward ISO 27001 certification. Our information security "
            "management system is aligned with ISO 27001 controls. We expect to achieve "
            "certification by Q4 2025. Our SOC 2 Type II certification serves as the "
            "primary evidence of our security posture in the interim."
        ),
        "confidence": 0.70,
        "evidence": "Internal ISMS documentation; SOC 2 Type II Report",
    },
    "encryption": {
        "keywords": ["encrypt", "encryption", "aes", "tls", "at rest", "in transit", "in-transit"],
        "answer": (
            "All data is encrypted at rest using AES-256 and in transit using TLS 1.2 or "
            "higher. Database encryption is enforced at the storage layer. Encryption keys "
            "are managed via AWS KMS with automatic rotation enabled."
        ),
        "confidence": 0.95,
        "evidence": "Technical architecture documentation; AWS KMS configuration",
    },
    "data_residency": {
        "keywords": [
            "data residency", "data location", "where is data stored",
            "geographic", "region", "country",
        ],
        "answer": (
            "All customer data is stored in the United States (AWS us-east-1 and us-west-2 "
            "regions). We do not transfer or process customer data outside the United States "
            "unless explicitly requested by the customer. European customers may request "
            "EU-based data residency (EU-West-1)."
        ),
        "confidence": 0.90,
        "evidence": "AWS infrastructure configuration; Data processing agreements",
    },
    "access_control": {
        "keywords": [
            "access control", "rbac", "role-based", "least privilege", "user access",
            "permissions", "mfa", "multi-factor",
        ],
        "answer": (
            "We enforce role-based access control (RBAC) with the principle of least "
            "privilege. All production system access requires multi-factor authentication "
            "(MFA). Access reviews are conducted quarterly. Privileged access is managed "
            "through Okta with just-in-time provisioning."
        ),
        "confidence": 0.95,
        "evidence": "Okta access management configuration; Quarterly access review records",
    },
    "penetration_testing": {
        "keywords": [
            "penetration test", "pentest", "pen test",
            "vulnerability assessment", "security testing",
        ],
        "answer": (
            "We conduct annual penetration testing performed by an independent third-party "
            "security firm. Our most recent penetration test was completed in October 2024. "
            "Critical and high findings are remediated within 30 and 60 days respectively. "
            "A summary report is available under NDA."
        ),
        "confidence": 0.90,
        "evidence": "Annual pentest report (available under NDA); Remediation tracking records",
    },
    "incident_response": {
        "keywords": [
            "incident response", "breach notification", "security incident",
            "data breach", "notification",
        ],
        "answer": (
            "We maintain a documented incident response plan (IRP) reviewed annually. "
            "In the event of a security incident affecting customer data, we will notify "
            "affected customers within 72 hours of discovery, consistent with GDPR Article "
            "33 requirements. Our CISO leads incident response exercises twice per year."
        ),
        "confidence": 0.90,
        "evidence": "Incident Response Plan (IRP); CISO incident response exercise records",
    },
    "gdpr": {
        "keywords": [
            "gdpr", "general data protection", "data subject rights",
            "right to erasure", "dpa", "data processing agreement",
        ],
        "answer": (
            "We are GDPR-compliant. We serve as a Data Processor for customer data. A Data "
            "Processing Agreement (DPA) is available and included in our enterprise contracts. "
            "We support data subject rights including right of access, erasure, portability, "
            "and rectification. Our DPA is available upon request."
        ),
        "confidence": 0.90,
        "evidence": "Data Processing Agreement (DPA); GDPR compliance documentation",
    },
    "ccpa": {
        "keywords": ["ccpa", "california consumer privacy", "california privacy", "cpra"],
        "answer": (
            "We comply with the California Consumer Privacy Act (CCPA) and its amendment "
            "(CPRA). We do not sell personal information. We support consumer rights requests "
            "(access, deletion, opt-out of sale) within the required 45-day response window. "
            "Our privacy policy is publicly available at [company-url]/privacy."
        ),
        "confidence": 0.85,
        "evidence": "Privacy policy; CCPA compliance documentation",
    },
    "subprocessors": {
        "keywords": [
            "subprocessor", "third party", "vendors", "sub-processor", "fourth party",
        ],
        "answer": (
            "We maintain a current list of subprocessors. Key subprocessors include: AWS "
            "(hosting/infrastructure), Anthropic (AI processing), Neo4j (graph database), "
            "Vercel (frontend hosting). Our subprocessor list is publicly available and "
            "customers are notified of changes 30 days in advance."
        ),
        "confidence": 0.85,
        "evidence": "Subprocessor list (publicly available); Vendor agreements",
    },
    "business_continuity": {
        "keywords": [
            "business continuity", "disaster recovery", "bcp", "rto", "rpo",
            "uptime", "availability", "sla",
        ],
        "answer": (
            "We target 99.9% uptime for production systems (excluding scheduled maintenance). "
            "Our Recovery Time Objective (RTO) is 4 hours and Recovery Point Objective (RPO) "
            "is 1 hour. We conduct disaster recovery tests semi-annually. Our status page is "
            "publicly available at status.[company-url]."
        ),
        "confidence": 0.85,
        "evidence": "Business Continuity Plan; Disaster recovery test records; Infrastructure monitoring",
    },
    "background_checks": {
        "keywords": [
            "background check", "employee screening", "personnel security", "pre-employment",
        ],
        "answer": (
            "All employees and contractors with access to customer data undergo background "
            "checks prior to employment, including criminal history and identity verification. "
            "Background checks are conducted by a third-party screening provider consistent "
            "with applicable employment laws."
        ),
        "confidence": 0.80,
        "evidence": "HR background check policy; Screening provider agreements",
    },
    "vulnerability_management": {
        "keywords": [
            "vulnerability management", "patch management", "cve",
            "security patches", "patching",
        ],
        "answer": (
            "We run automated vulnerability scanning on production systems weekly using "
            "industry-standard tools. Critical vulnerabilities (CVSS 9.0+) are patched within "
            "24 hours. High vulnerabilities (CVSS 7.0-8.9) are patched within 7 days. We "
            "subscribe to relevant CVE feeds and vendor security advisories."
        ),
        "confidence": 0.90,
        "evidence": "Vulnerability management policy; Scanning tool reports",
    },
    "network_security": {
        "keywords": [
            "firewall", "network security", "vpc", "network segmentation",
            "waf", "ddos",
        ],
        "answer": (
            "Our infrastructure is hosted in isolated AWS VPCs with network segmentation "
            "between production, staging, and development environments. We employ AWS WAF "
            "and Shield for DDoS protection. All inbound traffic is filtered through security "
            "groups with least-privilege rules. We use AWS GuardDuty for network threat detection."
        ),
        "confidence": 0.90,
        "evidence": "AWS infrastructure configuration; Network security documentation",
    },
    "logging_monitoring": {
        "keywords": [
            "logging", "monitoring", "audit log", "siem",
            "security monitoring", "audit trail",
        ],
        "answer": (
            "We maintain comprehensive audit logs for all system access and administrative "
            "actions. Logs are retained for 12 months and are immutable. We use CloudWatch "
            "and a SIEM tool for real-time security monitoring and alerting. Security events "
            "trigger automated alerts to our on-call security team."
        ),
        "confidence": 0.90,
        "evidence": "Logging and monitoring policy; CloudWatch configuration",
    },
}

# ── Sample questionnaire (for UI pre-fill and testing) ────────────────────────

SAMPLE_QUESTIONNAIRE = """\
1. Do you hold SOC 2 Type II certification?
2. Is customer data encrypted at rest and in transit?
3. Where is customer data physically stored?
4. Do you perform annual penetration testing?
5. Do you have an incident response plan? What is your breach notification timeline?
6. Are you GDPR compliant? Do you offer a Data Processing Agreement?
7. Do you conduct background checks on employees with access to customer data?
8. What is your uptime SLA and what are your RTO/RPO targets?
9. Do you maintain a subprocessor list?
10. How do you handle vulnerability management and patch deployment?"""


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class ComplianceAnswer:
    question_number: int
    question_text: str
    topic: str | None          # matched KB topic key
    answer: str
    confidence: float
    confidence_label: str      # "High" / "Review" / "Unknown"
    evidence: str | None       # what to attach/reference
    needs_review: bool         # True if confidence < 0.85


@dataclass
class ComplianceResult:
    job_id: str
    tenant_id: str
    customer_name: str
    questionnaire_type: str    # "CAIQ" / "SIG Lite" / "Custom (Enterprise)" / "Custom"
    total_questions: int
    high_confidence: int
    needs_review: int
    unknown_count: int
    answers: list[ComplianceAnswer]
    summary: str
    submitted_at: str


# ── Agent ──────────────────────────────────────────────────────────────────────


class ComplianceAgent:
    """
    Answers customer security questionnaires using the built-in compliance KB.

    No LLM required — KB keyword matching produces deterministic, auditable
    answers with confidence scores. Items with low confidence are flagged for
    human review.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def process_questionnaire(
        self,
        customer_name: str,
        questionnaire_text: str,
        tenant_id: str,
        db,  # noqa: ANN001 — passed through from route, ignored in KB-only mode
    ) -> ComplianceResult:
        """
        Parse and answer a security questionnaire.

        Steps:
          1. Parse text into numbered questions
          2. Match each question to a KB topic
          3. Build a ComplianceAnswer for each question
          4. Compute stats and a human-readable summary
        """
        logger.info(
            "ComplianceAgent.process_questionnaire customer=%s tenant=%s",
            customer_name,
            tenant_id,
        )

        raw_questions = self._parse_questions(questionnaire_text)
        questionnaire_type = self._detect_questionnaire_type(
            questionnaire_text, len(raw_questions)
        )

        answers: list[ComplianceAnswer] = []
        for num, text in raw_questions:
            topic = self._match_topic(text)
            answer = self._answer_question(text, topic, num)
            answers.append(answer)

        high = sum(1 for a in answers if a.confidence_label == "High")
        review = sum(1 for a in answers if a.confidence_label == "Review")
        unknown = sum(1 for a in answers if a.confidence_label == "Unknown")
        total = len(answers)

        parts = []
        if high:
            parts.append(f"{high} of {total} questions answered with high confidence")
        if review:
            parts.append(f"{review} require{'s' if review == 1 else ''} review")
        if unknown:
            parts.append(f"{unknown} {'is' if unknown == 1 else 'are'} unknown")
        summary = ". ".join(parts) + "." if parts else "No questions found."

        return ComplianceResult(
            job_id=str(uuid4()),
            tenant_id=tenant_id,
            customer_name=customer_name,
            questionnaire_type=questionnaire_type,
            total_questions=total,
            high_confidence=high,
            needs_review=review,
            unknown_count=unknown,
            answers=answers,
            summary=summary,
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Question parsing ───────────────────────────────────────────────────────

    def _parse_questions(self, text: str) -> list[tuple[int, str]]:
        """
        Split questionnaire text into (number, question_text) pairs.

        Handles formats: "1. Q", "1) Q", "Q1: Q", "Q1. Q"
        Falls back to double-newline paragraphs if no numbered format found.
        """
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
                raw_text = re.sub(r"\s*\n\s*$", "", raw_text)
                if raw_text:
                    raw_questions.append(raw_text)
        else:
            paragraphs = re.split(r"\n{2,}", text)
            raw_questions = [p.strip() for p in paragraphs if p.strip()]

        return [(i + 1, q) for i, q in enumerate(raw_questions)]

    # ── Topic matching ─────────────────────────────────────────────────────────

    def _match_topic(self, question: str) -> str | None:
        """
        Match a question to a KB topic using keyword scoring.

        Returns the topic key with the most keyword hits, or None if no match.
        """
        question_lower = question.lower()
        best_topic: str | None = None
        best_score = 0

        for topic, entry in COMPLIANCE_KB.items():
            score = sum(1 for kw in entry["keywords"] if kw in question_lower)
            if score > best_score:
                best_score = score
                best_topic = topic

        return best_topic if best_score > 0 else None

    # ── Answer building ────────────────────────────────────────────────────────

    def _answer_question(
        self,
        question: str,
        topic: str | None,
        question_number: int,
    ) -> ComplianceAnswer:
        """Build a ComplianceAnswer from a KB match (or unknown fallback)."""
        if topic is None or topic not in COMPLIANCE_KB:
            return ComplianceAnswer(
                question_number=question_number,
                question_text=question,
                topic=None,
                answer=(
                    "This question does not match our current compliance knowledge base. "
                    "Manual review and a custom response are required."
                ),
                confidence=0.0,
                confidence_label="Unknown",
                evidence=None,
                needs_review=True,
            )

        entry = COMPLIANCE_KB[topic]
        confidence: float = entry["confidence"]

        if confidence >= 0.85:
            confidence_label = "High"
        elif confidence >= 0.60:
            confidence_label = "Review"
        else:
            confidence_label = "Unknown"

        needs_review = confidence < 0.85

        return ComplianceAnswer(
            question_number=question_number,
            question_text=question,
            topic=topic,
            answer=entry["answer"],
            confidence=confidence,
            confidence_label=confidence_label,
            evidence=entry["evidence"],
            needs_review=needs_review,
        )

    # ── Questionnaire type detection ───────────────────────────────────────────

    def _detect_questionnaire_type(self, text: str, question_count: int) -> str:
        """Detect the questionnaire type from text content and question count."""
        text_lower = text.lower()
        if "caiq" in text_lower or "cloud security alliance" in text_lower:
            return "CAIQ"
        if "sig lite" in text_lower or "shared assessments" in text_lower:
            return "SIG Lite"
        if question_count > 20:
            return "Custom (Enterprise)"
        return "Custom"
