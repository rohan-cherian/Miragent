"""
scout/analysis/llm_analyst.py — LLM-powered narrative analyst.

Provider-agnostic: works with Claude, OpenAI, Gemini, Ollama, or any
future backend — all determined by config, no code changes required.

Design:
  - LLMAnalyst accepts an optional LLMProvider at construction time.
    When called without arguments it builds one from settings via
    build_provider() — so existing call sites need no changes.
  - If the provider is unavailable (missing SDK / missing key) →
    falls back to the template narrative from AIAnalyst, so the
    insights endpoint always returns a usable string.

Prompt engineering:
  - System prompt: CIO / PE operating partner persona
  - User message: structured summary of worker results, capped at ~8000
    tokens (top-3 findings per worker, detail strings truncated)
  - Cross-worker correlation section prepended so the LLM weights
    multi-worker entity flags as the highest-priority items
  - Output: plain text memo, 400-600 words, CAPS section labels

Error handling:
  - Any provider error → log + return fallback template narrative
  - Never raises; the insights endpoint always gets a string back
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scout.analysis.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Maximum characters for any single finding detail before truncation
_MAX_DETAIL_CHARS = 200

# Maximum findings per worker included in the LLM prompt
_MAX_FINDINGS_PER_WORKER = 3

# Severities that count as signal for cross-worker correlation
_HIGH_SELS = {"critical", "high"}

SYSTEM_PROMPT = """\
You are a world-class Chief Information Officer and operating partner at a PE firm.
You analyze business data extracted from enterprise systems and produce crisp,
actionable executive memos. Your memos are structured, data-driven, and focus on
the highest-impact findings. You write for sophisticated PE investors and operators
who value directness and specificity.

Rules:
- Lead with the single most urgent finding — no throat-clearing
- Cite specific numbers from the data (percentages, dollar amounts, headcounts)
- Every recommended action must be concrete and time-bound
- Use plain prose; do NOT use markdown, bullet symbols, or hash headers
- Structure with plain CAPS section labels followed by a colon
- Target length: 400-600 words total
- Sections required: EXECUTIVE SUMMARY, TOP 3 PRIORITIES, RISK FLAGS, QUICK WINS
- CROSS-WORKER SIGNALS (entities flagged by multiple workers) are the highest-priority
  findings — an account that appears in both ChurnPrediction and RenewalWorkflow is
  more urgent than either finding alone. Always surface these in TOP 3 PRIORITIES.
- When a CROSS-WORKER SIGNAL is present, name the specific entity and describe why
  multiple workers flagged it — do not just summarize each worker's finding separately.
"""


def _truncate(text: str, max_chars: int = _MAX_DETAIL_CHARS) -> str:
    """Truncate a string and append '...' if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _extract_entity_names(entities: list[Any]) -> list[str]:
    """
    Normalize specific_entities to a flat list of string names.

    Workers may emit specific_entities as:
      - list of str: ["Acme Corp", "Sarah Chen"]
      - list of dict: [{"type": "account", "name": "Acme Corp", ...}]
      - mixed (uncommon, tolerated)
    """
    names: list[str] = []
    for e in entities:
        if isinstance(e, str) and e.strip():
            names.append(e.strip())
        elif isinstance(e, dict):
            # Accept any of these keys in order of specificity
            for key in ("name", "account", "vendor", "person", "deal", "title"):
                val = e.get(key)
                if val and isinstance(val, str):
                    names.append(val.strip())
                    break
    return names


def _build_cross_worker_correlations(worker_results: list[dict]) -> list[str]:
    """
    Pre-compute cross-worker entity correlations.

    Scans all HIGH and CRITICAL findings for specific_entities, then
    identifies entities that appear in findings from 2+ distinct workers.
    These multi-worker flags are the highest-signal items in the memo
    — they represent compounding risk that no single worker can surface
    on its own.

    Examples of what this catches:
      - An account in ChurnPrediction (HIGH) + RenewalWorkflow (CRITICAL)
        + CrossSellIntelligence (no pipeline) → triple-flagged account.
      - A person in KeyPersonRisk (CRITICAL) + SentimentWorker (HIGH
        manager team) → individual-level compound risk.
      - A vendor in VendorBenchmark (CRITICAL) + VendorNegotiation (CRITICAL,
        30 days to renewal) → urgent negotiation with an overpriced contract.

    Returns a list of human-readable correlation strings for the prompt.
    """
    # entity_key -> list of (worker_name, severity, finding_title)
    entity_mentions: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for wr in worker_results:
        worker_name = wr.get("worker", "Unknown")
        if wr.get("error"):
            continue
        for f in wr.get("findings", []):
            severity = (f.get("severity") or "info").lower()
            if severity not in _HIGH_SELS:
                continue
            names = _extract_entity_names(f.get("specific_entities", []))
            title = f.get("title", "")
            for name in names:
                # Normalise key: lowercase + strip extra whitespace
                key = " ".join(name.lower().split())
                entity_mentions[key].append((worker_name, severity, title))

    correlations: list[str] = []
    for entity_key, mentions in entity_mentions.items():
        workers_involved = list(dict.fromkeys(m[0] for m in mentions))  # ordered dedup
        if len(workers_involved) < 2:
            continue

        crit_count = sum(1 for _, sev, _ in mentions if sev == "critical")
        high_count  = sum(1 for _, sev, _ in mentions if sev == "high")

        sev_parts: list[str] = []
        if crit_count:
            sev_parts.append(f"{crit_count} CRITICAL")
        if high_count:
            sev_parts.append(f"{high_count} HIGH")
        sev_desc = " + ".join(sev_parts)

        # Use the original (non-normalised) name from the first mention
        original_name = _extract_entity_names([].__class__([mentions[0][2]]))[0] if False else entity_key.title()

        worker_list = ", ".join(workers_involved[:5])
        correlations.append(
            f'  MULTI-WORKER FLAG: "{original_name}" appears in {len(workers_involved)} workers '
            f"({worker_list}) with {sev_desc} findings. Coordinated action required."
        )

    # Sort: more workers involved = higher priority
    correlations.sort(
        key=lambda s: -int(s.split("appears in ")[1].split(" workers")[0])
        if "appears in " in s else 0
    )
    return correlations[:8]  # cap at 8 cross-worker signals to avoid prompt bloat


def build_prompt(worker_results: list[dict], tenant_id: str) -> str:
    """
    Build the user-message prompt from worker result dicts.

    Keeps the prompt under ~8000 tokens by:
      - Including at most _MAX_FINDINGS_PER_WORKER findings per worker
      - Truncating finding detail strings to _MAX_DETAIL_CHARS characters
      - Omitting raw 'data' sub-dicts (too verbose)

    Args:
        worker_results: list of dicts as produced by WorkerResult.to_dict()
        tenant_id: the tenant being analysed

    Returns:
        A plain-text prompt string for the LLM user message.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Pre-compute cross-worker correlations before building the per-worker section.
    # These appear first in the prompt so Claude weights them highest.
    correlations = _build_cross_worker_correlations(worker_results)

    total_critical = sum(
        sum(1 for f in wr.get("findings", []) if f.get("severity") == "critical")
        for wr in worker_results
        if not wr.get("error")
    )
    total_high = sum(
        sum(1 for f in wr.get("findings", []) if f.get("severity") == "high")
        for wr in worker_results
        if not wr.get("error")
    )

    lines: list[str] = [
        "ANALYSIS REQUEST",
        f"Tenant: {tenant_id}",
        f"Timestamp: {timestamp}",
        f"Workers run: {len(worker_results)}",
        f"Total CRITICAL findings: {total_critical}",
        f"Total HIGH findings: {total_high}",
        "",
    ]

    # ── Cross-worker correlation summary ────────────────────────────────────
    # Entities that appear in 2+ workers' HIGH/CRITICAL findings represent
    # compounding risk that is more important than any single-worker finding.
    if correlations:
        lines.append("CROSS-WORKER SIGNALS (entities flagged by multiple workers — highest priority):")
        lines.extend(correlations)
        lines.append("")

    for wr in worker_results:
        worker_name = wr.get("worker", "Unknown")
        error = wr.get("error")
        if error:
            lines.append(f"[{worker_name}] ERROR: {error}")
            lines.append("")
            continue

        lines.append(f"[{worker_name}]")

        # Summary stats (key metrics)
        stats = wr.get("summary_stats", {})
        if stats:
            stat_parts = []
            for k, v in stats.items():
                if isinstance(v, dict):
                    continue
                label = k.replace("_", " ")
                if isinstance(v, float):
                    formatted = f"{v:,.1f}" if v < 1_000_000 else f"${v:,.0f}"
                else:
                    formatted = str(v)
                stat_parts.append(f"{label}={formatted}")
            if stat_parts:
                lines.append("  Metrics: " + ", ".join(stat_parts))

        # Top N findings (by order — workers already sort by severity)
        findings = wr.get("findings", [])
        top_findings = findings[:_MAX_FINDINGS_PER_WORKER]
        for i, f in enumerate(top_findings, 1):
            severity = f.get("severity", "info").upper()
            title = f.get("title", "")
            detail = _truncate(f.get("detail", ""), _MAX_DETAIL_CHARS)
            action = f.get("recommended_action", "")
            lines.append(f"  Finding {i} [{severity}]: {title}")
            if detail:
                lines.append(f"    Detail: {detail}")
            if action:
                lines.append(f"    Action: {action}")

        lines.append("")

    lines.append(
        "Please write an executive memo based on the above findings. "
        "Follow the structure and style rules in your system prompt exactly."
    )

    return "\n".join(lines)


class LLMAnalyst:
    """
    Generates an executive narrative memo from worker results.

    Provider-agnostic: accepts any LLMProvider at construction time, or
    builds one from settings automatically. Swap the backend by changing
    LLM_PROVIDER in your environment — no code changes required.

    Falls back to the template-based AIAnalyst narrative when the
    provider is unavailable, so the insights endpoint always returns
    a usable string regardless of API key or SDK status.

    Usage:
        # Default — provider from settings (LLM_PROVIDER env var)
        analyst = LLMAnalyst()

        # Explicit provider (e.g. in tests or custom deployments)
        from scout.analysis.providers.openai_provider import OpenAIProvider
        analyst = LLMAnalyst(provider=OpenAIProvider(api_key="...", model="gpt-4o"))

        narrative = analyst.generate_memo(worker_results_dicts, tenant_id)
    """

    def __init__(self, provider: "LLMProvider | None" = None) -> None:
        if provider is not None:
            self._provider = provider
        else:
            from scout.analysis.providers.factory import build_provider
            self._provider = build_provider()

        if self._provider.is_available:
            logger.info(
                "LLMAnalyst: provider=%s model=%s",
                self._provider.name,
                self._provider.model,
            )
        else:
            logger.info(
                "LLMAnalyst: provider=%s unavailable — using template fallback",
                self._provider.name,
            )

        # Kept for backwards-compatibility: code that inspects `_client` to
        # determine availability (e.g. insights.py) should now check
        # `_provider.is_available`, but we expose a shim so nothing breaks.
        self._client = self._provider if self._provider.is_available else None

    def generate_memo(self, worker_results: list[dict], tenant_id: str) -> str:
        """
        Generate an executive narrative from a list of worker result dicts.

        Args:
            worker_results: list of dicts as produced by WorkerResult.to_dict()
            tenant_id: identifier for the tenant being analysed

        Returns:
            Plain-text executive memo (400-600 words when a live provider is
            available) or a structured template narrative when falling back.
        """
        if self._provider.is_available:
            return self._call_provider(worker_results, tenant_id)
        return self._fallback_narrative(worker_results, tenant_id)

    def _call_provider(self, worker_results: list[dict], tenant_id: str) -> str:
        """Delegate to the active LLMProvider and return the narrative text."""
        prompt = build_prompt(worker_results, tenant_id)
        result = self._provider.complete(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        # If the provider returned an error sentinel, fall back gracefully
        if result.startswith("[") and "error" in result.lower():
            logger.warning(
                "LLMAnalyst: provider returned error sentinel — falling back. %s",
                result[:120],
            )
            return self._fallback_narrative(worker_results, tenant_id)
        return result

    def _fallback_narrative(self, worker_results: list[dict], tenant_id: str) -> str:
        """
        Template-based narrative for when the LLM provider is unavailable.

        Delegates to the existing AIAnalyst fallback so behaviour
        remains consistent with the rest of the system.
        """
        try:
            from scout.workers.analyst import AIAnalyst
            from scout.workers.base import Finding, Severity, WorkerResult

            results: list[WorkerResult] = []
            for wr in worker_results:
                r = WorkerResult(
                    worker_name=wr.get("worker", "Unknown"),
                    tenant_id=tenant_id,
                    error=wr.get("error"),
                    summary_stats=wr.get("summary_stats", {}),
                )
                for fd in wr.get("findings", []):
                    try:
                        sev = Severity(fd.get("severity", "info"))
                    except ValueError:
                        sev = Severity.INFO
                    r.findings.append(
                        Finding(
                            title=fd.get("title", ""),
                            detail=fd.get("detail", ""),
                            severity=sev,
                            data=fd.get("data", {}),
                            recommended_action=fd.get("recommended_action", ""),
                        )
                    )
                results.append(r)

            fallback_analyst = AIAnalyst.__new__(AIAnalyst)
            fallback_analyst._client = None  # force template path in AIAnalyst
            structured = {
                "tenant_id": tenant_id,
                "workers": [r.to_dict() for r in results],
                "total_critical": sum(r.critical_count for r in results),
                "total_high": sum(r.high_count for r in results),
            }
            return fallback_analyst._fallback_narrative(structured)

        except Exception as exc:
            logger.error(
                "LLMAnalyst: fallback narrative generation failed: %s",
                exc,
                exc_info=True,
            )
            return (
                f"Scout Intelligence Report — {tenant_id}\n"
                f"Analysis complete. {len(worker_results)} workers ran. "
                f"Narrative generation unavailable."
            )
