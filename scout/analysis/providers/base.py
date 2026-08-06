"""
scout/analysis/providers/base.py — LLMProvider abstract base class.

Every concrete provider must implement exactly one method: complete().
The contract is strict:
  - Always returns a non-empty string
  - Never raises (catches exceptions internally and returns an error string)
  - Is safe to call from multiple threads (providers are module-level singletons)

Why a single complete() method?
  All LLM interaction in Miragent follows the same shape:
    system prompt (persona / rules) + user message (data) → text response
  Chat history, tool-use, and streaming are out of scope for the
  analytics narrative use case. If those patterns emerge, extend the ABC then.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """
    Abstract base class for all LLM backend providers.

    Subclasses wrap a specific SDK (Anthropic, OpenAI, Google, Ollama, ...)
    and translate complete() calls into that SDK's native API shape.

    The rest of Miragent only ever sees LLMProvider — it never imports a
    concrete provider class directly. Swap providers by changing settings;
    no other code changes required.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name, e.g. 'anthropic', 'openai'."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The model identifier being used, e.g. 'claude-sonnet-4-5'."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """
        True if the provider was successfully initialised and can make calls.

        When False, LLMAnalyst falls back to the template narrative.
        A provider sets this False when its SDK is not installed or its
        API key is missing/invalid at construction time.
        """

    @abstractmethod
    def complete(self, system: str, messages: list[dict]) -> str:
        """
        Send a completion request and return the assistant's reply.

        Args:
            system:   The system prompt (persona, rules, output format).
            messages: A list of message dicts in OpenAI chat format:
                      [{"role": "user", "content": "..."}, ...]
                      Most providers accept this format natively.
                      Anthropic requires the system field separately —
                      the concrete provider handles that translation.

        Returns:
            The assistant's reply as a plain string.
            Must never raise — catch all exceptions and return an error
            string; the caller (LLMAnalyst) handles the fallback logic.
        """
