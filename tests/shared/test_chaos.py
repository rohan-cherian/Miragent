"""
tests/shared/test_chaos.py — W1-SRC-04 shared emulator ?chaos= switch

Injects 429s, 500s, slow responses, and partial pages on demand.
"""

from __future__ import annotations

import json
import time

import pytest

from scout.shared.chaos import (
    ChaosEffects,
    ChaosMode,
    ChaosSwitch,
    parse_chaos,
    parse_chaos_from_params,
)
from scout.shared.errors import Vendor
from scout.shared.pagination import paginate_zendesk


ITEMS = [{"id": i} for i in range(1, 21)]


class TestParseChaos:
    def test_missing_is_inactive(self):
        effects = parse_chaos(None)
        assert effects.active is False
        assert effects.inject_429 is False
        assert effects.partial is False

    def test_empty_string_inactive(self):
        assert parse_chaos("").active is False
        assert parse_chaos("   ").active is False

    def test_single_modes(self):
        assert parse_chaos("429").inject_429 is True
        assert parse_chaos("500").inject_500 is True
        assert parse_chaos("slow").slow is True
        assert parse_chaos("partial").partial is True

    def test_aliases(self):
        assert parse_chaos("rate_limit").inject_429 is True
        assert parse_chaos("server_error").inject_500 is True
        assert parse_chaos("latency").slow is True
        assert parse_chaos("partial_page").partial is True

    def test_comma_combined(self):
        effects = parse_chaos("slow,partial")
        assert effects.slow is True
        assert effects.partial is True
        assert effects.inject_429 is False

    def test_case_insensitive(self):
        assert parse_chaos("PARTIAL").partial is True
        assert parse_chaos("Rate_Limit").inject_429 is True

    def test_unknown_token_ignored(self):
        effects = parse_chaos("nope,429")
        assert effects.inject_429 is True
        assert effects.modes == frozenset({ChaosMode.RATE_LIMIT})

    def test_from_params(self):
        effects = parse_chaos_from_params({"chaos": "500", "page": "1"})
        assert effects.inject_500 is True


class TestChaosSwitch429:
    def test_returns_real_429_with_retry_after(self):
        switch = ChaosSwitch(Vendor.ZENDESK, sleeper=lambda _: None)
        result = switch.apply({"chaos": "429"})
        assert result.response is not None
        assert result.response.status_code == 429
        assert result.response.headers["Retry-After"] == "5"
        body = json.loads(result.response.body)
        assert body["error"] == "APIRateLimitExceeded"

    def test_salesforce_429_envelope(self):
        switch = ChaosSwitch(Vendor.SALESFORCE, sleeper=lambda _: None)
        result = switch.apply("429")
        body = json.loads(result.response.body)
        assert isinstance(body, list)
        assert body[0]["errorCode"] == "REQUEST_LIMIT_EXCEEDED"


class TestChaosSwitch500:
    def test_returns_real_500(self):
        switch = ChaosSwitch(Vendor.JIRA, sleeper=lambda _: None)
        result = switch.apply({"chaos": "500"})
        assert result.response is not None
        assert result.response.status_code == 500
        body = json.loads(result.response.body)
        assert "errorMessages" in body

    def test_429_wins_over_500(self):
        switch = ChaosSwitch(Vendor.ENTRA, sleeper=lambda _: None)
        result = switch.apply("429,500")
        assert result.response is not None
        assert result.response.status_code == 429


class TestChaosSwitchSlow:
    def test_slow_calls_sleeper(self):
        slept: list[float] = []
        switch = ChaosSwitch(
            Vendor.OKTA,
            slow_seconds=1.5,
            sleeper=slept.append,
        )
        result = switch.apply("slow")
        assert result.response is None
        assert slept == [1.5]
        assert result.effects.slow is True

    def test_slow_actually_delays(self):
        switch = ChaosSwitch(Vendor.OKTA, slow_seconds=0.05)
        start = time.monotonic()
        switch.apply("slow")
        assert time.monotonic() - start >= 0.04

    def test_slow_before_429(self):
        slept: list[float] = []
        switch = ChaosSwitch(
            Vendor.ZENDESK,
            slow_seconds=0.2,
            sleeper=slept.append,
        )
        result = switch.apply("slow,429")
        assert slept == [0.2]
        assert result.response is not None
        assert result.response.status_code == 429


class TestChaosSwitchPartial:
    def test_partial_flag_for_pagination(self):
        switch = ChaosSwitch(Vendor.ZENDESK, sleeper=lambda _: None)
        result = switch.apply({"chaos": "partial"})
        assert result.response is None
        assert result.effects.partial is True

        page = paginate_zendesk(
            ITEMS, per_page=10, force_partial=result.effects.partial
        )
        assert len(page["tickets"]) == 5
        assert page["meta"]["has_more"] is True
        assert "after_cursor" in page["meta"]

    def test_no_chaos_full_page(self):
        switch = ChaosSwitch(Vendor.ZENDESK)
        result = switch.apply({})
        page = paginate_zendesk(
            ITEMS, per_page=10, force_partial=result.effects.partial
        )
        assert len(page["tickets"]) == 10


class TestChaosSwitchValidation:
    def test_invalid_slow_seconds(self):
        with pytest.raises(ValueError):
            ChaosSwitch(Vendor.ZENDESK, slow_seconds=-1)

    def test_inactive_passthrough(self):
        switch = ChaosSwitch(Vendor.ZENDESK)
        result = switch.apply(None)
        assert result.response is None
        assert result.effects == ChaosEffects()
