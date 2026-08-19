"""
Task 10 — enum drift check.

The 4 canonical state enums (CaseStatus, DecisionState, WriteState,
TriageBand) must eventually match ITR_UI/src/contracts/state.js
exactly. That repo isn't part of this workspace yet, so this test
skips with a clear message instead of failing or silently passing —
once ITR_UI is available, drop it in next to this repo and the check
switches on automatically.
"""

import re
from pathlib import Path

import pytest

from scout.canonical.models import CaseStatus, DecisionState, TriageBand, WriteState

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_JS_PATH = REPO_ROOT / "ITR_UI" / "src" / "contracts" / "state.js"

ENUM_NAME_MAP = {
    "CaseStatus": CaseStatus,
    "DecisionState": DecisionState,
    "WriteState": WriteState,
    "TriageBand": TriageBand,
}


def _extract_js_enum_values(source: str, enum_name: str) -> list[str]:
    """Pull string literal values out of a `const <enum_name> = { ... }` block."""
    block_match = re.search(
        rf"{enum_name}\s*=\s*(?:Object\.freeze\()?\{{(.*?)\}}\)?", source, re.DOTALL
    )
    if not block_match:
        return []
    return re.findall(r"""['"]([a-zA-Z0-9_]+)['"]\s*,?""", block_match.group(1))


def test_enums_match_itr_ui_contracts():
    if not STATE_JS_PATH.exists():
        pytest.skip(
            "ITR_UI/src/contracts/state.js not found in this workspace — "
            "enum drift check skipped, verify manually once available"
        )

    source = STATE_JS_PATH.read_text(encoding="utf-8")

    mismatches = []
    for enum_name, python_enum in ENUM_NAME_MAP.items():
        js_values = set(_extract_js_enum_values(source, enum_name))
        py_values = {member.value for member in python_enum}

        if js_values != py_values:
            mismatches.append(
                f"{enum_name}: python={sorted(py_values)} "
                f"js={sorted(js_values)} "
                f"missing_in_python={sorted(js_values - py_values)} "
                f"missing_in_js={sorted(py_values - js_values)}"
            )

    assert not mismatches, "Enum drift vs ITR_UI/src/contracts/state.js:\n" + "\n".join(
        mismatches
    )
