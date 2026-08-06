"""
scout/analysis/providers/gemini_provider.py — Google Gemini provider.

Wraps the `google-generativeai` SDK. Gemini's API merges the system
instruction with the conversation rather than treating it as a separate
top-level field — this provider handles that translation.

Environment variable: GEMINI_API_KEY (from Google AI Studio or Vertex AI)
Supported models: gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash, etc.

Note on Vertex AI: Vertex uses a different SDK (`google-cloud-aiplatform`).
If you need Vertex instead of AI Studio, implement a VertexGeminiProvider
subclass — the interface is identical, only the client init differs.
"""

from __future__ import annotations

import logging

from scout.analysis.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """
    LLM provider backed by Google's Gemini API (AI Studio).

    Uses `google.generativeai` (pip: google-generativeai).
    The system prompt is passed as a `system_instruction` to the model
    constructor — Gemini does not accept it inline in the messages list.
    """

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        self._model_name = model
        self._max_tokens = max_tokens
        self._model = None

        if not api_key:
            logger.info("GeminiProvider: no API key — provider unavailable")
            return

        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            # Store the configured module for use in complete()
            self._genai = genai
            # The model instance is created per-call with the system instruction
            # because Gemini binds system_instruction at construction time.
            # We store a sentinel to confirm init succeeded.
            self._model = True
            logger.info("GeminiProvider: initialised (model=%s)", model)
        except ImportError:
            logger.warning(
                "GeminiProvider: `google-generativeai` package not installed — "
                "run `poetry add google-generativeai` to enable live calls"
            )

    # ── LLMProvider interface ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def complete(self, system: str, messages: list[dict]) -> str:
        """
        Call the Gemini GenerativeModel API.

        Gemini accepts system_instruction at model construction time, so we
        build a fresh model instance per call to honour the system prompt.
        The messages list (OpenAI format) is mapped to Gemini's `contents`
        format: [{"role": ..., "parts": [{"text": ...}]}].
        """
        if not self._model:
            return "[GeminiProvider unavailable — no client initialised]"

        try:
            model_instance = self._genai.GenerativeModel(
                model_name=self._model_name,
                system_instruction=system,
                generation_config=self._genai.types.GenerationConfig(
                    max_output_tokens=self._max_tokens,
                ),
            )

            # Translate OpenAI-format messages to Gemini contents format.
            # Gemini uses "model" instead of "assistant" for the assistant role.
            contents = []
            for msg in messages:
                role = msg.get("role", "user")
                if role == "assistant":
                    role = "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.get("content", "")}],
                })

            response = model_instance.generate_content(contents)
            return response.text or ""
        except Exception as exc:
            logger.error("GeminiProvider.complete failed: %s", exc, exc_info=True)
            return f"[GeminiProvider error: {exc}]"
