"""
scout/analysis/providers/openai_provider.py — OpenAI / OpenAI-compatible provider.

Wraps the `openai` SDK using the Chat Completions API. This provider also
works with any OpenAI-compatible endpoint (Azure OpenAI, vLLM, LM Studio,
Groq, Together AI, etc.) by setting llm_base_url in config.

Environment variable: OPENAI_API_KEY
Supported models: gpt-4o, gpt-4o-mini, gpt-4-turbo, o1-mini, etc.

For Azure OpenAI:
  LLM_PROVIDER=openai
  LLM_MODEL=gpt-4o
  LLM_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment>
  OPENAI_API_KEY=<azure-api-key>

For vLLM / LM Studio running locally:
  LLM_PROVIDER=openai
  LLM_MODEL=mistral-7b-instruct   (or whatever you loaded)
  LLM_BASE_URL=http://localhost:1234/v1
  OPENAI_API_KEY=not-needed        (vLLM ignores it)
"""

from __future__ import annotations

import logging

from scout.analysis.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    LLM provider backed by the OpenAI Chat Completions API.

    Also works with any OpenAI-compatible HTTP endpoint by supplying
    a custom base_url.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        max_tokens: int = 1024,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = None

        if not api_key and not base_url:
            logger.info("OpenAIProvider: no API key and no base_url — provider unavailable")
            return

        try:
            import openai

            kwargs: dict = {"api_key": api_key or "not-required"}
            if base_url:
                kwargs["base_url"] = base_url

            self._client = openai.OpenAI(**kwargs)
            endpoint = base_url or "https://api.openai.com"
            logger.info(
                "OpenAIProvider: initialised (model=%s, endpoint=%s)", model, endpoint
            )
        except ImportError:
            logger.warning(
                "OpenAIProvider: `openai` package not installed — "
                "run `poetry add openai` to enable live calls"
            )

    # ── LLMProvider interface ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def complete(self, system: str, messages: list[dict]) -> str:
        """
        Call the OpenAI Chat Completions API.

        Inserts the system prompt as the first message with role="system",
        which is the standard OpenAI pattern.
        """
        if not self._client:
            return "[OpenAIProvider unavailable — no client initialised]"

        try:
            full_messages = [{"role": "system", "content": system}] + list(messages)
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=full_messages,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.error("OpenAIProvider.complete failed: %s", exc, exc_info=True)
            return f"[OpenAIProvider error: {exc}]"
