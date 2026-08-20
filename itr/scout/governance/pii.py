"""
Task 12 — PII redaction (governance), fail-closed.

Wraps Presidio's AnalyzerEngine and AnonymizerEngine behind a single
redact() entry point. Every internal failure — engine setup, analysis,
anonymization, or unexpected input — becomes a RedactionError. No code
path here is permitted to hand back the caller's raw, unredacted input
when something goes wrong.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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

# Minimum confidence AnalyzerEngine.analyze() will report a detection at.
# Without this, InPanRecognizer's ~0.01-confidence noise on almost any
# 10-character word ("screenshot", "activation", ...) counts as a
# "detection" — degrading real text and, when two such spans land
# adjacent to each other, triggering Presidio's own anonymizer-side span
# merge (see _make_mask below). 0.4 is comfortably below every genuine
# recognizer's real-match confidence observed in this codebase: pattern
# recognizers (EMAIL/PHONE/CREDIT_CARD/...) score ~0.85-1.0 on a real
# match, spaCy NER (PERSON/LOCATION) scores ~0.85. This is noise
# suppression, not gate weakening — a sub-threshold "detection" was never
# PII, and the boundary-aware post-redaction check still runs on
# everything that IS detected.
_SCORE_THRESHOLD = 0.4

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


def _is_alphabetic_value(value: str) -> bool:
    """True for values made only of letters/spaces (names, locations) —
    these get word-boundary matching so a detected "Mark" doesn't falsely
    match inside "Marketing" (Finding 2, Mode 1). Structured values
    (emails, phone numbers, credit cards, IBANs, SSNs, Aadhaar, PAN) always
    contain a digit or a symbol and get an exact substring match instead —
    a word-boundary has no clean meaning around punctuation like "@" or "-".
    """
    return bool(value) and all(ch.isalpha() or ch.isspace() for ch in value)


def _find_occurrences(text: str, value: str) -> list[tuple[int, int]]:
    """Every occurrence of `value` in `text` that counts as a real match —
    word-boundary for alphabetic values, exact substring for structured
    ones. Shared by the residual sweep and the final check (Finding 2):
    whatever this predicate can find, the sweep already replaced, so
    anything the final check still finds afterward is a genuine anomaly,
    never a "Mark"-inside-"Marketing" false positive.
    """
    if not value:
        return []
    if _is_alphabetic_value(value):
        pattern = r"\b" + re.escape(value) + r"\b"
    else:
        pattern = re.escape(value)
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def _sweep_residual_occurrences(anonymized_text: str, pii_map: dict[str, str]) -> str:
    """Mask any occurrence of a known original PII value that Presidio's
    anonymizer didn't itself mask (Finding 2, Mode 2 — regex recognizers
    catch every occurrence, NER recognizers do not).

    Processed LONGEST VALUE FIRST so "John Smith" is swept before "John" —
    otherwise sweeping "John" first could carve into an unswept
    "John Smith" occurrence and leave "PII_PERSON_01 Smith" behind instead
    of masking the whole name with its own placeholder.
    """
    swept = anonymized_text
    for placeholder, original_value in sorted(
        pii_map.items(), key=lambda item: len(item[1] or ""), reverse=True
    ):
        if not original_value:
            continue
        if _is_alphabetic_value(original_value):
            pattern = re.compile(r"\b" + re.escape(original_value) + r"\b")
        else:
            pattern = re.compile(re.escape(original_value))
        swept = pattern.sub(placeholder, swept)
    return swept


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
            score_threshold=_SCORE_THRESHOLD,
        )

        if not results:
            return RedactionResult(text=text, pii_map={}, status="clean")

        ordered_results = sorted(results, key=lambda r: (r.start, r.end))

        placeholder_by_key: dict[tuple[str, str], str] = {}
        counters: dict[str, int] = {}
        pii_map: dict[str, str] = {}

        def _allocate_placeholder(entity_type: str, original_value: str) -> str:
            counters[entity_type] = counters.get(entity_type, 0) + 1
            label = _PLACEHOLDER_LABELS.get(entity_type, entity_type)
            placeholder = f"PII_{label}_{counters[entity_type]:02d}"
            placeholder_by_key[(entity_type, original_value)] = placeholder
            pii_map[placeholder] = original_value
            return placeholder

        for result in ordered_results:
            original_value = text[result.start : result.end]
            key = (result.entity_type, original_value)
            if key not in placeholder_by_key:
                _allocate_placeholder(result.entity_type, original_value)

        def _make_mask(entity_type: str):
            def _mask(original_value: str) -> str:
                key = (entity_type, original_value)
                if key not in placeholder_by_key:
                    # Presidio's own anonymizer merged two adjacent
                    # same-type spans (e.g. two low-confidence detections
                    # one space apart) into one combined value before
                    # calling this operator — a value our per-result loop
                    # above never saw. Allocate a fresh placeholder for it
                    # NOW rather than refusing to mask: masking MORE than
                    # expected is always safe, refusing is the only unsafe
                    # direction, and the boundary-aware post-redaction
                    # check below remains the real gate either way.
                    logger.warning(
                        "pii.redact: anonymizer merged spans for entity_type=%r "
                        "into an unrecognised value %r — allocating a placeholder "
                        "on the fly.", entity_type, original_value,
                    )
                    return _allocate_placeholder(entity_type, original_value)
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

        # Finding 2 fix, step 1 (content): mask any occurrence Presidio's
        # own anonymizer missed — NER recognizers (PERSON, LOCATION) do not
        # guarantee every repeat occurrence is detected, unlike the regex
        # recognizers. This is a real content fix, not a relaxation of the
        # check below: it makes MORE text actually redacted, never less.
        swept_text = _sweep_residual_occurrences(anonymized.text, pii_map)

        # Finding 2 fix, step 2 (precision) — defense in depth: if a
        # known original PII value is still findable after the sweep,
        # refuse to hand back output that contains it. Boundary-aware
        # (word-boundary for alphabetic values, exact substring for
        # structured ones) so a detected "Mark" no longer falsely matches
        # inside "Marketing" — the SAME predicate the sweep just used, so
        # anything still found here is a genuine anomaly the sweep
        # couldn't fix, never a substring false positive. The gate itself
        # is unchanged: still fail-closed, still raises, still last.
        for original_value in pii_map.values():
            if _find_occurrences(swept_text, original_value):
                raise RedactionError(
                    "Post-redaction check failed: an original PII value is still "
                    "present in the masked output."
                )

        return RedactionResult(text=swept_text, pii_map=pii_map, status="redacted")

    except RedactionError:
        raise
    except Exception as exc:
        raise RedactionError(f"PII redaction failed: {exc}") from exc


def redact_and_audit(text: str, source: str, case_id=None) -> RedactionResult:
    """redact(), plus one itr360.decision_audit row — closing the audit gap
    where governance gate one was invisible to the audit trail.

    Purely additive: calls the existing redact() unchanged, then records the
    outcome. Callers that don't need audit visibility keep calling redact()
    directly; nothing about redact()'s behaviour, signature or fail-closed
    guarantee changes.

    case_id is EXPECTED to be None at most call sites: redaction runs on the
    way into canonical, BEFORE case correlation exists, so there is no case
    to attribute yet. That is the same accepted pattern identity-resolution
    audit rows already have — the row stays discoverable by source and
    timestamp, and the later case_retrolinked event (identity/queue.py)
    bridges the case's own timeline back to this period.

    On RedactionError: a redact_failed audit row is attempted BEFORE the
    original exception is re-raised unchanged. The audit attempt is wrapped
    in its own guard (the trust.py pattern) — an audit-backend failure can
    only produce a warning, never swallow or replace the RedactionError,
    and never stop it propagating.
    """
    import logging

    from scout.governance import audit

    logger = logging.getLogger(__name__)

    def _write_row(action: str, outputs: dict) -> None:
        try:
            audit.write(
                actor="system",
                action=action,
                category="redaction",
                case_id=case_id,
                outputs=outputs,
            )
        except Exception as exc:  # noqa: BLE001 — logging failure must not cascade
            logger.warning(
                "redact_and_audit: audit row (%s) could not be written for "
                "source=%s (%s: %s) — redaction outcome unaffected.",
                action, source, type(exc).__name__, exc,
            )

    try:
        result = redact(text)
    except RedactionError as exc:
        _write_row("redact_failed", {"source": source, "error": str(exc)})
        raise  # the ORIGINAL RedactionError, unchanged

    _write_row(
        "redact",
        {"source": source, "status": result.status, "pii_count": len(result.pii_map)},
    )
    return result
