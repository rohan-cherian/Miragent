"""
itr/scout/connectors/gmail.py — GmailAdapter (Task 21).

Implements all four connector protocols from ``scout.connectors.base``:

  MetadataReader   scan()                      -> MetadataInventory
  DataReader       backfill() / fetch()        -> raw Gmail records
  EventListener    verify() / to_events()      -> NotImplementedError in Slice 1
  ActionExecutor   execute(ApprovedAction)     -> ActionResult

EventListener raises rather than returning empty. Gmail has no plain webhook —
real push is ``users.watch`` -> Pub/Sub -> HTTPS POST, and a watch expires after
seven days, so Slice 1 polls. A stub that quietly returned ``[]`` would look
like "no events" forever; raising says "not built" out loud.

Sending goes through ``scout.gmail.executor.send_reply`` — the single function
permitted to put mail on the wire. Nothing here duplicates it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from scout.config import settings
from scout.connectors.base import (
    ActionResult,
    ApprovedAction,
    MetadataInventory,
    SendResult,
)

logger = logging.getLogger(__name__)

__all__ = ["GmailAdapter"]

SOURCE_SYSTEM = "gmail"


class GmailAdapter:
    """The Gmail source adapter. Satisfies all four protocols structurally."""

    def __init__(self, client: Any = None, account_id: str | None = None) -> None:
        self._client = client
        self._account_id = account_id

    # -- lazy client -------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            from scout.gmail.client import get_client

            self._client = get_client()
        return self._client

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            self._account_id = (
                self.client.get_profile().get("emailAddress") or settings.gmail_user
            )
        return self._account_id

    # -- MetadataReader ----------------------------------------------------

    def scan(self) -> MetadataInventory:
        """Describe the mailbox without extracting from it."""
        profile = self.client.get_profile()
        return MetadataInventory(
            source_system=SOURCE_SYSTEM,
            objects=[
                {"name": "message", "count": profile.get("messagesTotal"), "custom": False},
                {"name": "thread", "count": profile.get("threadsTotal"), "custom": False},
            ],
            threads=profile.get("threadsTotal"),
            messages=profile.get("messagesTotal"),
            # Gmail is the one real source in Slice 1; everything else is emulated.
            is_emulated=settings.use_gmail_fixtures,
            rate_limit={"quota_units_per_user_per_second": 250},
            scanned_at=datetime.now(timezone.utc),
        )

    # -- DataReader --------------------------------------------------------

    def backfill(self, cursor: str | None = None) -> Any:
        """Walk the mailbox, resuming from ``cursor`` (a page token)."""
        return self.client.iter_all_message_ids(start_page_token=cursor)

    def fetch(self, entity: str, external_id: str) -> Any:
        if entity in ("message", "messages"):
            return self.client.get_message(external_id, format="full")
        raise ValueError(f"GmailAdapter cannot fetch entity {entity!r}")

    # -- EventListener (Slice 1: polling only) ------------------------------

    def verify(self, headers: dict[str, str], body: bytes) -> bool:
        raise NotImplementedError(
            "Gmail has no signed webhook; Slice 1 polls. Push arrives via "
            "Pub/Sub at scout.gmail.ingest_api, which needs no signature check."
        )

    def to_events(self, body: bytes) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "Gmail push carries only {emailAddress, historyId}, never the mail. "
            "Slice 1 re-syncs instead of parsing events."
        )

    # -- ActionExecutor ----------------------------------------------------

    def execute(self, action: ApprovedAction, **kwargs: Any) -> ActionResult:
        """Execute an approved action. The type carries the approval."""
        if action.action_type not in ("send_reply", "reply", "email_reply"):
            raise ValueError(f"GmailAdapter cannot execute {action.action_type!r}")
        from scout.gmail.executor import send_reply

        result = send_reply(
            approval_id=action.approval_id,
            case_id=action.case_id,
            payload_hash=action.payload_hash,
            **kwargs,
        )
        return result.as_action_result()

    # -- convenience used by Task 22's dispatch -----------------------------

    def send_reply(self, *, case_id: Any, body: str, **kwargs: Any) -> str:
        """Resolve reply details from the canonical layer, then send.

        Task 22 (``scout/canonical/execution.py``) calls this with only
        ``case_id`` and ``body``; recipient, subject, thread and the approval
        are looked up here so the canonical layer never has to know Gmail's
        shape. Returns the Gmail message id, which is what it stores as
        ``execution_ref``.
        """
        from scout.gmail.executor import send_reply as _send

        details = self._reply_details(case_id)
        details.update({k: v for k, v in kwargs.items() if v is not None})
        result: SendResult = _send(body_text=body, **details)
        return result.message_id

    def _reply_details(self, case_id: Any) -> dict[str, Any]:
        """Look up recipient, subject, thread and approval for a case."""
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from scout.canonical.models import Case, Message, Person, RecommendationDecision

        engine = create_engine(settings.database_url, pool_pre_ping=True)
        with Session(engine) as session:
            case = session.scalar(select(Case).where(Case.id == case_id))
            if case is None:
                raise ValueError(f"no case {case_id}")

            # Newest inbound message decides the thread and the message we reply to.
            inbound = session.scalars(
                select(Message)
                .where(Message.case_id == case_id, Message.direction == "inbound")
                .order_by(Message.sent_at.desc())
            ).first()

            requester = session.scalar(select(Person).where(Person.id == case.requester_id))
            decision = session.scalars(
                select(RecommendationDecision)
                .where(RecommendationDecision.case_id == case_id)
                .order_by(RecommendationDecision.decided_at.desc())
            ).first()

        if requester is None or not requester.primary_email:
            raise ValueError(f"case {case_id} has no requester email to reply to")
        if decision is None:
            raise ValueError(f"case {case_id} has no decision to send")

        return {
            "approval_id": decision.id,
            "case_id": case_id,
            "to_address": requester.primary_email,
            "subject": (inbound.subject if inbound else None) or case.subject,
            "thread_external_id": inbound.thread_id if inbound else None,
            "in_reply_to_message_id": inbound.src_message_id if inbound else None,
            "payload_hash": decision.payload_hash or "",
        }
