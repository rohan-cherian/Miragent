"""
itr/scout/gmail/executor.py — Gmail write-back (Task 21).

**This module contains the only function in the entire codebase permitted to
send email.** Boring on purpose: the component that touches the outside world
should be the one you can read in a single sitting and fully understand.

Two things it refuses to do:

* Send without an approval. ``send_reply`` re-reads the approval row and
  compares ``payload_hash`` against the text it was handed. A hash passed in by
  the caller only proves someone built an object; re-reading proves the
  approval still exists and still covers this exact text. Mismatch or missing
  row raises ``ApprovalRequired`` before any network call.

* Send outside a thread. Gmail needs BOTH ``threadId`` in the request body and
  the ``In-Reply-To`` / ``References`` headers on the MIME message. Set only
  one and the reply opens a new conversation in the recipient's inbox — the
  visible failure everyone notices.

Built in Slice 1 but not fired: Task 22's dispatch gates on ACTION_MODE, which
defaults to ``draft_only``.
"""

from __future__ import annotations

import base64
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import httpx

from scout.config import settings
from scout.connectors.base import ApprovedAction, SendResult

logger = logging.getLogger(__name__)

__all__ = ["send_reply", "ApprovalRequired", "SendResult", "GmailSendError"]

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

_RATE_LIMIT_STATUS = {429, 403}
_MAX_ATTEMPTS = 4
_BASE_DELAY_SECONDS = 1.0


class ApprovalRequired(Exception):
    """Raised when a send is attempted without a valid, matching approval.

    Typed deliberately: callers must be able to distinguish "refused because
    unapproved" from "Gmail was down", because only one of those is a bug.
    """


class GmailSendError(RuntimeError):
    """Gmail rejected the send."""


@dataclass(frozen=True)
class _Approval:
    approval_id: str
    case_id: str
    payload_hash: str
    state: str


# ── approval verification ────────────────────────────────────────────────────


def _load_approval(approval_id: str, case_id: str | None) -> _Approval | None:
    """Read the approval row. Returns None when there is no usable approval.

    Imported lazily so this module stays importable — and unit-testable —
    without SQLAlchemy or a live database.
    """
    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from scout.canonical.models import RecommendationDecision
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ApprovalRequired(
            f"cannot verify approval (canonical layer unavailable: {exc})"
        ) from exc

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with Session(engine) as session:
        row = session.scalar(
            select(RecommendationDecision).where(RecommendationDecision.id == approval_id)
        )
        if row is None:
            return None
        return _Approval(
            approval_id=str(row.id),
            case_id=str(row.case_id),
            payload_hash=row.payload_hash or "",
            state=str(row.state or ""),
        )


_APPROVED_STATES = {"approved", "edited_approved"}


def _require_approval(approval_id: Any, case_id: Any, payload_hash: str) -> _Approval:
    """Refuse unless a matching approval exists. Never returns on failure."""
    if not approval_id:
        raise ApprovalRequired("no approval_id supplied — refusing to send")

    approval = _load_approval(str(approval_id), str(case_id) if case_id else None)
    if approval is None:
        raise ApprovalRequired(f"no approval record for {approval_id}")

    if approval.state not in _APPROVED_STATES:
        raise ApprovalRequired(
            f"approval {approval_id} is in state {approval.state!r}, "
            f"not one of {sorted(_APPROVED_STATES)}"
        )

    # The hash is the whole point: it ties this send to the exact text a human
    # signed off. Text edited after approval must not go out under it.
    if not payload_hash or approval.payload_hash != payload_hash:
        raise ApprovalRequired(
            f"payload hash does not match approval {approval_id} — "
            "the text changed after it was approved"
        )
    return approval


# ── message construction ─────────────────────────────────────────────────────


def _reply_subject(subject: str | None) -> str:
    """Prefix ``Re:`` unless the subject already carries one."""
    text = (subject or "").strip()
    if not text:
        return "Re:"
    return text if text.lower().startswith("re:") else f"Re: {text}"


def build_reply_message(
    *,
    to_address: str,
    from_address: str,
    subject: str | None,
    body_text: str,
    in_reply_to_message_id: str | None,
) -> EmailMessage:
    """Build the MIME reply. Pure — no network, no database.

    Both ``In-Reply-To`` and ``References`` are set from the same id. Gmail
    threads on References; other clients thread on In-Reply-To. Setting one
    only works until someone reads the mail somewhere else.
    """
    msg = EmailMessage()
    msg["To"] = to_address
    msg["From"] = from_address
    msg["Subject"] = _reply_subject(subject)
    if in_reply_to_message_id:
        rfc_id = in_reply_to_message_id
        if not rfc_id.startswith("<"):
            rfc_id = f"<{rfc_id}>"
        msg["In-Reply-To"] = rfc_id
        msg["References"] = rfc_id
    msg.set_content(body_text or "")
    return msg


def _access_token() -> str:
    """A fresh access token. The stored one is routinely expired."""
    from scout.gmail.auth import GmailTokenStore, refresh_access_token

    store = GmailTokenStore(settings.gmail_token_path)
    tokens = store.load()
    if tokens is None:
        raise GmailSendError(f"no Gmail token at {settings.gmail_token_path}")
    refresh_token = getattr(tokens, "refresh_token", None) or settings.gmail_refresh_token
    if not refresh_token:
        raise GmailSendError("no refresh token available")
    fresh = refresh_access_token(
        refresh_token=refresh_token,
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
    )
    store.save(fresh)
    return fresh.access_token


def _post_send(payload: dict[str, Any], token: str) -> dict[str, Any]:
    """POST to Gmail, retrying rate limits with exponential backoff + jitter."""
    delay = _BASE_DELAY_SECONDS
    last: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                SEND_URL, headers={"Authorization": f"Bearer {token}"}, json=payload
            )
        if res.status_code < 400:
            return res.json()
        if res.status_code in _RATE_LIMIT_STATUS and attempt < _MAX_ATTEMPTS:
            # Jitter matters more than the backoff: without it every throttled
            # sender retries in lockstep and hits the quota again together.
            sleep_for = delay + random.uniform(0, delay / 2)
            logger.warning(
                "Gmail send rate-limited (%s), attempt %d/%d, sleeping %.1fs",
                res.status_code,
                attempt,
                _MAX_ATTEMPTS,
                sleep_for,
            )
            time.sleep(sleep_for)
            delay *= 2
            continue
        last = GmailSendError(f"Gmail send failed ({res.status_code}): {res.text[:300]}")
        break
    raise last or GmailSendError("Gmail send failed")


# ── the one permitted send ───────────────────────────────────────────────────


def send_reply(
    *,
    approval_id: Any,
    case_id: Any,
    to_address: str,
    subject: str | None,
    body_text: str,
    thread_external_id: str | None,
    in_reply_to_message_id: str | None,
    payload_hash: str,
    from_address: str | None = None,
) -> SendResult:
    """Send an approved reply, inside its original Gmail thread.

    Raises ``ApprovalRequired`` before any network call when the approval is
    missing, not approved, or does not cover this exact text.
    """
    _require_approval(approval_id, case_id, payload_hash)

    sender = from_address or settings.gmail_user
    if not sender or sender == "me":
        sender = ""  # Gmail fills From from the authenticated account

    msg = build_reply_message(
        to_address=to_address,
        from_address=sender,
        subject=subject,
        body_text=body_text,
        in_reply_to_message_id=in_reply_to_message_id,
    )
    payload: dict[str, Any] = {
        "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    }
    # threadId AND the headers above. Either alone breaks threading.
    if thread_external_id:
        payload["threadId"] = thread_external_id

    logger.info(
        "Sending approved reply (approval=%s case=%s thread=%s)",
        approval_id,
        case_id,
        thread_external_id,
    )
    data = _post_send(payload, _access_token())
    return SendResult(
        message_id=str(data.get("id") or ""),
        thread_id=str(data.get("threadId") or thread_external_id or ""),
        sent_at=datetime.now(timezone.utc),
    )


def execute(action: ApprovedAction, **kwargs: Any) -> Any:
    """``ActionExecutor.execute`` — approval is carried by the argument type."""
    result = send_reply(
        approval_id=action.approval_id,
        case_id=action.case_id,
        payload_hash=action.payload_hash,
        **kwargs,
    )
    return result.as_action_result()
