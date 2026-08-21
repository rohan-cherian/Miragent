import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scout.governance import pii as pii_module
from scout.governance.pii import RedactionError, redact

_PII_MODULE_PATH = Path(__file__).resolve().parent.parent / "scout" / "governance" / "pii.py"


def test_email_masking():
    text = "Please reach out to alice@example.com about the ticket."

    result = redact(text)

    assert result.status == "redacted"
    assert "alice@example.com" not in result.text
    assert "PII_EMAIL_01" in result.text
    assert result.pii_map.get("PII_EMAIL_01") == "alice@example.com"


def test_phone_masking():
    text = "Call me back at 415-555-0132 when you get a chance."

    result = redact(text)

    assert "415-555-0132" not in result.text
    assert result.status == "redacted"


def test_credit_card_masking():
    text = "Card on file: 4111111111111111, please charge it."

    result = redact(text)

    assert "4111111111111111" not in result.text
    assert result.status == "redacted"


def test_placeholder_roundtrip():
    original = (
        "Contact john@example.com and john@example.com. "
        "Also contact jane@example.com."
    )

    result = redact(original)

    assert result.pii_map.get("PII_EMAIL_01") == "john@example.com"
    assert result.pii_map.get("PII_EMAIL_02") == "jane@example.com"
    assert result.text.count("PII_EMAIL_01") == 2
    assert result.text.count("PII_EMAIL_02") == 1

    reconstructed = result.text
    for placeholder, original_value in result.pii_map.items():
        reconstructed = reconstructed.replace(placeholder, original_value)

    assert reconstructed == original


def test_fail_closed_on_forced_failure(monkeypatch):
    monkeypatch.setenv("PRESIDIO_FORCE_FAIL", "true")

    with pytest.raises(RedactionError):
        redact("alice@example.com")


def test_source_never_returns_raw_text():
    source = _PII_MODULE_PATH.read_text(encoding="utf-8")

    assert "return text" not in source, (
        "redact() must never return unredacted content — found a 'return text' "
        "pattern that could bypass masking."
    )


# ══════════════════════════════════════════════════════════════════════════
# Finding 2 — residual sweep (content fix) + boundary-aware check (precision
# fix). Analyzer output is faked directly (a fixed list of detections) so
# these are pure-python and deterministic — no dependency on which entities
# a live spaCy model happens to catch on a given run.
# ══════════════════════════════════════════════════════════════════════════


class _FakeAnalyzer:
    def __init__(self, results):
        self._results = results

    def analyze(self, text, entities, language, **kwargs):
        return self._results


def _fake_engines(monkeypatch, results):
    from presidio_anonymizer import AnonymizerEngine

    monkeypatch.setitem(pii_module._engine_cache, "analyzer", _FakeAnalyzer(results))
    monkeypatch.setitem(pii_module._engine_cache, "anonymizer", AnonymizerEngine())


def _person_result(text: str, value: str, *, nth: int = 0, score: float = 0.85):
    start = text.index(value)
    for _ in range(nth):
        start = text.index(value, start + 1)
    return SimpleNamespace(entity_type="PERSON", start=start, end=start + len(value), score=score)


def test_repeated_person_second_occurrence_undetected_is_swept(monkeypatch):
    """Mode 2: the analyzer only flags the signature occurrence; the
    identical mid-sentence occurrence is left for the residual sweep,
    masked with the SAME placeholder, and the call succeeds — no raise."""
    text = "John Smith called again about the same ticket.\n\nRegards,\nJohn Smith"
    _fake_engines(monkeypatch, [_person_result(text, "John Smith", nth=1)])  # sig only

    result = redact(text)

    assert result.status == "redacted"
    assert result.pii_map == {"PII_PERSON_01": "John Smith"}
    assert result.text.count("PII_PERSON_01") == 2
    assert "John Smith" not in result.text


def test_detected_mark_does_not_falsely_match_inside_marketing(monkeypatch):
    """Mode 1: "Mark" is detected and masked; the innocent "Marketing"
    elsewhere in the text must pass through completely untouched."""
    text = "Hi, this is Mark from support. Loop in our Marketing team."
    _fake_engines(monkeypatch, [_person_result(text, "Mark")])

    result = redact(text)

    assert result.status == "redacted"
    assert "PII_PERSON_01" in result.text
    assert "Marketing" in result.text, "the boundary-aware check must not treat this as a residual"
    assert "Mark from support" not in result.text


def test_overlapping_values_longest_first_no_partial_mangling(monkeypatch):
    """"John Smith" and "John" both appear in pii_map; sweeping "John"
    first would carve into an unswept "John Smith" occurrence. Longest-
    first order must leave "PII_PERSON_01" whole, never
    "PII_PERSON_02 Smith"."""
    text = "John Smith opened the ticket. John will follow up separately."
    results = [
        _person_result(text, "John Smith"),
        _person_result(text, "John", nth=1),  # the standalone "John" later in the text
    ]
    _fake_engines(monkeypatch, results)

    result = redact(text)

    assert result.status == "redacted"
    assert "PII_PERSON_02 Smith" not in result.text
    assert "John Smith" not in result.text
    assert "John" not in result.text.replace("PII_PERSON_01", "").replace("PII_PERSON_02", "")


def test_a_residual_the_sweep_cannot_fix_still_raises(monkeypatch):
    """The gate is never weakened: force the sweep to be a no-op (as if its
    own predicate genuinely couldn't match a residual) and confirm the
    final check still raises rather than silently returning leaked text."""
    text = "John Smith called again.\n\nRegards,\nJohn Smith"
    _fake_engines(monkeypatch, [_person_result(text, "John Smith", nth=1)])  # sig only
    monkeypatch.setattr(pii_module, "_sweep_residual_occurrences", lambda anonymized_text, pii_map: anonymized_text)

    with pytest.raises(RedactionError, match="Post-redaction check failed"):
        redact(text)


# ══════════════════════════════════════════════════════════════════════════
# Follow-up round — the third bug found while diagnosing Finding 2:
# InPanRecognizer's near-zero-confidence noise on arbitrary 10-char words,
# with no score_threshold configured, produces adjacent same-type spans
# that Presidio's own anonymizer merges before the operator callback runs.
# Two fixes: an explicit score_threshold, and allocating a fresh
# placeholder on the fly for a merged value instead of raising.
# ══════════════════════════════════════════════════════════════════════════


class _ThresholdAwareFakeAnalyzer:
    """Unlike _FakeAnalyzer, this one actually applies score_threshold —
    the same filtering contract the real AnalyzerEngine has — so a test
    can verify redact() actually WIRES the threshold through, not just
    that it accepts the parameter without error."""

    def __init__(self, results):
        self._results = results

    def analyze(self, text, entities, language, score_threshold=0.0, **kwargs):
        return [r for r in self._results if r.score >= score_threshold]


def _fake_engines_threshold_aware(monkeypatch, results):
    from presidio_anonymizer import AnonymizerEngine

    monkeypatch.setitem(pii_module._engine_cache, "analyzer", _ThresholdAwareFakeAnalyzer(results))
    monkeypatch.setitem(pii_module._engine_cache, "anonymizer", AnonymizerEngine())


def test_two_adjacent_merged_spans_get_an_allocated_placeholder_not_a_raise(monkeypatch):
    """Presidio's anonymizer merges two adjacent same-type spans (one
    space apart) into a single combined value before calling the
    operator — the exact shape observed with real InPanRecognizer noise
    on scout/gmail/fixtures/0002_19fffd7b5c1f2564.json. The merged value
    must get an allocated placeholder, appear in pii_map, and the call
    must succeed — never raise "no assigned placeholder"."""
    text = "Please check screenshot reference-details for the ticket."
    results = [
        _person_result(text, "screenshot"),
        _person_result(text, "reference-"),
    ]
    _fake_engines(monkeypatch, results)

    result = redact(text)

    assert result.status == "redacted"
    assert "screenshot reference-" in result.pii_map.values()
    merged_placeholder = next(p for p, v in result.pii_map.items() if v == "screenshot reference-")
    assert merged_placeholder in result.text
    assert "screenshot" not in result.text.replace(merged_placeholder, "")
    assert "reference-" not in result.text.replace(merged_placeholder, "")


def test_sub_threshold_detection_leaves_text_untouched(monkeypatch):
    text = "This word triggers only a low-confidence noise detection."
    noisy = SimpleNamespace(
        entity_type="IN_PAN",
        start=text.index("triggers"),
        end=text.index("triggers") + len("triggers"),
        score=0.01,  # well below _SCORE_THRESHOLD
    )
    _fake_engines_threshold_aware(monkeypatch, [noisy])

    result = redact(text)

    assert result.status == "clean"
    assert result.pii_map == {}
    assert result.text == text


def test_message_with_only_sub_threshold_noise_is_clean(monkeypatch):
    text = "screenshot activation reference- database migration"
    noise = [
        SimpleNamespace(entity_type="IN_PAN", start=text.index("screenshot"),
                        end=text.index("screenshot") + len("screenshot"), score=0.01),
        SimpleNamespace(entity_type="IN_PAN", start=text.index("activation"),
                        end=text.index("activation") + len("activation"), score=0.01),
    ]
    _fake_engines_threshold_aware(monkeypatch, noise)

    result = redact(text)

    assert result.status == "clean"
    assert result.pii_map == {}


def test_previously_failing_fixture_messages_now_redact_successfully():
    """End-to-end regression: the two real Gmail fixture messages that
    used to raise "Anonymizer produced a value with no assigned
    placeholder for entity type 'IN_PAN'" must now redact cleanly, with
    the real analyzer/anonymizer engines (no monkeypatching)."""
    from scout.gmail.envelope import extract_bodies

    fixtures_dir = Path(__file__).resolve().parent.parent / "scout" / "gmail" / "fixtures"
    for name in ["0002_19fffd7b5c1f2564.json", "0003_19fffe6693781cab.json"]:
        path = fixtures_dir / name
        if not path.exists():
            pytest.skip(f"{path} not present — skipping fixture regression check")
        doc = json.loads(path.read_text(encoding="utf-8"))
        text_body, _ = extract_bodies(doc.get("payload") or {})

        result = redact(text_body)  # must not raise

        assert result.status == "redacted"
        assert "Priya Sharma" not in result.text
        assert "motiveminds.vihaan@gmail.com" not in result.text
