"""
tests/test_llm_analyst.py — Tests for LLMAnalyst (Sprint 16).

All tests work WITHOUT a real Anthropic API key:
  - Fallback path is exercised directly (no key configured in test env)
  - The anthropic client is patched with unittest.mock where needed to
    verify LLM-path behaviour without hitting the real API

Run with:
    poetry run python -m pytest tests/test_llm_analyst.py -v
"""

import unittest.mock as mock

import pytest

from scout.analysis.llm_analyst import LLMAnalyst, build_prompt, _truncate, _MAX_DETAIL_CHARS


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_worker_dict(
    worker_name: str = "WorkforceWorker",
    tenant_id: str = "test-tenant",
    with_findings: bool = True,
) -> dict:
    """Return a dict that mirrors WorkerResult.to_dict() output."""
    findings = []
    if with_findings:
        findings = [
            {
                "title": "3 managers are overloaded",
                "detail": "Elena, James, Sarah each have >10 direct reports",
                "severity": "high",
                "data": {"overloaded": 3},
                "recommended_action": "Review org design within 30 days",
            },
            {
                "title": "Key-person risk: CTO has 14 direct reports",
                "detail": "Single point of failure in engineering leadership",
                "severity": "critical",
                "data": {"span": 14},
                "recommended_action": "Hire VP of Engineering",
            },
        ]
    return {
        "worker": worker_name,
        "tenant_id": tenant_id,
        "summary_stats": {"total_headcount": 120, "avg_span": 6.5},
        "findings": findings,
        "error": None,
    }


def make_31_worker_dicts(tenant_id: str = "acme-corp") -> list[dict]:
    """Return 36 mock worker result dicts (mirrors the real insights endpoint)."""
    worker_names = [
        "WorkforceWorker", "VendorWorker", "PipelineVelocityWorker",
        "ChurnPredictionWorker", "ExpansionRevenueWorker", "PricingIntegrityWorker",
        "SalesCapacityWorker", "SaasLicenseWorker", "VendorNegotiationWorker",
        "HeadcountEfficiencyWorker", "ProcessBottleneckWorker", "WorkingCapitalWorker",
        "SentimentWorker", "TamPenetrationWorker", "MarketingFunnelWorker",
        "CrossSellIntelligenceWorker", "LeadToCashWorker", "HireToRetireWorker",
        "ProcureToPayWorker", "IssueToResolutionWorker", "EngagementIntelligenceWorker",
        "OutreachSequenceWorker", "LeadEnrichmentWorker", "MeetingPrepWorker",
        "RenewalWorkflowWorker", "CrossSellCampaignWorker", "OnboardingWorker",
        "OffboardingWorker", "APProcessingWorker", "LicenseManagementWorker",
        "ExpenseAuditWorker",
        # Sprint 18
        "VendorBenchmarkWorker",
        # Sprint 57: R&D / DORA
        "DORAMetricsWorker", "GitHubVelocityWorker",
        # Sprint 59: Security Hygiene
        "SecurityHygieneWorker",
        # Sprint 62: Process Conformance
        "ProcessConformanceWorker",
    ]
    assert len(worker_names) == 36
    return [make_worker_dict(name, tenant_id) for name in worker_names]


# ── Import tests ───────────────────────────────────────────────────────────────

class TestLLMAnalystImport:

    def test_llm_analyst_is_importable(self):
        """Basic smoke test — the module must import without errors."""
        from scout.analysis.llm_analyst import LLMAnalyst  # noqa: F401
        assert LLMAnalyst is not None

    def test_build_prompt_is_importable(self):
        from scout.analysis.llm_analyst import build_prompt  # noqa: F401
        assert build_prompt is not None


# ── Fallback tests (no API key) ────────────────────────────────────────────────

class TestLLMAnalystFallback:

    def _make_no_key_analyst(self) -> LLMAnalyst:
        """Return an LLMAnalyst backed by an unavailable provider."""
        from scout.analysis.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="", model="claude-sonnet-4-5")
        return LLMAnalyst(provider=provider)

    def test_fallback_when_no_api_key(self):
        """With no key, generate_memo must return a non-empty string."""
        analyst = self._make_no_key_analyst()
        result = analyst.generate_memo([make_worker_dict()], "test-tenant")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_narrative_mentions_tenant(self):
        """Fallback narrative must reference the tenant_id."""
        analyst = self._make_no_key_analyst()
        tenant = "acme-corp-42"
        result = analyst.generate_memo([make_worker_dict(tenant_id=tenant)], tenant)
        assert tenant in result

    def test_generate_memo_accepts_empty_worker_list(self):
        """An empty worker list must not crash."""
        analyst = self._make_no_key_analyst()
        result = analyst.generate_memo([], "test-tenant")
        assert isinstance(result, str)

    def test_generate_memo_accepts_full_worker_results(self):
        """31 mock worker result dicts must not crash."""
        analyst = self._make_no_key_analyst()
        results = make_31_worker_dicts()
        narrative = analyst.generate_memo(results, "acme-corp")
        assert isinstance(narrative, str)
        assert len(narrative) > 50

    def test_fallback_handles_worker_with_error(self):
        """A worker dict with error set must not crash fallback."""
        analyst = self._make_no_key_analyst()
        error_worker = {
            "worker": "FailingWorker",
            "tenant_id": "test-tenant",
            "summary_stats": {},
            "findings": [],
            "error": "Neo4j connection refused",
        }
        result = analyst.generate_memo([error_worker], "test-tenant")
        assert isinstance(result, str)

    def test_fallback_provider_is_unavailable(self):
        """When provider has no key, is_available must be False and _client None."""
        analyst = self._make_no_key_analyst()
        assert analyst._provider.is_available is False
        assert analyst._client is None  # backwards-compat shim


# ── Prompt builder tests ───────────────────────────────────────────────────────

class TestPromptBuilder:

    def test_prompt_builder_returns_string(self):
        prompt = build_prompt([make_worker_dict()], "test-tenant")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_prompt_builder_includes_tenant_id(self):
        prompt = build_prompt([make_worker_dict()], "pe-portfolio-co")
        assert "pe-portfolio-co" in prompt

    def test_prompt_builder_includes_worker_name(self):
        prompt = build_prompt([make_worker_dict("VendorWorker")], "t")
        assert "VendorWorker" in prompt

    def test_prompt_builder_truncates_long_details(self):
        """Finding details longer than _MAX_DETAIL_CHARS must be truncated."""
        long_detail = "X" * 500  # 500 chars — well over the 200-char limit
        worker = {
            "worker": "WorkforceWorker",
            "tenant_id": "t",
            "summary_stats": {},
            "findings": [
                {
                    "title": "Some finding",
                    "detail": long_detail,
                    "severity": "high",
                    "data": {},
                    "recommended_action": "",
                }
            ],
            "error": None,
        }
        prompt = build_prompt([worker], "t")
        # The original 500-char string must NOT appear verbatim
        assert long_detail not in prompt
        # But a truncated version (ending with ...) must be present
        assert "X" * _MAX_DETAIL_CHARS + "..." in prompt

    def test_prompt_builder_limits_findings_per_worker(self):
        """Only top 3 findings per worker should appear in the prompt."""
        findings = [
            {
                "title": f"Finding {i}",
                "detail": f"Detail {i}",
                "severity": "low",
                "data": {},
                "recommended_action": "",
            }
            for i in range(1, 8)  # 7 findings
        ]
        worker = {
            "worker": "WorkforceWorker",
            "tenant_id": "t",
            "summary_stats": {},
            "findings": findings,
            "error": None,
        }
        prompt = build_prompt([worker], "t")
        # Finding 4 through 7 must NOT appear
        assert "Finding 4" not in prompt
        assert "Finding 7" not in prompt
        # Findings 1-3 must appear
        assert "Finding 1" in prompt
        assert "Finding 3" in prompt

    def test_prompt_builder_handles_empty_worker_list(self):
        prompt = build_prompt([], "empty-tenant")
        assert isinstance(prompt, str)
        assert "empty-tenant" in prompt

    def test_prompt_builder_handles_worker_with_error(self):
        error_worker = {
            "worker": "FailingWorker",
            "tenant_id": "t",
            "summary_stats": {},
            "findings": [],
            "error": "Connection refused",
        }
        prompt = build_prompt([error_worker], "t")
        assert "FailingWorker" in prompt
        assert "ERROR" in prompt

    def test_prompt_builder_skips_nested_dict_stats(self):
        """Nested dict values in summary_stats should not crash the builder."""
        worker = make_worker_dict()
        worker["summary_stats"]["nested"] = {"a": 1, "b": 2}
        prompt = build_prompt([worker], "t")
        assert isinstance(prompt, str)


# ── Truncate helper tests ──────────────────────────────────────────────────────

class TestTruncate:

    def test_truncate_short_string_unchanged(self):
        s = "short"
        assert _truncate(s, 200) == s

    def test_truncate_exact_length_unchanged(self):
        s = "a" * 200
        assert _truncate(s, 200) == s

    def test_truncate_long_string_appends_ellipsis(self):
        s = "b" * 300
        result = _truncate(s, 200)
        assert result.endswith("...")
        assert len(result) == 203  # 200 chars + "..."

    def test_truncate_uses_max_detail_chars_default(self):
        long = "c" * (_MAX_DETAIL_CHARS + 50)
        result = _truncate(long)
        assert result.endswith("...")
        assert len(result) == _MAX_DETAIL_CHARS + 3


# ── LLM path tests (mocked API client) ────────────────────────────────────────

class TestLLMAnalystWithMockedClient:
    """
    Tests for the LLM call path using a mocked AnthropicProvider._client.

    The mock is injected into the provider so we verify the full stack
    (LLMAnalyst → AnthropicProvider → anthropic SDK) without real API calls.
    """

    def _make_analyst_with_mock_client(self, response_text: str = "Mocked memo.") -> LLMAnalyst:
        """Return an LLMAnalyst backed by an AnthropicProvider with a mocked SDK client."""
        from scout.analysis.providers.anthropic_provider import AnthropicProvider

        mock_message = mock.MagicMock()
        mock_message.content = [mock.MagicMock(text=response_text)]

        mock_sdk_client = mock.MagicMock()
        mock_sdk_client.messages.create.return_value = mock_message

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._model = "claude-sonnet-4-5"
        provider._max_tokens = 1024
        provider._client = mock_sdk_client  # inject mock at the SDK layer

        return LLMAnalyst(provider=provider)

    def test_calls_provider_when_available(self):
        analyst = self._make_analyst_with_mock_client("PE memo here.")
        result = analyst.generate_memo([make_worker_dict()], "test-tenant")
        assert result == "PE memo here."
        analyst._provider._client.messages.create.assert_called_once()

    def test_claude_call_uses_correct_model(self):
        analyst = self._make_analyst_with_mock_client()
        analyst.generate_memo([make_worker_dict()], "t")
        call_kwargs = analyst._provider._client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-5"

    def test_claude_call_passes_system_prompt(self):
        analyst = self._make_analyst_with_mock_client()
        analyst.generate_memo([make_worker_dict()], "t")
        call_kwargs = analyst._provider._client.messages.create.call_args[1]
        assert "system" in call_kwargs
        assert len(call_kwargs["system"]) > 0

    def test_fallback_used_when_api_raises(self):
        """If the provider raises internally, fallback narrative must be returned."""
        from scout.analysis.providers.anthropic_provider import AnthropicProvider

        mock_sdk_client = mock.MagicMock()
        mock_sdk_client.messages.create.side_effect = RuntimeError("Network error")

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._model = "claude-sonnet-4-5"
        provider._max_tokens = 1024
        provider._client = mock_sdk_client

        analyst = LLMAnalyst(provider=provider)
        result = analyst.generate_memo([make_worker_dict()], "test-tenant")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_used_when_api_raises_does_not_reraise(self):
        """API failure must never propagate as an exception."""
        from scout.analysis.providers.anthropic_provider import AnthropicProvider

        mock_sdk_client = mock.MagicMock()
        mock_sdk_client.messages.create.side_effect = Exception("Timeout")

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._model = "claude-sonnet-4-5"
        provider._max_tokens = 1024
        provider._client = mock_sdk_client

        analyst = LLMAnalyst(provider=provider)
        try:
            analyst.generate_memo([make_worker_dict()], "test-tenant")
        except Exception as e:
            pytest.fail(f"generate_memo raised an exception: {e}")

    def test_memo_contains_tenant_context_in_prompt(self):
        """The prompt sent to the provider must reference the tenant_id."""
        analyst = self._make_analyst_with_mock_client()
        analyst.generate_memo([make_worker_dict()], "my-special-tenant")
        call_kwargs = analyst._provider._client.messages.create.call_args[1]
        user_message = call_kwargs["messages"][0]["content"]
        assert "my-special-tenant" in user_message

    def test_max_tokens_is_set(self):
        analyst = self._make_analyst_with_mock_client()
        analyst.generate_memo([make_worker_dict()], "t")
        call_kwargs = analyst._provider._client.messages.create.call_args[1]
        assert "max_tokens" in call_kwargs
        assert call_kwargs["max_tokens"] > 0
