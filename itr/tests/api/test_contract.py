"""
Contract conformance — the served API vs openapi/console-api-v1.yaml (Task 24).

The contract was frozen at Task 2 precisely so the console could be built
against it before the API existed. That only holds if something keeps checking
that the API still serves what the yaml promises.

test_app_smoke.py already covers contract-SHAPED behaviour — trace headers,
409/422 bodies, the app's own schema generating. What it cannot catch is drift:
a path quietly unimplemented, a method dropped, a POST that stopped requiring
Idempotency-Key. This module is the diff.

Failures here mean one of two things, and the message says which:
  * the API drifted from the contract  -> fix the API
  * the contract changed              -> that is a Task 2 decision, not a
                                          silent edit, and the console team
                                          needs telling
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scout.api.app import app

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "openapi" / "console-api-v1.yaml"


@pytest.fixture(scope="module")
def contract() -> dict:
    if not CONTRACT_PATH.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"contract not found at {CONTRACT_PATH}")
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def served() -> dict:
    return app.openapi()


def _base_path(contract: dict) -> str:
    """The contract carries /api/v1 in servers, not in each path."""
    servers = contract.get("servers") or []
    for server in servers:
        url = (server.get("url") or "").rstrip("/")
        if url:
            return url
    return ""


def _contract_operations(contract: dict) -> set[tuple[str, str]]:
    base = _base_path(contract)
    ops = set()
    for path, methods in contract["paths"].items():
        for method in methods:
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                ops.add((method.lower(), f"{base}{path}"))
    return ops


def _served_operations(served: dict) -> set[tuple[str, str]]:
    return {
        (method.lower(), path)
        for path, methods in served["paths"].items()
        for method in methods
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }


# -- the surface ------------------------------------------------------------


def test_every_contract_path_is_served(contract, served):
    """A path in the yaml the API does not serve is a broken promise."""
    missing = sorted(_contract_operations(contract) - _served_operations(served))
    assert not missing, (
        "the API does not serve these contract operations: "
        + ", ".join(f"{m.upper()} {p}" for m, p in missing)
    )


def test_no_undeclared_operations_under_the_contract_base(contract, served):
    """Anything under /api/v1 that the contract does not declare is drift.

    Ops endpoints are fine — they just have to live outside the contract's
    base path, which is why /health is mounted at the root.
    """
    base = _base_path(contract)
    extra = sorted(
        (m, p) for m, p in _served_operations(served) - _contract_operations(contract)
        if p.startswith(base)
    )
    assert not extra, (
        "these operations are served under the contract base but are not in the "
        "contract: " + ", ".join(f"{m.upper()} {p}" for m, p in extra)
    )


# -- POST requirements the contract states for every write ------------------


def _resolve(contract: dict, node):
    """Follow a $ref inside the contract document."""
    while isinstance(node, dict) and "$ref" in node:
        target = contract
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node


def _contract_posts(contract: dict) -> list[tuple[str, dict]]:
    return [
        (path, ops["post"])
        for path, ops in contract["paths"].items()
        if "post" in ops
    ]


def test_contract_declares_posts(contract):
    """Guard the guard: if this hits zero, the checks below prove nothing."""
    assert _contract_posts(contract), "contract declares no POST operations"


@pytest.mark.parametrize("header", ["Idempotency-Key", "If-Match"])
def test_every_post_requires_the_concurrency_headers(contract, header):
    offenders = []
    for path, op in _contract_posts(contract):
        names = {
            _resolve(contract, p).get("name")
            for p in op.get("parameters", [])
        }
        if header not in names:
            offenders.append(path)
    assert not offenders, f"POST without {header}: {offenders}"


def test_every_post_returns_a_trace_id_header(contract):
    offenders = []
    for path, op in _contract_posts(contract):
        responses = op.get("responses", {})
        has_trace = any(
            "X-Trace-Id" in (_resolve(contract, r).get("headers") or {})
            for r in responses.values()
        )
        if not has_trace:
            offenders.append(path)
    assert not offenders, f"POST without an X-Trace-Id response header: {offenders}"


@pytest.mark.parametrize(
    "code,fields",
    [("409", {"error", "by", "at"}), ("422", {"field", "min"})],
)
def test_every_post_declares_the_error_bodies(contract, code, fields):
    offenders = []
    for path, op in _contract_posts(contract):
        response = op.get("responses", {}).get(code)
        if response is None:
            offenders.append(f"{path} (no {code})")
            continue
        schema = _resolve(contract, response).get("content", {}).get(
            "application/json", {}
        ).get("schema", {})
        props = set(_resolve(contract, schema).get("properties", {}))
        if props != fields:
            offenders.append(f"{path} ({code} body is {sorted(props)})")
    assert not offenders, f"{code} body does not match the contract: {offenders}"


# -- the enums the console switches on --------------------------------------


@pytest.mark.parametrize(
    "name,values",
    [
        ("CaseStatus", ["new", "open", "pending", "hold", "solved", "closed"]),
        (
            "DecisionState",
            [
                "draft_pending", "in_review", "approved", "edited_approved",
                "rejected", "redrafted", "superseded",
            ],
        ),
        (
            "WriteState",
            ["not_started", "queued", "executing", "retrying", "succeeded", "failed"],
        ),
    ],
)
def test_state_enums_are_exact(contract, name, values):
    """Copied verbatim from the doc. The console renders on these strings, so
    an added or reordered variant is a UI break, not a detail."""
    schema = contract["components"]["schemas"].get(name)
    assert schema is not None, f"{name} missing from components.schemas"
    assert schema.get("enum") == values, f"{name} enum drifted: {schema.get('enum')}"


def test_citation_dto_is_exact(contract):
    citation = contract["components"]["schemas"].get("Citation")
    assert citation is not None, "Citation missing from components.schemas"
    props = citation.get("properties", {})
    for field in (
        "source_system", "source_type", "object_id", "excerpt",
        "source_ts", "deep_link", "access_status",
    ):
        assert field in props, f"Citation.{field} missing"
    assert props["source_type"].get("enum") == [
        "ticket", "comment", "article", "resolution", "graph_path"
    ]
    assert props["access_status"].get("enum") == ["ok", "restricted", "missing"]
