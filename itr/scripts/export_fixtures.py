"""
Export the raw lake into offline Gmail fixtures (Task 9).

Reads every object under ``raw/gmail/`` in MinIO and writes numbered JSON files
into ``scout/gmail/fixtures/``, plus a manifest recording thread grouping,
message order and a synthetic historyId sequence so an incremental sync can be
replayed offline.

One wrinkle worth knowing: the raw objects are ENVELOPE documents, not verbatim
Gmail API responses. ``envelope.strip_body_data`` deliberately removes
``body.data`` from the stored MIME tree, because the decoded bodies are already
held in ``body_text`` / ``body_html`` and storing both would double every
object. So a fixture is REBUILT into ``format=full`` shape rather than copied:
the part tree comes back from ``mime_tree``, the header list from
``headers_raw``, and body bytes are re-encoded into the text parts from
``body_text`` / ``body_html``.

Attachment bytes live in their own objects (Task 6), so they are pulled down
alongside and written as files the FixtureClient can serve.

Usage:
  poetry run python scripts/export_fixtures.py
  poetry run python scripts/export_fixtures.py --out scout/gmail/fixtures --limit 50
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings  # noqa: E402
from scout.raw.minio_client import RawLakeClient  # noqa: E402


def b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def rebuild_payload(doc: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a Gmail ``format=full`` payload from an envelope document.

    Walks the stored mime_tree and puts back what was stripped: base64url body
    data for the text parts, and attachmentId for attachment parts.
    """
    text_body = doc.get("body_text") or doc.get("body") or ""
    html_body = doc.get("body_html") or ""
    used = {"text": False, "html": False}

    def walk(node: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "partId": node.get("partId", ""),
            "mimeType": node.get("mimeType") or "text/plain",
            "filename": node.get("filename") or "",
            "headers": list(node.get("headers") or []),
        }
        body = dict(node.get("body") or {})
        body.pop("has_data", None)
        mime = out["mimeType"]
        if mime == "text/plain" and not out["filename"] and not used["text"]:
            body["data"] = b64url(text_body)
            body["size"] = len(text_body)
            used["text"] = True
        elif mime == "text/html" and not out["filename"] and not used["html"]:
            body["data"] = b64url(html_body)
            body["size"] = len(html_body)
            used["html"] = True
        out["body"] = body
        if node.get("parts"):
            out["parts"] = [walk(p) for p in node["parts"]]
        return out

    tree = doc.get("mime_tree")
    if tree:
        payload = walk(tree)
    else:
        # No tree stored (very old object): synthesise the simplest valid shape.
        payload = {
            "partId": "",
            "mimeType": "text/plain",
            "filename": "",
            "headers": [],
            "body": {"size": len(text_body), "data": b64url(text_body)},
        }

    # Headers, in the order they arrived, so a re-parse sees what Gmail sent.
    raw_headers = doc.get("headers_raw") or []
    if raw_headers:
        payload["headers"] = [
            {"name": h.get("name"), "value": h.get("value")} for h in raw_headers
        ]
    return payload


def rebuild_message(doc: dict[str, Any], history_id: int) -> dict[str, Any]:
    """Envelope document -> Gmail ``users.messages.get(format=full)`` shape."""
    return {
        "id": doc.get("message_id"),
        "threadId": doc.get("thread_id") or f"t-{doc.get('message_id')}",
        # Synthetic, increasing: this is what makes offline incremental replay
        # possible. The original historyId is kept for reference.
        "historyId": str(history_id),
        "originalHistoryId": doc.get("history_id"),
        "internalDate": str(doc.get("internal_date_ms") or 0),
        "labelIds": list(doc.get("label_ids") or []),
        "snippet": doc.get("snippet") or "",
        "sizeEstimate": int(doc.get("size_estimate") or 0),
        "payload": rebuild_payload(doc),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export raw/gmail/ into offline fixtures")
    ap.add_argument("--out", default=settings.gmail_fixtures_dir)
    ap.add_argument("--prefix", default=settings.gmail_raw_prefix)
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--clean", action="store_true", help="empty the directory first")
    args = ap.parse_args()

    out = Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    lake = RawLakeClient()
    keys = lake.list_keys(f"{args.prefix.strip('/')}/", limit=args.limit)
    message_keys = sorted(k for k in keys if k.endswith(".json") and "/attachments/" not in k)
    if not message_keys:
        print(f"No objects under {args.prefix}/ - nothing to export.")
        return 1
    print(f"Found {len(message_keys)} message object(s) under {args.prefix}/")

    files: dict[str, str] = {}
    thread_of: dict[str, str] = {}
    threads: dict[str, list[str]] = {}
    history: list[dict[str, Any]] = []
    attachments: dict[str, str] = {}
    order: list[str] = []
    docs: list[tuple[str, dict[str, Any]]] = []

    for key in message_keys:
        doc = json.loads(lake.get_raw(key).decode("utf-8"))
        mid = doc.get("message_id")
        if not mid:
            print(f"  skip {key}: no message_id")
            continue
        docs.append((mid, doc))

    # Oldest first, so the synthetic historyId sequence rises with real time and
    # an incremental replay returns messages in the order they arrived.
    docs.sort(key=lambda pair: int(pair[1].get("internal_date_ms") or 0))

    for index, (mid, doc) in enumerate(docs, start=1):
        history_id = index * 10  # leaves room between entries
        message = rebuild_message(doc, history_id)
        name = f"{index:04d}_{mid}.json"
        (out / name).write_text(json.dumps(message, indent=2), encoding="utf-8")

        files[mid] = name
        order.append(mid)
        thread = message["threadId"]
        thread_of[mid] = thread
        threads.setdefault(thread, []).append(mid)
        history.append({"history_id": history_id, "message_id": mid, "thread_id": thread})

        for att in doc.get("attachments") or []:
            path = att.get("object_path")
            att_id = att.get("attachment_id") or att.get("part_id")
            if not path or not att_id:
                continue
            try:
                raw = lake.get_raw(path)
            except Exception as exc:  # one bad attachment must not stop the export
                print(f"  ! attachment {path}: {type(exc).__name__}")
                continue
            att_name = f"{index:04d}_{mid}__{att_id}.bin"
            (out / att_name).write_bytes(raw)
            attachments[f"{mid}/{att_id}"] = att_name

        print(f"  {name}  thread={thread}  historyId={history_id}")

    manifest = {
        "account_id": settings.gmail_user
        if settings.gmail_user != "me"
        else (docs[0][1].get("account_id") if docs else "me"),
        "source_prefix": args.prefix,
        "message_count": len(order),
        "message_order": order,
        "files": files,
        "thread_of": thread_of,
        "threads": threads,
        "history": history,
        "final_history_id": (len(order) * 10) if order else 0,
        "attachments": attachments,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(
        f"\nWrote {len(order)} message(s), {len(threads)} thread(s), "
        f"{len(attachments)} attachment(s) to {out}"
    )
    print("Replay offline with:  USE_GMAIL_FIXTURES=true poetry run python "
          "scripts/gmail_sync_once.py --backfill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
