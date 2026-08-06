"""
scout/analysis/providers/factory.py — build_provider() factory.

Reads LLM_PROVIDER, LLM_MODEL, and related settings and returns the
appropriate concrete LLMProvider. All provider imports are local so
missing optional SDK packages never break startup.

Adding a new provider:
  1. Create scout/analysis/providers/my_provider.py (subclass LLMProvider)
  2. Add a branch in _REGISTRY below
  3. Set LLM_PROVIDER=my_provider in your environment
"""

from __future__ import annotations

import logging

from scout.analysis.providers.base import LLMProvider
from scout.config import settings

logger = logging.getLogger(__name__)


def build_provider() -> LLMProvider:
    """
    Instantiate and return the configured LLM provider.

    Resolution order:
      1. Read settings.llm_provider (default: "anthropic")
      2. Instantiate the matching provider with its API key and model
      3. If the provider SDK is missing or the key is absent, is_available
         will be False — LLMAnalyst handles the fallback to templates

    Returns:
        A concrete LLMProvider instance (always — never raises).
    """
    provider_name = (settings.llm_provider or "anthropic").lower().strip()
    model = settings.llm_model or "claude-sonnet-4-5"
    base_url = settings.llm_base_url or ""

    logger.info(
        "build_provider: provider=%s model=%s base_url=%r",
        provider_name,
        model,
        base_url or "(default)",
    )

    if provider_name == "anthropic":
        from scout.analysis.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=model,
        )

    if provider_name == "openai":
        from scout.analysis.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=model,
            base_url=base_url,
        )

    if provider_name == "gemini":
        from scout.analysis.providers.gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=model,
        )

    if provider_name == "ollama":
        from scout.analysis.providers.ollama_provider import OllamaProvider
        return OllamaProvider(
            model=model,
            base_url=base_url,
        )

    # Unknown provider — log clearly and fall back to Anthropic (may itself
    # be unavailable, which LLMAnalyst handles gracefully)
    logger.warning(
        "build_provider: unknown provider %r — falling back to anthropic. "
        "Supported: anthropic, openai, gemini, ollama",
        provider_name,
    )
    from scout.analysis.providers.anthropic_provider import AnthropicProvider
    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        model=model,
    )
