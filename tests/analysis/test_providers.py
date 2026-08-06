"""
tests/analysis/test_providers.py — LLMProvider abstraction layer tests.

Tests the ABC contract, each concrete provider's initialisation behaviour,
the factory, and LLMAnalyst's provider-agnostic wiring — all without
making real API calls or requiring any SDK to be installed.
"""

from __future__ import annotations

import pytest

from scout.analysis.providers.base import LLMProvider


# ── Helpers ───────────────────────────────────────────────────────────────

class _EchoProvider(LLMProvider):
    """
    Minimal test double that echoes the user message back.
    Used to verify LLMAnalyst wiring without any real API calls.
    """

    def __init__(self, available: bool = True) -> None:
        self._available = available

    @property
    def name(self) -> str:
        return "echo"

    @property
    def model(self) -> str:
        return "echo-1.0"

    @property
    def is_available(self) -> bool:
        return self._available

    def complete(self, system: str, messages: list[dict]) -> str:
        if not self._available:
            return "[EchoProvider unavailable]"
        user_content = messages[-1].get("content", "") if messages else ""
        return f"ECHO: {user_content[:80]}"


class _ErrorProvider(LLMProvider):
    """Provider that returns an error sentinel — simulates API failure."""

    @property
    def name(self) -> str:
        return "error"

    @property
    def model(self) -> str:
        return "error-1.0"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system: str, messages: list[dict]) -> str:
        return "[error: simulated provider failure]"


# ── ABC contract tests ─────────────────────────────────────────────────────

class TestLLMProviderABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract]

    def test_echo_provider_satisfies_contract(self):
        p = _EchoProvider()
        assert p.name == "echo"
        assert p.model == "echo-1.0"
        assert p.is_available is True
        result = p.complete("system", [{"role": "user", "content": "hello"}])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unavailable_provider_returns_string(self):
        p = _EchoProvider(available=False)
        assert p.is_available is False
        result = p.complete("system", [{"role": "user", "content": "hello"}])
        assert isinstance(result, str)


# ── Concrete provider init (no live calls) ─────────────────────────────────

class TestAnthropicProviderInit:
    def test_no_key_is_unavailable(self):
        from scout.analysis.providers.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="", model="claude-sonnet-4-5")
        assert p.is_available is False
        assert p.name == "anthropic"
        assert p.model == "claude-sonnet-4-5"

    def test_placeholder_key_is_unavailable(self):
        from scout.analysis.providers.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-your-key-here", model="claude-sonnet-4-5")
        assert p.is_available is False

    def test_complete_when_unavailable_returns_string(self):
        from scout.analysis.providers.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="", model="claude-sonnet-4-5")
        result = p.complete("system", [{"role": "user", "content": "test"}])
        assert isinstance(result, str)
        assert len(result) > 0


class TestOpenAIProviderInit:
    def test_no_key_no_url_is_unavailable(self):
        from scout.analysis.providers.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="", model="gpt-4o")
        assert p.is_available is False
        assert p.name == "openai"
        assert p.model == "gpt-4o"

    def test_complete_when_unavailable_returns_string(self):
        from scout.analysis.providers.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="", model="gpt-4o")
        result = p.complete("system", [{"role": "user", "content": "test"}])
        assert isinstance(result, str)


class TestGeminiProviderInit:
    def test_no_key_is_unavailable(self):
        from scout.analysis.providers.gemini_provider import GeminiProvider
        p = GeminiProvider(api_key="", model="gemini-2.0-flash")
        assert p.is_available is False
        assert p.name == "gemini"
        assert p.model == "gemini-2.0-flash"

    def test_complete_when_unavailable_returns_string(self):
        from scout.analysis.providers.gemini_provider import GeminiProvider
        p = GeminiProvider(api_key="", model="gemini-2.0-flash")
        result = p.complete("system", [{"role": "user", "content": "test"}])
        assert isinstance(result, str)


class TestOllamaProviderInit:
    def test_init_without_openai_sdk_is_unavailable(self, monkeypatch):
        """If the openai package is not installed, Ollama should be unavailable."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("openai not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from scout.analysis.providers import ollama_provider as om
        import importlib
        importlib.reload(om)

        p = om.OllamaProvider(model="llama3.1")
        assert p.is_available is False

    def test_properties(self):
        from scout.analysis.providers.ollama_provider import OllamaProvider
        p = OllamaProvider(model="llama3.1", base_url="http://localhost:11434")
        assert p.name == "ollama"
        assert p.model == "llama3.1"

    def test_complete_when_unavailable_returns_string(self, monkeypatch):
        from scout.analysis.providers.ollama_provider import OllamaProvider
        p = OllamaProvider.__new__(OllamaProvider)
        p._model_name = "llama3.1"
        p._max_tokens = 1024
        p._client = None  # simulate unavailable
        result = p.complete("system", [{"role": "user", "content": "test"}])
        assert isinstance(result, str)
        assert "unavailable" in result.lower()


# ── Factory tests ──────────────────────────────────────────────────────────

class TestBuildProvider:
    def test_default_provider_is_anthropic(self, monkeypatch):
        monkeypatch.setattr("scout.config.settings.llm_provider", "anthropic")
        monkeypatch.setattr("scout.config.settings.llm_model", "claude-sonnet-4-5")
        monkeypatch.setattr("scout.config.settings.anthropic_api_key", "")

        from scout.analysis.providers.factory import build_provider
        p = build_provider()
        assert p.name == "anthropic"

    def test_openai_provider_selected(self, monkeypatch):
        monkeypatch.setattr("scout.config.settings.llm_provider", "openai")
        monkeypatch.setattr("scout.config.settings.llm_model", "gpt-4o")
        monkeypatch.setattr("scout.config.settings.openai_api_key", "")
        monkeypatch.setattr("scout.config.settings.llm_base_url", "")

        from scout.analysis.providers.factory import build_provider
        p = build_provider()
        assert p.name == "openai"
        assert p.model == "gpt-4o"

    def test_gemini_provider_selected(self, monkeypatch):
        monkeypatch.setattr("scout.config.settings.llm_provider", "gemini")
        monkeypatch.setattr("scout.config.settings.llm_model", "gemini-2.0-flash")
        monkeypatch.setattr("scout.config.settings.gemini_api_key", "")

        from scout.analysis.providers.factory import build_provider
        p = build_provider()
        assert p.name == "gemini"

    def test_ollama_provider_selected(self, monkeypatch):
        monkeypatch.setattr("scout.config.settings.llm_provider", "ollama")
        monkeypatch.setattr("scout.config.settings.llm_model", "llama3.1")
        monkeypatch.setattr("scout.config.settings.llm_base_url", "")

        from scout.analysis.providers.factory import build_provider
        p = build_provider()
        assert p.name == "ollama"

    def test_unknown_provider_falls_back_to_anthropic(self, monkeypatch):
        monkeypatch.setattr("scout.config.settings.llm_provider", "some-future-model")
        monkeypatch.setattr("scout.config.settings.llm_model", "model-x")
        monkeypatch.setattr("scout.config.settings.anthropic_api_key", "")

        from scout.analysis.providers.factory import build_provider
        p = build_provider()
        assert p.name == "anthropic"


# ── LLMAnalyst provider wiring ─────────────────────────────────────────────

class TestLLMAnalystProviderWiring:
    def _make_result(self) -> list[dict]:
        return [
            {
                "worker": "TestWorker",
                "summary_stats": {"total": 1},
                "findings": [
                    {
                        "title": "Test finding",
                        "detail": "Detail here",
                        "severity": "high",
                        "recommended_action": "Do something",
                        "confidence": "high",
                        "specific_entities": [],
                        "context_note": "",
                        "data": {},
                    }
                ],
                "error": None,
            }
        ]

    def test_uses_injected_provider(self):
        from scout.analysis.llm_analyst import LLMAnalyst
        provider = _EchoProvider(available=True)
        analyst = LLMAnalyst(provider=provider)
        assert analyst._provider is provider
        assert analyst._provider.is_available is True

    def test_generates_memo_via_provider(self):
        from scout.analysis.llm_analyst import LLMAnalyst
        analyst = LLMAnalyst(provider=_EchoProvider())
        result = analyst.generate_memo(self._make_result(), "test-tenant")
        assert isinstance(result, str)
        assert "ECHO:" in result  # echo provider signature

    def test_falls_back_when_provider_unavailable(self):
        from scout.analysis.llm_analyst import LLMAnalyst
        analyst = LLMAnalyst(provider=_EchoProvider(available=False))
        assert analyst._provider.is_available is False
        # Should call fallback — returns a string without raising
        result = analyst.generate_memo(self._make_result(), "test-tenant")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_falls_back_on_error_sentinel(self):
        """Provider that returns an error sentinel should trigger fallback."""
        from scout.analysis.llm_analyst import LLMAnalyst
        analyst = LLMAnalyst(provider=_ErrorProvider())
        result = analyst.generate_memo(self._make_result(), "test-tenant")
        assert isinstance(result, str)
        # Should NOT contain the raw error sentinel in the final output
        assert "[error:" not in result.lower() or "Scout Intelligence" in result

    def test_client_shim_is_set_when_available(self):
        """_client shim is non-None when provider is available (backwards compat)."""
        from scout.analysis.llm_analyst import LLMAnalyst
        analyst = LLMAnalyst(provider=_EchoProvider(available=True))
        assert analyst._client is not None

    def test_client_shim_is_none_when_unavailable(self):
        """_client shim is None when provider is unavailable (backwards compat)."""
        from scout.analysis.llm_analyst import LLMAnalyst
        analyst = LLMAnalyst(provider=_EchoProvider(available=False))
        assert analyst._client is None

    def test_default_construction_builds_from_settings(self, monkeypatch):
        """LLMAnalyst() with no args builds provider from settings."""
        monkeypatch.setattr("scout.config.settings.llm_provider", "anthropic")
        monkeypatch.setattr("scout.config.settings.llm_model", "claude-sonnet-4-5")
        monkeypatch.setattr("scout.config.settings.anthropic_api_key", "")

        from scout.analysis.llm_analyst import LLMAnalyst
        analyst = LLMAnalyst()
        assert analyst._provider.name == "anthropic"
        assert analyst._provider.is_available is False  # no key set
