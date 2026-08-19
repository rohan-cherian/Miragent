"""
Task 19a (part 1) — the reasoning abstraction.

One async entry point, :func:`complete`, that every agent in the system
calls instead of talking to a model itself. It owns four things no agent
is allowed to own:

* **Model choice.** The tier comes from ``settings.agent_tier[agent]`` and
  the model from ``settings.llm_tiers[tier]``. An agent may pass an explicit
  ``tier`` (that is how triage escalates), but no agent ever names a model.
  That is what lets a model swap be a config change rather than a code change.
* **Redaction.** Every message's content goes through ``pii.redact()`` before
  dispatch. A :class:`~scout.governance.pii.RedactionError` propagates and
  aborts the call — it is never caught and continued past. Governance fails
  closed; this is the same rule as Task 12 and Task 17's index path.
* **Structured output.** The caller passes a pydantic model; this module
  requests ``response_format`` with a JSON schema derived from it and returns
  a parsed, validated instance. Because structured-output support varies by
  routed model, a failure falls back **once** to pasting the schema into the
  system prompt with ``response_format={"type": "json_object"}``.
* **Cost.** Every call is metered per agent and per tenant against
  ``settings.llm_cost_ceiling_usd_per_run``. When the ceiling is reached the
  next call raises :class:`CostCeilingExceededError` *before dispatching* —
  a hard stop, not a warning.

Reasoning goes through **OpenRouter** (``settings.llm_base_url``). OpenAI-direct
is embeddings only (Task 17) — OpenRouter has no ``/embeddings`` endpoint, and
correspondingly this module never touches ``settings.openai_api_key``.

Transport is ``httpx`` (already a project dependency, and what ``embed.py``
uses). The spec says "OpenAI SDK pointed at OpenRouter"; ``openai`` is not in
``pyproject.toml`` and pyproject is out of scope for this task, so the request
body is kept in the SDK's ``chat.completions.create`` shape and swapping later
is a change to :func:`_post_chat` alone.

Layering (Task 4): imports nothing from ``scout.gmail``, ``scout.connectors``
or ``googleapiclient``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from scout.config import settings
from scout.governance.pii import redact

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120.0

# The two structured-output strategies, in the order they are attempted.
MODE_JSON_SCHEMA = "json_schema"
MODE_JSON_OBJECT_FALLBACK = "json_object_fallback"


class ReasoningError(RuntimeError):
    """Base class for reasoning-layer failures."""


class CostCeilingExceededError(ReasoningError):
    """The run has spent its LLM budget. Hard stop — the call is not dispatched."""


class StructuredOutputError(ReasoningError):
    """The model could not be made to return output matching the schema."""


@dataclass
class CallMeta:
    """Everything a caller must persist alongside whatever the model said."""

    agent: str
    model: str
    tier: str
    prompt_version: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    structured_mode: str = MODE_JSON_SCHEMA


# ── Cost metering ─────────────────────────────────────────────────────────
# In-memory, per process. Slice 1 runs one pipeline per process, so a module
# accumulator is the whole "per run" scope. Cross-process persistence is a
# later-slice concern; the shape below (total + per-agent + per-tenant) is
# already what a persisted meter would need.

@dataclass
class _CostState:
    total_usd: float = 0.0
    by_agent: dict[str, float] = field(default_factory=dict)
    by_tenant: dict[str, float] = field(default_factory=dict)
    calls: int = 0


_cost = _CostState()


def run_cost() -> dict[str, Any]:
    """Current run's spend — total, per agent, per tenant, and call count."""
    return {
        "total_usd": _cost.total_usd,
        "by_agent": dict(_cost.by_agent),
        "by_tenant": dict(_cost.by_tenant),
        "calls": _cost.calls,
        "ceiling_usd": settings.llm_cost_ceiling_usd_per_run,
    }


def reset_run_cost() -> None:
    """Start a new run's meter. Call this at the top of a pipeline run."""
    global _cost
    _cost = _CostState()


def _record_cost(agent: str, tenant_id: str, cost_usd: float | None) -> None:
    amount = float(cost_usd or 0.0)
    _cost.total_usd += amount
    _cost.by_agent[agent] = _cost.by_agent.get(agent, 0.0) + amount
    _cost.by_tenant[tenant_id] = _cost.by_tenant.get(tenant_id, 0.0) + amount
    _cost.calls += 1


def _check_ceiling(agent: str) -> None:
    ceiling = settings.llm_cost_ceiling_usd_per_run
    if ceiling and _cost.total_usd >= ceiling:
        raise CostCeilingExceededError(
            f"LLM cost ceiling reached before dispatching {agent!r}: "
            f"${_cost.total_usd:.4f} spent of ${ceiling:.2f} "
            "(LLM_COST_CEILING_USD_PER_RUN). This is a hard stop — the call was "
            "not made. Reset with reasoning.reset_run_cost() to start a new run."
        )


# ── Tier / model resolution ───────────────────────────────────────────────


def resolve_tier(agent: str, tier: str | None = None) -> str:
    """Explicit tier wins; otherwise ``settings.agent_tier[agent]``."""
    if tier is not None:
        if tier not in settings.llm_tiers:
            raise ReasoningError(
                f"Unknown tier {tier!r} — settings.llm_tiers has "
                f"{sorted(settings.llm_tiers)}."
            )
        return tier

    try:
        return settings.agent_tier[agent]
    except KeyError as exc:
        raise ReasoningError(
            f"No tier configured for agent {agent!r}. Add it to "
            "settings.agent_tier — the tier must never be chosen in agent code."
        ) from exc


def resolve_model(tier: str) -> str:
    try:
        return settings.llm_tiers[tier]
    except KeyError as exc:
        raise ReasoningError(
            f"No model configured for tier {tier!r} in settings.llm_tiers."
        ) from exc


def next_tier_up(tier: str) -> str | None:
    """The next tier in the fast -> standard -> deep ladder, or None at the top.

    Reads the ladder from ``settings.llm_tiers`` insertion order so adding a
    tier in config does not require a code change here.
    """
    ladder = list(settings.llm_tiers)
    try:
        index = ladder.index(tier)
    except ValueError:
        return None
    return ladder[index + 1] if index + 1 < len(ladder) else None


# ── Redaction ─────────────────────────────────────────────────────────────


def _redact_messages(messages: list[dict]) -> list[dict]:
    """Redact every message's content. RedactionError propagates — fails closed."""
    redacted: list[dict] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and content:
            redacted.append({**message, "content": redact(content).text})
        else:
            redacted.append(dict(message))
    return redacted


# ── Structured output ─────────────────────────────────────────────────────


def _json_schema_of(schema: Any) -> dict[str, Any]:
    """JSON schema for a pydantic model (v2 ``model_json_schema``)."""
    if hasattr(schema, "model_json_schema"):
        return schema.model_json_schema()
    raise ReasoningError(
        f"schema must be a pydantic model, got {type(schema).__name__!r}."
    )


def _validate(schema: Any, payload: dict) -> Any:
    if hasattr(schema, "model_validate"):
        return schema.model_validate(payload)
    raise ReasoningError(
        f"schema must be a pydantic model, got {type(schema).__name__!r}."
    )


def _schema_response_format(schema: Any) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": getattr(schema, "__name__", "Result"),
            "strict": True,
            "schema": _json_schema_of(schema),
        },
    }


def _fallback_messages(messages: list[dict], schema: Any) -> list[dict]:
    """Paste the schema into a system message for models that ignore json_schema."""
    instruction = (
        "Respond with a single JSON object and nothing else — no prose, no "
        "code fences. It must validate against this JSON Schema:\n\n"
        + json.dumps(_json_schema_of(schema), indent=2)
    )
    return [{"role": "system", "content": instruction}, *messages]


def _extract_content(payload: dict) -> str:
    try:
        return payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise StructuredOutputError(
            f"Malformed chat completion response: {str(payload)[:300]}"
        ) from exc


def _parse_json(content: str) -> dict:
    text = content.strip()
    # Some routed models wrap JSON in a fenced block despite instructions.
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# ── Transport ─────────────────────────────────────────────────────────────


def _client() -> httpx.AsyncClient:
    if not settings.openrouter_api_key:
        raise ReasoningError(
            "No OpenRouter API key configured (settings.openrouter_api_key / "
            "OPENROUTER_API_KEY). Reasoning routes through OpenRouter; only "
            "embeddings go direct to OpenAI."
        )
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # config.py has llm_title but no HTTP-Referer setting; OpenRouter
        # treats Referer as optional. Flagged rather than invented.
        "X-Title": settings.llm_title,
    }
    return httpx.AsyncClient(
        base_url=settings.llm_base_url.rstrip("/"),
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


async def _post_chat(
    client: httpx.AsyncClient,
    model: str,
    messages: list[dict],
    response_format: dict,
) -> dict:
    """One chat completion. Mirrors the OpenAI SDK's chat.completions.create shape."""
    response = await client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "response_format": response_format,
            # OpenRouter returns generation cost when asked for it.
            "usage": {"include": True},
        },
    )
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"chat/completions returned {response.status_code}: {response.text[:500]}",
            request=response.request,
            response=response,
        )
    return response.json()


def _usage_of(payload: dict) -> tuple[int | None, int | None, float | None]:
    usage = payload.get("usage") or {}
    return (
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        usage.get("cost"),
    )


# ── Public API ────────────────────────────────────────────────────────────


async def complete(
    agent: str,
    prompt_version: str,
    messages: list[dict],
    schema: Any,
    tier: str | None = None,
) -> tuple[Any, CallMeta]:
    """Call a model and return ``(parsed_schema_instance, CallMeta)``.

    Args:
        agent: agent name, keyed into ``settings.agent_tier``. Never a model.
        prompt_version: version string of the prompt template in use. Carried
            on :class:`CallMeta` because ``itr360.triage_result.prompt_version``
            is NOT NULL — it must not be possible to forget it at persist time.
        messages: chat messages. Every ``content`` is redacted before dispatch.
        schema: a pydantic model class. The return value is an instance of it.
        tier: explicit tier override — how an agent escalates. The agent still
            never names a model.

    Raises:
        CostCeilingExceededError: the run's budget is spent. Nothing dispatched.
        RedactionError: redaction failed. Nothing dispatched.
        StructuredOutputError: neither the schema request nor the fallback
            produced output matching ``schema``.
        ReasoningError: misconfiguration (unknown agent, tier, or missing key).
    """
    _check_ceiling(agent)

    resolved_tier = resolve_tier(agent, tier)
    model = resolve_model(resolved_tier)
    tenant_id = str(settings.tenant_id)

    redacted = _redact_messages(messages)

    started = time.monotonic()
    last_error: Exception | None = None

    async with _client() as client:
        for mode in (MODE_JSON_SCHEMA, MODE_JSON_OBJECT_FALLBACK):
            if mode == MODE_JSON_SCHEMA:
                sent, response_format = redacted, _schema_response_format(schema)
            else:
                logger.warning(
                    "reasoning: %s on %s did not honour json_schema (%s) — "
                    "retrying once with the schema in the system prompt.",
                    agent, model, last_error,
                )
                sent = _fallback_messages(redacted, schema)
                response_format = {"type": "json_object"}

            try:
                payload = await _post_chat(client, model, sent, response_format)
                parsed = _validate(schema, _parse_json(_extract_content(payload)))
            except Exception as exc:  # noqa: BLE001 — classified by the retry loop
                last_error = exc
                continue

            tokens_in, tokens_out, cost_usd = _usage_of(payload)
            _record_cost(agent, tenant_id, cost_usd)

            return parsed, CallMeta(
                agent=agent,
                model=model,
                tier=resolved_tier,
                prompt_version=prompt_version,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                latency_ms=int((time.monotonic() - started) * 1000),
                structured_mode=mode,
            )

    raise StructuredOutputError(
        f"{agent!r} on {model!r} produced no schema-valid output after the "
        f"json_object fallback: {type(last_error).__name__}: {last_error}"
    ) from last_error


__all__ = [
    "CallMeta",
    "CostCeilingExceededError",
    "ReasoningError",
    "StructuredOutputError",
    "complete",
    "next_tier_up",
    "reset_run_cost",
    "resolve_model",
    "resolve_tier",
    "run_cost",
]
