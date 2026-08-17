from pathlib import Path

import pytest

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
