"""
MinIO / S3 raw-lake client.

Thin wrapper over boto3 so the rest of the codebase never imports boto3
directly. S3-compatible throughout: pointing at real AWS S3 means changing
``minio_endpoint`` and setting ``minio_addressing_style="virtual"``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from scout.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PutResult:
    bucket: str
    key: str
    size_bytes: int
    etag: str | None
    sha256: str


class RawLakeError(RuntimeError):
    """Raised when the raw lake is unreachable or rejects an operation."""


class RawLakeClient:
    """Object-store client for the ``raw`` bucket."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        addressing_style: str | None = None,
    ) -> None:
        self.endpoint = (endpoint or settings.minio_endpoint).rstrip("/")
        self.bucket = bucket or settings.minio_bucket
        access = access_key or settings.minio_access_key
        secret = secret_key or settings.minio_secret_key
        missing = [
            name
            for name, value in (
                ("MINIO_ENDPOINT", self.endpoint),
                ("MINIO_ACCESS_KEY", access),
                ("MINIO_SECRET_KEY", secret),
            )
            if not value
        ]
        if missing:
            raise RawLakeError(
                f"Missing MinIO settings: {', '.join(missing)}. "
                "Set them in .env.local (gitignored) — never in source."
            )
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name=region or settings.minio_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style or settings.minio_addressing_style},
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=15,
                read_timeout=120,
            ),
        )

    # ── bucket ────────────────────────────────────────────────────────────────

    def bucket_exists(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "NotFound"}:
                return False
            if code in {"403", "AccessDenied"}:
                # Bucket exists but HEAD is not permitted for this key.
                return True
            raise RawLakeError(f"head_bucket failed: {exc}") from exc

    def ensure_bucket(self) -> None:
        if self.bucket_exists():
            return
        logger.info("Creating bucket %s", self.bucket)
        try:
            self._client.create_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                return
            raise RawLakeError(f"create_bucket failed: {exc}") from exc

    # ── objects ───────────────────────────────────────────────────────────────

    def stat_object(self, key: str) -> dict[str, Any] | None:
        """
        HEAD one object. Returns None when absent.

        This is the duplicate check (handover doc section 8). The returned
        user metadata carries what we stamped at write time, which is enough
        to rebuild an audit row without re-reading the body.
        """
        try:
            res = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise RawLakeError(f"head_object {key} failed: {exc}") from exc
        return {
            "key": key,
            "size_bytes": int(res.get("ContentLength") or 0),
            "etag": (res.get("ETag") or "").strip('"') or None,
            "last_modified": res.get("LastModified"),
            "metadata": res.get("Metadata") or {},
        }

    def object_exists(self, key: str) -> bool:
        return self.stat_object(key) is not None

    def put_bytes(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        metadata: dict[str, str] | None = None,
    ) -> PutResult:
        sha = hashlib.sha256(body).hexdigest()
        try:
            res = self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata=_clean_metadata(metadata or {}),
            )
        except ClientError as exc:
            raise RawLakeError(f"put_object {key} failed: {exc}") from exc
        return PutResult(
            bucket=self.bucket,
            key=key,
            size_bytes=len(body),
            etag=(res.get("ETag") or "").strip('"') or None,
            sha256=sha,
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            res = self._client.get_object(Bucket=self.bucket, Key=key)
            return res["Body"].read()
        except ClientError as exc:
            raise RawLakeError(f"get_object {key} failed: {exc}") from exc

    def list_keys(self, prefix: str, *, limit: int = 1000) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while len(keys) < limit:
            kwargs: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": min(1000, limit - len(keys)),
            }
            if token:
                kwargs["ContinuationToken"] = token
            try:
                res = self._client.list_objects_v2(**kwargs)
            except ClientError as exc:
                raise RawLakeError(f"list_objects_v2 {prefix} failed: {exc}") from exc
            keys.extend(item["Key"] for item in res.get("Contents") or [])
            token = res.get("NextContinuationToken")
            if not res.get("IsTruncated") or not token:
                break
        return keys


def _clean_metadata(meta: dict[str, str]) -> dict[str, str]:
    """
    S3 user metadata must be ASCII header-safe. Drop empties, coerce to str,
    and strip characters that would break the HTTP header round-trip.
    """
    out: dict[str, str] = {}
    for key, value in meta.items():
        if value is None or value == "":
            continue
        text = str(value).replace("\n", " ").replace("\r", " ")
        out[key] = text.encode("ascii", errors="ignore").decode("ascii")[:1024]
    return out
