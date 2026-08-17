"""
Task 12 — PII redaction (governance), fail-closed.

Wraps Presidio's AnalyzerEngine and AnonymizerEngine behind a single
redact() entry point. Every internal failure — engine setup, analysis,
anonymization, or unexpected input — becomes a RedactionError. No code
path here is permitted to hand back the caller's raw, unredacted input
when something goes wrong.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class RedactionError(Exception):
    """Raised whenever redact() cannot guarantee the input has been safely masked."""


@dataclass
class RedactionResult:
    text: str
    pii_map: dict[str, str]
    status: str  # "redacted" | "clean"


_SUPPORTED_ENTITIES: tuple[str, ...] = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "IN_AADHAAR",
    "IN_PAN",
    "LOCATION",
    "PERSON",
)

# Short labels used inside placeholders (PII_<LABEL>_NN), e.g. EMAIL_ADDRESS
# -> EMAIL so placeholders read as PII_EMAIL_01 rather than the longer raw
# Presidio entity type name.
_PLACEHOLDER_LABELS: dict[str, str] = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CREDIT_CARD": "CREDIT_CARD",
    "IBAN_CODE": "IBAN",
    "US_SSN": "SSN",
    "IN_AADHAAR": "AADHAAR",
    "IN_PAN": "PAN",
    "LOCATION": "LOCATION",
    "PERSON": "PERSON",
}

_engine_cache: dict = {}


def _force_fail_enabled() -> bool:
    value = os.environ.get("PRESIDIO_FORCE_FAIL", "")
    return value.strip().lower() in ("true", "1")


def _get_engines():
    if "analyzer" not in _engine_cache:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.predefined_recognizers import (
            InAadhaarRecognizer,
            InPanRecognizer,
        )
        from presidio_anonymizer import AnonymizerEngine

        # IN_AADHAAR / IN_PAN exist as recognizer classes but are not part
        # of AnalyzerEngine()'s default registry — register them explicitly
        # so the required entity list is actually detectable.
        analyzer = AnalyzerEngine()
        analyzer.registry.add_recognizer(InAadhaarRecognizer())
        analyzer.registry.add_recognizer(InPanRecognizer())

        _engine_cache["analyzer"] = analyzer
        _engine_cache["anonymizer"] = AnonymizerEngine()

    return _engine_cache["analyzer"], _engine_cache["anonymizer"]


def redact(text: str) -> RedactionResult:
    """Mask PII in `text`, or raise RedactionError. Fails closed on any error."""
    if _force_fail_enabled():
        raise RedactionError("PRESIDIO_FORCE_FAIL is set — failing closed before analysis.")

    if not isinstance(text, str):
        raise RedactionError(f"redact() requires a str, got {type(text).__name__!r}.")

    try:
        from presidio_anonymizer.entities import OperatorConfig

        analyzer, anonymizer = _get_engines()

        results = analyzer.analyze(
            text=text,
            entities=list(_SUPPORTED_ENTITIES),
            language="en",
        )

        if not results:
            return RedactionResult(text=text, pii_map={}, status="clean")

        ordered_results = sorted(results, key=lambda r: (r.start, r.end))

        placeholder_by_key: dict[tuple[str, str], str] = {}
        counters: dict[str, int] = {}
        pii_map: dict[str, str] = {}

        for result in ordered_results:
            original_value = text[result.start : result.end]
            key = (result.entity_type, original_value)
            if key not in placeholder_by_key:
                counters[result.entity_type] = counters.get(result.entity_type, 0) + 1
                label = _PLACEHOLDER_LABELS.get(result.entity_type, result.entity_type)
                placeholder = f"PII_{label}_{counters[result.entity_type]:02d}"
                placeholder_by_key[key] = placeholder
                pii_map[placeholder] = original_value

        def _make_mask(entity_type: str):
            def _mask(original_value: str) -> str:
                key = (entity_type, original_value)
                if key not in placeholder_by_key:
                    raise RedactionError(
                        "Anonymizer produced a value with no assigned placeholder "
                        f"for entity type {entity_type!r}."
                    )
                return placeholder_by_key[key]

            return _mask

        operators = {
            entity_type: OperatorConfig("custom", {"lambda": _make_mask(entity_type)})
            for entity_type in {result.entity_type for result in ordered_results}
        }

        anonymized = anonymizer.anonymize(
            text=text,
            analyzer_results=ordered_results,
            operators=operators,
        )

        # Defense in depth: if Presidio's own overlap-resolution ever drops
        # a detected span before masking it, refuse to hand back output
        # that still contains a known original PII value.
        for original_value in pii_map.values():
            if original_value and original_value in anonymized.text:
                raise RedactionError(
                    "Post-redaction check failed: an original PII value is still "
                    "present in the masked output."
                )

        return RedactionResult(text=anonymized.text, pii_map=pii_map, status="redacted")

    except RedactionError:
        raise
    except Exception as exc:
        raise RedactionError(f"PII redaction failed: {exc}") from exc
