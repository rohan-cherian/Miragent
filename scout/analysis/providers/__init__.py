"""
scout/analysis/providers — LLM provider abstraction layer.

Exports the LLMProvider ABC and the build_provider() factory.

Usage:
    from scout.analysis.providers import build_provider

    provider = build_provider()          # uses settings
    text = provider.complete(system, messages)

Adding a new provider:
    1. Subclass LLMProvider in a new module (e.g. my_provider.py)
    2. Implement complete() — it must always return a str and never raise
    3. Register it in build_provider() below
"""

from scout.analysis.providers.base import LLMProvider
from scout.analysis.providers.factory import build_provider

__all__ = ["LLMProvider", "build_provider"]
