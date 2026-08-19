"""
Task 17 (part 1) — parent/child chunking.

Pure function, no I/O. Turns one canonical ``itr360.message`` row into a
list of :class:`Chunk` objects:

* **parent** — a paragraph-sized block of surrounding context. It is never
  embedded; it travels alongside the child so a retrieved sentence arrives
  with enough context to be readable in the console and in an LLM prompt.
* **child**  — the unit that actually gets embedded and searched
  (~``CHILD_TARGET_TOKENS`` tokens with ``CHILD_OVERLAP_TOKENS`` overlap,
  aligned to sentence boundaries wherever the text allows it).

Every chunk carries ``start_offset``/``end_offset`` — character positions
into the *original* ``body_redacted`` string, such that::

    body_redacted[chunk.start_offset:chunk.end_offset] == chunk.child_text

holds exactly. That is what lets Task 18 cite "this sentence, from this
message, at these characters" instead of a vague reference, and what
Task 19a's ``evidence_spans`` are expressed in.

REDACTED INPUT ONLY
-------------------
This module must only ever see text that has already been through
``scout.governance.pii.redact()`` — i.e. ``itr360.message.body_redacted``
(Task 12/13), never a raw Gmail body. Redaction is gate one of two
(the trust filter at Task 18 is gate two) and it happens *upstream* of
here, on the way into canonical.

``chunk_message()`` fails closed on obviously-unredacted input by raising
:class:`UnredactedTextError`. That check is a heuristic, not a guarantee —
see :func:`looks_unredacted` for exactly what it can and cannot catch.
Passing ``strict=False`` downgrades it to a no-op for callers that have
their own proof of redaction (e.g. a test fixture).

Layering (Task 4): this module imports nothing from ``scout.gmail``,
``scout.connectors`` or ``googleapiclient``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# ── Size targets ──────────────────────────────────────────────────────────
# Slice-1 spec: "The child is what gets embedded and retrieved (~300 tokens,
# 50-token overlap); the parent is the whole message and is what gets
# displayed." Parents here are paragraph blocks rather than always the whole
# body: for a short email with no blank lines that IS the whole body, and for
# a long thread it keeps the displayed context readable. See
# docs/corpus_datasheet.md.
#
# These are chunking geometry, not pinned model config — unlike EMBED_DIMS
# they can change without a re-embed of anything already indexed being
# *incorrect* (it would just be inconsistent), so they live here as
# overridable defaults rather than in scout.config.
CHILD_TARGET_TOKENS = 300
CHILD_OVERLAP_TOKENS = 50
PARENT_MAX_TOKENS = 1000

# Rough character/token ratio for English prose. Deliberately a constant and
# not tiktoken: Task 17 adds no new NLP/tokeniser dependency (pyproject.toml
# has neither tiktoken nor nltk/spacy-for-sentences available to this layer).
CHARS_PER_TOKEN = 4

CHILD_TARGET_CHARS = CHILD_TARGET_TOKENS * CHARS_PER_TOKEN      # ~1200
CHILD_OVERLAP_CHARS = CHILD_OVERLAP_TOKENS * CHARS_PER_TOKEN    # ~200
PARENT_MAX_CHARS = PARENT_MAX_TOKENS * CHARS_PER_TOKEN          # ~4000

# Paragraph separator: a blank line, optionally containing whitespace.
_PARA_SEP = re.compile(r"\n[ \t]*\n+")

# Sentence terminator followed by whitespace, or a hard line break. Stdlib
# regex only — good enough for email prose, and deliberately conservative
# about abbreviations (see _ABBREVIATIONS).
_SENT_SEP = re.compile(r"(?<=[.!?…])[\"'\)\]”’]*[ \t]*\n+|(?<=[.!?…])[\"'\)\]”’]*[ \t]+|\n+")

_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.",
    "e.g.", "i.e.", "etc.", "vs.", "approx.", "no.", "inc.", "ltd.",
    "co.", "corp.", "dept.", "fig.", "cf.", "al.", "ext.",
}

# A bare email address surviving in text that claims to be body_redacted is
# the single clearest signal that redaction did not run: pii.redact() masks
# EMAIL_ADDRESS unconditionally and replaces it with a PII_EMAIL_NN token.
_BARE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Long digit runs that look like a card/ID number and are not a placeholder.
_LONG_DIGIT_RUN = re.compile(r"(?<!\w)(?:\d[ \-]?){13,19}(?!\w)")

_PLACEHOLDER = re.compile(r"PII_[A-Z_]+_\d{2}")


class UnredactedTextError(ValueError):
    """Raised when chunk_message() is handed text that looks unredacted."""


@dataclass(frozen=True)
class Chunk:
    """One child window plus the parent block it was cut from.

    ``child_text`` is what gets embedded (Task 17 part 2) and retrieved
    (Task 18). ``parent_text`` is what gets displayed. ``start_offset`` /
    ``end_offset`` index into the source ``body_redacted``.
    """

    chunk_id: uuid.UUID
    message_id: Any
    child_text: str
    parent_text: str
    start_offset: int
    end_offset: int

    # Identifiers the index payload and the Task 18 trust filter need.
    # Present on Chunk (rather than bolted on later) because filtering has
    # to happen at query time, not after retrieval.
    case_id: Any = None
    person_id: Any = None
    tenant_id: Any = None
    parent_index: int = 0
    child_index: int = 0
    acl_tags: list[str] = field(default_factory=list)

    @property
    def offsets(self) -> tuple[int, int]:
        return (self.start_offset, self.end_offset)


# ── Input normalisation ───────────────────────────────────────────────────


def _get(message: Any, name: str, default: Any = None) -> Any:
    """Read an attribute from a Message ORM object or a key from a dict."""
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def build_acl_tags(tenant_id: Any, org_id: Any = None) -> list[str]:
    """ACL tags in the Slice-1 shape: ``["tenant:<uuid>", "org:<uuid>"]``.

    Stored on every chunk so Task 18's trust filter can push them into the
    index query as a payload filter. Filtering after retrieval is how
    restricted content ends up in an LLM prompt.
    """
    tags: list[str] = []
    if tenant_id:
        tags.append(f"tenant:{tenant_id}")
    if org_id:
        tags.append(f"org:{org_id}")
    return tags


# ── Redaction contract ────────────────────────────────────────────────────


def looks_unredacted(text: str) -> str | None:
    """Return a reason string if `text` looks like it never went through redact().

    Heuristic, and knowingly incomplete. It catches the two failure modes
    that are both common and unambiguous:

    * a bare email address — pii.redact() masks EMAIL_ADDRESS every time,
      so one surviving here means the text bypassed governance;
    * a 13-19 digit run that is not a PII placeholder — card/ID shaped.

    It cannot catch unredacted names, addresses, or free-text disclosures:
    those are only distinguishable from ordinary prose by the analyser that
    already ran upstream. Enforcement of the wider contract is by
    construction (callers pass ``itr360.message.body_redacted``) and by the
    docstring above — not by this function. Do not read a ``None`` return
    as proof that the text is safe.
    """
    if not text:
        return None

    match = _BARE_EMAIL.search(text)
    if match:
        return f"bare email address at offset {match.start()}"

    for match in _LONG_DIGIT_RUN.finditer(text):
        if _PLACEHOLDER.search(text, max(0, match.start() - 24), match.end() + 24):
            continue
        return f"unmasked {len(re.sub(r'[^0-9]', '', match.group()))}-digit sequence at offset {match.start()}"

    return None


# ── Span helpers (all offsets are into the original text) ─────────────────


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for sep in _PARA_SEP.finditer(text):
        spans.append((pos, sep.start()))
        pos = sep.end()
    spans.append((pos, len(text)))

    out: list[tuple[int, int]] = []
    for start, end in spans:
        start, end = _trim(text, start, end)
        if end > start:
            out.append((start, end))
    return out


def _ends_with_abbreviation(text: str, end: int) -> bool:
    window = text[max(0, end - 12):end].lower()
    token = window.rsplit(" ", 1)[-1].rsplit("\n", 1)[-1]
    return token in _ABBREVIATIONS


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = start
    for sep in _SENT_SEP.finditer(text, start, end):
        cut = sep.start()
        if cut <= pos:
            continue
        if _ends_with_abbreviation(text, cut):
            continue
        s, e = _trim(text, pos, cut)
        if e > s:
            spans.append((s, e))
        pos = sep.end()

    s, e = _trim(text, pos, end)
    if e > s:
        spans.append((s, e))

    return spans or [_trim(text, start, end)]


def _hard_split(start: int, end: int, target: int, overlap: int) -> list[tuple[int, int]]:
    """Fixed-width fallback for a 'sentence' longer than a whole child window."""
    step = max(1, target - overlap)
    out: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        out.append((pos, min(pos + target, end)))
        if pos + target >= end:
            break
        pos += step
    return out


def _child_spans(
    sentences: list[tuple[int, int]],
    target: int,
    overlap: int,
) -> list[tuple[int, int]]:
    """Pack sentence spans into ~`target`-char windows with `overlap` carry-back."""
    spans: list[tuple[int, int]] = []
    count = len(sentences)
    i = 0

    while i < count:
        start, end = sentences[i]
        last = i

        # A single sentence that blows past the window gets split by width.
        if end - start > target * 1.5:
            spans.extend(_hard_split(start, end, target, overlap))
            i += 1
            continue

        while last + 1 < count and (sentences[last + 1][1] - start) <= target:
            last += 1
            end = sentences[last][1]

        spans.append((start, end))

        if last + 1 >= count:
            break

        # Next window starts far enough back to carry `overlap` characters.
        back_from = end - overlap
        nxt = last + 1
        while nxt > i + 1 and sentences[nxt - 1][0] >= back_from:
            nxt -= 1
        i = max(nxt, i + 1)

    # Drop exact duplicates while preserving order.
    seen: set[tuple[int, int]] = set()
    unique: list[tuple[int, int]] = []
    for span in spans:
        if span in seen:
            continue
        seen.add(span)
        unique.append(span)
    return unique


# ── Public API ────────────────────────────────────────────────────────────


def chunk_message(
    message: dict | Any,
    *,
    org_id: Any = None,
    child_target_chars: int = CHILD_TARGET_CHARS,
    child_overlap_chars: int = CHILD_OVERLAP_CHARS,
    parent_max_chars: int = PARENT_MAX_CHARS,
    strict: bool = True,
) -> list[Chunk]:
    """Split one canonical message into parent/child chunks.

    Args:
        message: an ``itr360.message`` row — either a
            :class:`scout.canonical.models.Message` instance or a dict with
            the same field names. Only ``body_redacted`` is read for text;
            ``id``, ``case_id``, ``person_id`` and ``tenant_id`` are carried
            onto every chunk.
        org_id: the owning org (``itr360.case_.org_id``), used to build the
            ``org:`` ACL tag. Not on the message row itself, so the caller
            passes it.
        strict: when True (default) raise :class:`UnredactedTextError` if
            the body looks unredacted. See :func:`looks_unredacted` for the
            limits of that check.

    Returns:
        A list of :class:`Chunk`, in document order. Empty if the body is
        empty or whitespace-only.

    Raises:
        UnredactedTextError: strict mode, and the body trips the heuristic.
        TypeError: ``body_redacted`` is not a string.

    Contract: the input must already be redacted (Task 12/13). This function
    performs no I/O and no redaction of its own.
    """
    if isinstance(message, str):
        raise TypeError(
            "chunk_message() takes a canonical message row (Message or dict), "
            "not a bare string — the message_id and identifiers are required "
            "for citation back to source."
        )

    body = _get(message, "body_redacted")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise TypeError(f"body_redacted must be a str, got {type(body).__name__!r}.")

    if strict:
        reason = looks_unredacted(body)
        if reason is not None:
            raise UnredactedTextError(
                "chunk_message() received text that looks unredacted "
                f"({reason}). This function accepts itr360.message.body_redacted "
                "only — redaction happens upstream (Task 12/13) and must never "
                "be skipped on the way into the index."
            )

    if not body.strip():
        return []

    message_id = _get(message, "id")
    if message_id is None:
        message_id = _get(message, "message_id")
    case_id = _get(message, "case_id")
    person_id = _get(message, "person_id")
    tenant_id = _get(message, "tenant_id")
    acl_tags = build_acl_tags(tenant_id, org_id)

    chunks: list[Chunk] = []
    parent_index = 0

    for p_start, p_end in _paragraph_spans(body):
        # Oversized paragraph: cut it into several parents at sentence
        # boundaries so a displayed parent stays readable.
        parent_blocks: list[tuple[int, int]]
        if p_end - p_start > parent_max_chars:
            parent_blocks = _child_spans(
                _sentence_spans(body, p_start, p_end),
                target=parent_max_chars,
                overlap=0,
            )
        else:
            parent_blocks = [(p_start, p_end)]

        for block_start, block_end in parent_blocks:
            parent_text = body[block_start:block_end]
            sentences = _sentence_spans(body, block_start, block_end)
            child_index = 0
            for c_start, c_end in _child_spans(
                sentences, target=child_target_chars, overlap=child_overlap_chars
            ):
                c_start, c_end = _trim(body, c_start, c_end)
                if c_end <= c_start:
                    continue
                chunks.append(
                    Chunk(
                        chunk_id=uuid.uuid4(),
                        message_id=message_id,
                        child_text=body[c_start:c_end],
                        parent_text=parent_text,
                        start_offset=c_start,
                        end_offset=c_end,
                        case_id=case_id,
                        person_id=person_id,
                        tenant_id=tenant_id,
                        parent_index=parent_index,
                        child_index=child_index,
                        acl_tags=list(acl_tags),
                    )
                )
                child_index += 1
            parent_index += 1

    return chunks
