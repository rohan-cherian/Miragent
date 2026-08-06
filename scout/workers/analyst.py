"""
scout/workers/analyst.py — AI Analyst powered by Claude.

This is the "brain" of the Agentic CIO. It takes structured findings
from all workers and synthesises them into an executive-quality insight
memo — the kind of document a PE operating partner would read before
a board call.

Why separate workers from the analyst?
  Workers produce FACTS (structured data, numbers, risk ratings).
  The analyst produces NARRATIVE (prose, priorities, recommendations).
  Separating them means:
    - Workers are testable without an API key (pure Python logic)
    - The AI layer can be swapped (Claude → GPT-4 → internal LLM)
    - The structured findings are also useful without AI (JSON API response)

What Claude receives:
  A rich JSON payload with all findings, severity levels, data points,
  and summary stats from every worker. Claude is instructed to act as
  a PE operating partner and produce a concise, action-oriented memo.

What Claude returns:
  A prose memo with: Executive Summary, Key Risks, Priority Actions,
  and an optional section on Rule of 40 implications.

If ANTHROPIC_API_KEY is not set:
  The analyst returns a structured fallback (no prose, but still useful)
  so the rest of the system works without an API key.
"""

import json
import logging

from scout.config import settings
from scout.workers.base import WorkerResult

logger = logging.getLogger(__name__)

# The system prompt that frames Claude's role
SYSTEM_PROMPT = """You are an experienced PE operating partner and CIO advisor.
You have just received a structured analysis of a portfolio company's digital twin —
their people data, vendor contracts, and org structure.

Your job is to write a concise, action-oriented insight memo for the deal team.
The memo should be written for a CFO or operating partner who has 5 minutes.

Style rules:
- Lead with the most urgent finding, not with context
- Use specific numbers from the data (not vague language like "many" or "some")
- Every section must have a clear recommended action
- Be direct. PE partners don't want hedging.
- Do NOT include generic filler like "it's important to note that..."
- Format: use markdown with ## headers and bullet points

Structure your memo with these exact sections:
## Executive Summary (2-3 sentences max)
## Critical & High Priority Actions (bulleted, numbered by priority)
## Workforce Findings
## Vendor & Contract Findings
## Rule of 40 Implications
## Recommended 30-Day Action Plan
"""


class AIAnalyst:
    """
    Synthesises worker findings into an executive insight memo via Claude.

    Usage:
        analyst = AIAnalyst()
        memo = analyst.generate_memo(tenant_id, [workforce_result, vendor_result])
        print(memo.narrative)
    """

    def __init__(self) -> None:
        self._client = None
        if settings.anthropic_api_key and settings.anthropic_api_key != "sk-ant-your-key-here":
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
                logger.info("AIAnalyst: Claude client initialised")
            except ImportError:
                logger.warning("AIAnalyst: anthropic package not installed. Run: poetry add anthropic")
        else:
            logger.info("AIAnalyst: No API key — will return structured fallback")

    def generate_memo(self, tenant_id: str, worker_results: list[WorkerResult]) -> "InsightMemo":
        """
        Generate an executive insight memo from worker results.

        If Claude is available: returns AI-written prose + structured findings.
        If not: returns structured findings only (still fully useful via API).
        """
        # Build the structured payload all workers produced
        structured = {
            "tenant_id": tenant_id,
            "workers": [r.to_dict() for r in worker_results],
            "total_critical": sum(r.critical_count for r in worker_results),
            "total_high": sum(r.high_count for r in worker_results),
        }

        if self._client:
            narrative = self._call_claude(structured)
        else:
            narrative = self._fallback_narrative(structured)

        return InsightMemo(
            tenant_id=tenant_id,
            narrative=narrative,
            structured=structured,
            ai_generated=self._client is not None,
        )

    def _call_claude(self, structured: dict) -> str:
        """Send findings to Claude and get back a prose memo."""
        user_message = (
            f"Here is the digital twin analysis for tenant '{structured['tenant_id']}':\n\n"
            f"```json\n{json.dumps(structured, indent=2)}\n```\n\n"
            f"Please write the executive insight memo based on these findings."
        )

        try:
            response = self._client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except Exception as exc:
            logger.error(f"Claude API call failed: {exc}", exc_info=True)
            return self._fallback_narrative(structured) + f"\n\n*AI generation failed: {exc}*"

    def _fallback_narrative(self, structured: dict) -> str:
        """
        Generate a structured text summary when Claude is not available.
        Good enough for testing and demos without an API key.
        """
        lines = [
            f"# Scout Intelligence Report — {structured['tenant_id']}",
            f"*AI narrative unavailable (no API key). Showing structured findings.*\n",
        ]

        for worker in structured["workers"]:
            if worker.get("error"):
                lines.append(f"## {worker['worker']} — ERROR\n{worker['error']}\n")
                continue

            lines.append(f"## {worker['worker']}")

            # Summary stats
            stats = worker.get("summary_stats", {})
            if stats:
                lines.append("**Key Metrics:**")
                for k, v in stats.items():
                    if isinstance(v, dict):
                        continue  # skip nested dicts
                    label = k.replace("_", " ").title()
                    if isinstance(v, float):
                        v = f"{v:,.1f}" if v < 1_000_000 else f"${v:,.0f}"
                    lines.append(f"- {label}: {v}")
                lines.append("")

            # Findings by severity
            findings = worker.get("findings", [])
            for severity in ("critical", "high", "medium", "low", "info"):
                level_findings = [f for f in findings if f["severity"] == severity]
                for f in level_findings:
                    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡",
                            "low": "🔵", "info": "ℹ️"}.get(severity, "")
                    lines.append(f"{icon} **{f['title']}**")
                    lines.append(f"  {f['detail']}")
                    if f.get("recommended_action"):
                        lines.append(f"  *Action: {f['recommended_action']}*")
                    lines.append("")

        lines.append(f"\n*Total findings: {sum(len(w.get('findings', [])) for w in structured['workers'])}*")
        lines.append(f"*Critical: {structured['total_critical']} | High: {structured['total_high']}*")
        return "\n".join(lines)


class InsightMemo:
    """The output of the AI Analyst — both the prose and the structured data."""

    def __init__(
        self,
        tenant_id: str,
        narrative: str,
        structured: dict,
        ai_generated: bool,
    ) -> None:
        self.tenant_id = tenant_id
        self.narrative = narrative
        self.structured = structured
        self.ai_generated = ai_generated

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "ai_generated": self.ai_generated,
            "narrative": self.narrative,
            "structured": self.structured,
        }
