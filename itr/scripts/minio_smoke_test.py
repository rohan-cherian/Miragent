"""
Verify MinIO connectivity, credentials, and the raw bucket.

Writes a tiny probe object under _healthcheck/ and reads it back, then
deletes nothing — the probe key is stable so repeat runs overwrite it and
never accumulate junk.

Usage:
  poetry run python scripts/minio_smoke_test.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.raw.minio_client import RawLakeClient, RawLakeError


def main() -> int:
    print(f"Endpoint : {settings.minio_endpoint}")
    print(f"Bucket   : {settings.minio_bucket}")

    lake = RawLakeClient()
    try:
        exists = lake.bucket_exists()
        print(f"Bucket exists: {exists}")
        if not exists:
            lake.ensure_bucket()
            print("Bucket created.")

        key = "_healthcheck/scout-probe.json"
        body = json.dumps(
            {"probe": "scout", "at": datetime.now(timezone.utc).isoformat()},
            indent=2,
        ).encode("utf-8")
        put = lake.put_bytes(key=key, body=body)
        print(f"PUT  {key}  ({put.size_bytes} bytes, etag={put.etag})")

        back = lake.get_bytes(key)
        print(f"GET  {key}  ({len(back)} bytes) -> {json.loads(back)}")

        keys = lake.list_keys(settings.gmail_raw_prefix + "/", limit=10)
        print(f"Existing objects under {settings.gmail_raw_prefix}/: {len(keys)}")
        for k in keys[:10]:
            print(f"  {k}")
        print("\nMinIO OK.")
        return 0
    except RawLakeError as exc:
        print(f"MinIO check FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
