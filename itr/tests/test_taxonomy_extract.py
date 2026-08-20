"""
Task 0, Part 5 — extractor correctness.

No DB needed — pure file test, always runs. Runs the extractor against the
committed workbook (data/ITR_SyntheticData_GenerationClasses_v1_30July2026.xlsx)
and checks the output against facts verified by direct workbook inspection
(see the Task 0 prompt): exactly 10 categories, 100 classes, 10 per
category, and the CFG-09 demo class's verbatim fields.
"""

from __future__ import annotations

import json

import pytest

from scripts.extract_taxonomy import (
    EXPECTED_CATEGORY_COUNT,
    EXPECTED_CLASS_COUNT,
    PHRASES_PATH,
    WORKBOOK_PATH,
    _extract_categories,
    _extract_classes,
    _load_phrases,
)
from scripts.seed_taxonomy import _PRIORITY_MAP


def _skip_if_workbook_missing() -> None:
    if not WORKBOOK_PATH.exists():
        pytest.skip(f"{WORKBOOK_PATH} not committed — skipping extractor tests")


@pytest.fixture(scope="module")
def workbook():
    _skip_if_workbook_missing()
    import openpyxl

    return openpyxl.load_workbook(WORKBOOK_PATH, data_only=True)


@pytest.fixture(scope="module")
def categories(workbook):
    return _extract_categories(workbook)


@pytest.fixture(scope="module")
def classes(workbook):
    phrases = _load_phrases()
    return _extract_classes(workbook, phrases)


def test_exactly_ten_categories(categories):
    assert len(categories) == EXPECTED_CATEGORY_COUNT == 10


def test_exactly_one_hundred_classes(classes):
    assert len(classes) == EXPECTED_CLASS_COUNT == 100


def test_ten_classes_per_category(classes):
    per_category: dict[str, int] = {}
    for entry in classes:
        per_category[entry["category"]] = per_category.get(entry["category"], 0) + 1
    assert len(per_category) == 10
    assert set(per_category.values()) == {10}


def test_every_class_prefix_is_a_known_category_code(categories, classes):
    known_codes = {c["code"] for c in categories}
    assert len(known_codes) == 10
    for entry in classes:
        assert entry["category"] in known_codes, f"{entry['class_id']} has an unrecognised prefix"


def test_cfg_09_verbatim_fields(classes):
    cfg09 = next(c for c in classes if c["class_id"] == "CFG-09")
    assert cfg09["name"] == "Feature flag / entitlement not enabled"
    assert cfg09["kb_article_exists"] is True
    assert cfg09["category"] == "CFG"
    assert cfg09["default_priority"] == "high"
    assert cfg09["example_phrases"], "CFG-09 must have hand-written example phrases"


def test_priority_values_are_within_the_expected_workbook_set(classes):
    seen = {entry["default_priority"] for entry in classes if entry["default_priority"]}
    assert seen <= {"low", "normal", "high", "urgent"}


def test_seed_time_priority_map_covers_every_workbook_priority(classes):
    seen = {entry["default_priority"] for entry in classes if entry["default_priority"]}
    assert seen <= set(_PRIORITY_MAP)
    # and the map itself only ever produces triage's own ladder
    assert set(_PRIORITY_MAP.values()) == {"low", "medium", "high", "critical"}


def test_phrases_overlay_file_is_the_only_phrase_source(classes):
    """Re-running extraction must never destroy hand-written phrases — the
    overlay file is read fresh and merged in, nothing is invented here."""
    _skip_if_workbook_missing()
    overlay = json.loads(PHRASES_PATH.read_text(encoding="utf-8"))
    with_phrases = {entry["class_id"] for entry in classes if entry["example_phrases"]}
    assert with_phrases == set(overlay), "extracted phrases must match the overlay file exactly"
