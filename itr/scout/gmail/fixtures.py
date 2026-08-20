"""
itr/scout/gmail/fixtures.py — offline Gmail replay (Task 9).

If a token expires, Google rate-limits, or venue wifi drops mid-demonstration,
the pipeline still runs. It also lets the whole adapter suite run with zero
services, which keeps CI fast.

FixtureClient exposes the same method surface as GmailClient but reads from a
directory of exported JSON instead of the network, simulating page tokens and a
historyId progression so an incremental sync can be exercised offline.

Populate the directory with ``scripts/export_fixtures.py``.
"""

from __future__ import annotations

import base64
import json
import logging
import pathlib
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:  # pragma: no cover
    from scout.gmail.client import GmailMessage

logger = logging.getLogger(__name__)

__all__ = ["FixtureClient", "FixtureError", "MANIFEST_NAME"]

MANIFEST_NAME = "manifest.json"


class FixtureError(RuntimeError):
    """Raised when the fixture directory is missing or unusable."""


class FixtureClient:
    """Drop-in stand-in for GmailClient, backed by exported JSON.

    Page tokens are the index of the next message encoded as a string, so
    pagination behaves like Gmail's: an opaque token the caller passes back,
    and no token at all on the final page.
    """

    def __init__(
        self,
        fixtures_dir: str | pathlib.Path | None = None,
        *,
        account_id: str | None = None,
    ) -> None:
        from scout.config import settings

        self.dir = pathlib.Path(fixtures_dir or settings.gmail_fixtures_dir)
        if not self.dir.exists():
            raise FixtureError(
                f"fixture directory {self.dir} does not exist - "
                "run: poetry run python scripts/export_fixtures.py"
            )
        manifest_path = self.dir / MANIFEST_NAME
        if not manifest_path.exists():
            raise FixtureError(f"{manifest_path} missing - re-run export_fixtures.py")

        self.manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.account_id = account_id or self.manifest.get("account_id") or "me"
        # Message order comes from the manifest, not the filesystem: replay must
        # be deterministic, and a directory listing is not.
        self.order: list[str] = list(self.manifest.get("message_order") or [])
        self.files: dict[str, str] = dict(self.manifest.get("files") or {})
        self.thread_of: dict[str, str] = dict(self.manifest.get("thread_of") or {})
        self.history: list[dict[str, Any]] = list(self.manifest.get("history") or [])
        self.attachments: dict[str, str] = dict(self.manifest.get("attachments") or {})
        self._cache: dict[str, dict[str, Any]] = {}
        logger.info("FixtureClient: %d message(s) from %s", len(self.order), self.dir)

    # -- loading -------------------------------------------------------------

    def _load(self, message_id: str) -> dict[str, Any]:
        if message_id in self._cache:
            return self._cache[message_id]
        name = self.files.get(message_id)
        if not name:
            raise FixtureError(f"no fixture for message {message_id}")
        doc = json.loads((self.dir / name).read_text(encoding="utf-8"))
        self._cache[message_id] = doc
        return doc

    # -- GmailClient surface -------------------------------------------------

    def get_profile(self) -> dict[str, Any]:
        return {
            "emailAddress": self.account_id,
            "messagesTotal": len(self.order),
            "threadsTotal": len(self.manifest.get("threads") or {}),
            "historyId": str(self.manifest.get("final_history_id") or len(self.order)),
        }

    def list_message_refs(
        self,
        *,
        max_results: int = 10,
        page_token: str | None = None,
        q: str | None = None,
        include_spam_trash: bool = False,
    ) -> dict[str, Any]:
        """One page of refs in Gmail's own response shape.

        Signature and return type mirror GmailClient exactly — the doc asks for
        the same method surface, and callers such as fetch_messages() read
        ``data["messages"]`` and ``data["nextPageToken"]`` straight off it.
        """
        start = int(page_token) if page_token else 0
        window = self.order[start : start + max(1, max_results)]
        nxt = start + len(window)
        data: dict[str, Any] = {
            "messages": [
                {"id": mid, "threadId": self.thread_of.get(mid, f"t-{mid}")}
                for mid in window
            ],
            "resultSizeEstimate": len(self.order),
        }
        if nxt < len(self.order):
            data["nextPageToken"] = str(nxt)
        return data

    def iter_all_message_ids(
        self,
        *,
        q: str | None = None,
        include_spam_trash: bool = True,
        page_size: int = 100,
        limit: int | None = None,
        start_page_token: str | None = None,
    ) -> Iterator[tuple[str, str | None]]:
        """Walk every message id, yielding (id, next_page_token)."""
        page_token = start_page_token
        seen = 0
        while True:
            data = self.list_message_refs(
                max_results=min(page_size, 500),
                page_token=page_token,
                q=q or None,
                include_spam_trash=include_spam_trash,
            )
            next_token = data.get("nextPageToken")
            for ref in data.get("messages") or []:
                yield ref["id"], next_token
                seen += 1
                if limit is not None and seen >= limit:
                    return
            page_token = next_token
            if not page_token:
                return

    def get_message(self, message_id: str, *, format: str = "full") -> dict[str, Any]:
        doc = self._load(message_id)
        if format == "minimal":
            return {k: v for k, v in doc.items() if k != "payload"}
        return doc

    def get_attachment_bytes(self, *, message_id: str, attachment_id: str) -> bytes:
        name = self.attachments.get(f"{message_id}/{attachment_id}")
        if not name:
            raise FixtureError(f"no attachment fixture for {message_id}/{attachment_id}")
        return (self.dir / name).read_bytes()

    def list_history_message_ids(
        self, *, start_history_id: str, history_types: str = "messageAdded"
    ) -> tuple[list[str], str | None]:
        """Message ids newer than start_history_id, plus the newest id.

        The exporter stamps each message with an increasing synthetic historyId,
        so an incremental sync replays offline exactly as it would online: pass
        the previous cursor, get back only what is newer.
        """
        try:
            start = int(start_history_id)
        except (TypeError, ValueError):
            start = 0
        newer = [e["message_id"] for e in self.history if int(e["history_id"]) > start]
        newest = self.manifest.get("final_history_id")
        return newer, (str(newest) if newest is not None else None)

    # -- names the Slice-1 doc uses ------------------------------------------
    # The doc calls these list_messages / history_list. The live GmailClient
    # calls them list_message_refs / list_history_message_ids, and sync.py uses
    # those. Both names are provided so either reading works.

    def list_messages(self, page_token: str | None = None, **kw: Any) -> dict[str, Any]:
        return self.list_message_refs(page_token=page_token, **kw)

    def history_list(self, start_history_id: str, **kw: Any):
        return self.list_history_message_ids(start_history_id=start_history_id, **kw)

    # -- higher-level helpers the real client also exposes -------------------

    def fetch_messages(
        self, *, max_results: int = 10, q: str | None = None
    ) -> list[GmailMessage]:
        from scout.gmail.client import parse_message

        listing = self.list_message_refs(max_results=max_results, q=q)
        return [
            parse_message(self.get_message(ref["id"], format="full"))
            for ref in listing.get("messages") or []
        ]

    def fetch_messages_by_ids(self, message_ids: list[str]) -> list[GmailMessage]:
        from scout.gmail.client import parse_message

        return [parse_message(self.get_message(m, format="full")) for m in message_ids]

    # -- inert bits of the real client ---------------------------------------

    def close(self) -> None:
        return

    def watch(
        self,
        *,
        topic_name: str,
        label_ids: list[str] | None = None,
        label_filter_behavior: str = "include",
    ) -> dict[str, Any]:
        raise FixtureError("watch() needs the real Gmail API; fixtures are read-only")

    def stop_watch(self) -> None:
        return


def decode_body(data: str) -> bytes:
    """base64url helper, exposed for tests that build fixtures by hand."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
