"""
``?chaos=`` switch for vendor API emulators.

Opt-in fault injection so connector resilience can be tested on demand:

  ?chaos=429       — genuine HTTP 429 + Retry-After + vendor envelope
  ?chaos=500       — genuine HTTP 500 + vendor server-error envelope
  ?chaos=slow      — delay the response (real wall-clock sleep)
  ?chaos=partial   — truncated page that still signals more data

Combine with commas: ``?chaos=slow,partial`` or ``?chaos=429``.

Off by default — missing / empty ``chaos`` injects nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from starlette.responses import JSONResponse

from scout.shared.errors import ErrorKind, Vendor, error_response


class ChaosMode(str, Enum):
    RATE_LIMIT = "429"
    SERVER_ERROR = "500"
    SLOW = "slow"
    PARTIAL = "partial"


# Friendly aliases → canonical mode
_ALIASES: dict[str, ChaosMode] = {
    "429": ChaosMode.RATE_LIMIT,
    "rate_limit": ChaosMode.RATE_LIMIT,
    "ratelimit": ChaosMode.RATE_LIMIT,
    "rate-limit": ChaosMode.RATE_LIMIT,
    "500": ChaosMode.SERVER_ERROR,
    "error": ChaosMode.SERVER_ERROR,
    "server_error": ChaosMode.SERVER_ERROR,
    "server-error": ChaosMode.SERVER_ERROR,
    "slow": ChaosMode.SLOW,
    "latency": ChaosMode.SLOW,
    "delay": ChaosMode.SLOW,
    "partial": ChaosMode.PARTIAL,
    "partial_page": ChaosMode.PARTIAL,
    "partial-page": ChaosMode.PARTIAL,
}


@dataclass(frozen=True)
class ChaosEffects:
    """Parsed chaos flags for one request. Empty = no injection."""

    modes: frozenset[ChaosMode] = frozenset()

    @property
    def active(self) -> bool:
        return bool(self.modes)

    @property
    def inject_429(self) -> bool:
        return ChaosMode.RATE_LIMIT in self.modes

    @property
    def inject_500(self) -> bool:
        return ChaosMode.SERVER_ERROR in self.modes

    @property
    def slow(self) -> bool:
        return ChaosMode.SLOW in self.modes

    @property
    def partial(self) -> bool:
        return ChaosMode.PARTIAL in self.modes


def parse_chaos(value: str | None) -> ChaosEffects:
    """
    Parse a ``chaos`` query value into ``ChaosEffects``.

    Accepts comma-separated tokens, case-insensitive.
    Unknown tokens are ignored (so typos don't crash the emulator).
    """
    if value is None or not str(value).strip():
        return ChaosEffects()

    modes: set[ChaosMode] = set()
    for raw in str(value).split(","):
        token = raw.strip().lower()
        if not token:
            continue
        mode = _ALIASES.get(token)
        if mode is not None:
            modes.add(mode)
    return ChaosEffects(modes=frozenset(modes))


def parse_chaos_from_params(params: Mapping[str, str]) -> ChaosEffects:
    """Read ``chaos`` from a query-param mapping (dict or Starlette QueryParams)."""
    value = None
    if hasattr(params, "get"):
        value = params.get("chaos")
    if value is None:
        for key, val in params.items():
            if str(key).lower() == "chaos":
                value = val
                break
    return parse_chaos(value)


@dataclass(frozen=True)
class ChaosResult:
    """
    Outcome of applying chaos to a request.

    ``response`` is set when the emulator should return immediately (429/500).
    ``effects`` always reflects what was requested (including slow/partial).
    """

    effects: ChaosEffects
    response: JSONResponse | None = None


class ChaosSwitch:
    """
    Apply ``?chaos=`` effects for one vendor emulator.

    Usage::

        chaos = ChaosSwitch(Vendor.ZENDESK)
        result = chaos.apply(request.query_params)
        if result.response is not None:
            return result.response  # 429 or 500

        page = paginate_zendesk(items, force_partial=result.effects.partial)
    """

    def __init__(
        self,
        vendor: Vendor | str,
        *,
        slow_seconds: float = 2.0,
        retry_after_seconds: int = 5,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if slow_seconds < 0:
            raise ValueError("slow_seconds must be >= 0")
        if retry_after_seconds < 1:
            raise ValueError("retry_after_seconds must be >= 1")

        self.vendor = Vendor(vendor)
        self.slow_seconds = slow_seconds
        self.retry_after_seconds = retry_after_seconds
        self._sleep = sleeper or time.sleep

    def apply(
        self,
        params: Mapping[str, str] | str | None,
    ) -> ChaosResult:
        """
        Parse chaos from query params (or a raw string) and apply side effects.

        Priority when multiple error modes are set: 429 wins over 500
        (rate-limit is the more specific resilience path to exercise).
        ``slow`` runs before returning an error so clients still see latency.
        """
        if isinstance(params, str) or params is None:
            effects = parse_chaos(params)
        else:
            effects = parse_chaos_from_params(params)

        if not effects.active:
            return ChaosResult(effects=effects)

        if effects.slow:
            self._sleep(self.slow_seconds)

        if effects.inject_429:
            response = error_response(
                self.vendor,
                ErrorKind.RATE_LIMITED,
                headers={
                    "Retry-After": str(self.retry_after_seconds),
                    "X-RateLimit-Remaining": "0",
                },
            )
            return ChaosResult(effects=effects, response=response)

        if effects.inject_500:
            response = error_response(self.vendor, ErrorKind.SERVER_ERROR)
            return ChaosResult(effects=effects, response=response)

        return ChaosResult(effects=effects)
