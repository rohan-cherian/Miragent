"""
Task 15 — thread/reply-matching helpers.

Pure lookups against itr360.message; no writes, no case-creation
logic (that's scout.canonical.correlation). Must never import
scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).

ASSUMPTION: works against Task 5/7's src_message shape (Rohan's
side), not verified against real data in this workspace.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.canonical.models import Message


def find_case_by_thread_id(session: Session, thread_id: str | None) -> uuid.UUID | None:
    """Rule 1 (same_thread): any itr360.message row sharing this thread_id -> its case_id."""
    if not thread_id:
        return None

    message = session.execute(
        select(Message).where(Message.thread_id == thread_id)
    ).scalars().first()

    return message.case_id if message is not None else None


def find_case_by_in_reply_to(session: Session, in_reply_to: str | None) -> uuid.UUID | None:
    """Rule 2 (in_reply_to): the message this one replies to (matched on
    src_message_id) -> its case_id. Fallback for clients that break threading."""
    if not in_reply_to:
        return None

    message = session.execute(
        select(Message).where(Message.src_message_id == in_reply_to)
    ).scalar_one_or_none()

    return message.case_id if message is not None else None
