"""
scout/analysis/providers/anthropic_provider.py — Anthropic Claude provider.

Wraps the `anthropic` SDK. The Anthropic API separates the system prompt
from the messages list — this provider handles that translation so the
rest of the codebase uses the standard (system, messages) shape.

Environment variable: ANTHROPIC_API_KEY
Supported models: claude-sonnet-4-5, claude-3-5-haiku-20241022, claude-opus-4, etc.
"""

from __future__ import annotations

import logging

from scout.analysis.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """
    LLM provider backed by Anthropic's Claude API.

    Initialisation is intentionally lazy-import: the `anthropic` package
    is optional. If it is not installed, is_available returns False and
    LLMAnalyst falls back to the template narrative gracefully.
    """

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = None

        if not api_key or api_key in ("", "sk-ant-your-key-here"):
            logger.info("AnthropicProvider: no API key — provider unavailable")
            return

        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
            logger.info("AnthropicProvider: initialised (model=%s)", model)
        except ImportError:
            logger.warning(
                "AnthropicProvider: `anthropic` package not installed — "
                "run `poetry add anthropic` to enable live calls"
            )

    # ── LLMProvider interface ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def complete(self, system: str, messages: list[dict]) -> str:
        """
        Call the Anthropic Messages API.

        Anthropic requires system as a top-level parameter (not inside messages),
        so we extract it here rather than forcing callers to know that detail.
        """
        if not self._client:
            return "[AnthropicProvider unavailable — no client initialised]"

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
            )
            return response.content[0].text
        except Exception as exc:
            logger.error("AnthropicProvider.complete failed: %s", exc, exc_info=True)
            return f"[AnthropicProvider error: {exc}]"
