"""
scout/analysis/providers/ollama_provider.py — Ollama (local models) provider.

Ollama runs open-weight models locally (Llama 3, Mistral, Phi-3, Gemma, etc.)
and exposes an OpenAI-compatible HTTP API. No API key is required.

Default endpoint: http://localhost:11434
Override with: LLM_BASE_URL=http://your-ollama-host:11434

Prerequisites:
  1. Install Ollama: https://ollama.ai
  2. Pull a model: `ollama pull llama3.1`
  3. Start the server: `ollama serve` (usually auto-starts on install)

This provider uses the `openai` SDK pointed at the Ollama endpoint rather
than the `ollama` Python package — it's a thinner dependency and works
with any OpenAI-compatible backend, not just Ollama.

Supported models (whatever you have pulled):
  llama3.1, llama3.2, mistral, phi3, gemma2, qwen2.5, deepseek-r1, etc.

For a custom SLM you've built and want to serve via Ollama:
  1. Create a Modelfile pointing at your GGUF weights
  2. `ollama create my-company-model -f Modelfile`
  3. Set LLM_MODEL=my-company-model
"""

from __future__ import annotations

import logging

from scout.analysis.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(LLMProvider):
    """
    LLM provider backed by a locally running Ollama instance.

    Uses the `openai` Python SDK with the base_url pointed at Ollama's
    OpenAI-compatible endpoint (/v1). This requires `poetry add openai`
    but does NOT require an OpenAI API key — Ollama ignores the key field.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "",
        max_tokens: int = 1024,
    ) -> None:
        self._model_name = model
        self._max_tokens = max_tokens
        self._client = None

        endpoint = (base_url.rstrip("/") or _DEFAULT_OLLAMA_URL) + "/v1"

        try:
            import openai

            # Ollama doesn't validate the API key — any non-empty string works.
            self._client = openai.OpenAI(
                api_key="ollama",
                base_url=endpoint,
            )
            logger.info(
                "OllamaProvider: initialised (model=%s, endpoint=%s)",
                model,
                endpoint,
            )
        except ImportError:
            logger.warning(
                "OllamaProvider: `openai` package not installed — "
                "run `poetry add openai` to enable Ollama calls"
            )

    # ── LLMProvider interface ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def complete(self, system: str, messages: list[dict]) -> str:
        """
        Call the Ollama Chat Completions endpoint (OpenAI-compatible).

        System prompt is prepended as a role="system" message, which
        Ollama honours for all models that support system instructions.
        """
        if not self._client:
            return "[OllamaProvider unavailable — no client initialised]"

        try:
            full_messages = [{"role": "system", "content": system}] + list(messages)
            response = self._client.chat.completions.create(
                model=self._model_name,
                max_tokens=self._max_tokens,
                messages=full_messages,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.error(
                "OllamaProvider.complete failed (is Ollama running?): %s",
                exc,
                exc_info=True,
            )
            return f"[OllamaProvider error: {exc}]"
