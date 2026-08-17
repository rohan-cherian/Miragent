"""
MinIO / S3 raw-lake client.

Thin wrapper over boto3 so the rest of the codebase never imports boto3
directly. S3-compatible throughout: pointing at real AWS S3 means changing
``minio_endpoint`` and setting ``minio_addressing_style="virtual"``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from scout.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Transient S3/MinIO conditions worth a retry. Anything else (NoSuchKey,
# AccessDenied, a bad bucket name) is a real answer and retrying only delays it.
_RETRYABLE_CODES = {
    "InternalError",
    "RequestTimeout",
    "RequestTimeTooSkewed",
    "SlowDown",
    "ServiceUnavailable",
    "ThrottlingException",
    "503",
    "500",
}
_RETRY_ATTEMPTS = 3
_RETRY_BASE_SECONDS = 0.5


def sha256(data: bytes) -> str:
    """Content hash of raw bytes, as the doc's Task 6 API specifies."""
    return hashlib.sha256(data).hexdigest()


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, BotoCoreError):
        return True
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        status = str(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
        return err.get("Code") in _RETRYABLE_CODES or status in {"500", "503", "429"}
    return False


def _with_retry(what: str, fn: Callable[[], T]) -> T:
    """Run ``fn``, retrying transient failures with exponential backoff.

    Never logs payloads — only the operation name and the error — because raw
    objects contain customer mail.
    """
    last: Exception | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            if not _is_retryable(exc) or attempt == _RETRY_ATTEMPTS:
                last = exc
                break
            delay = _RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "%s failed (attempt %d/%d, %s), retrying in %.1fs",
                what,
                attempt,
                _RETRY_ATTEMPTS,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
            last = exc
    raise RawLakeError(f"{what} failed after {_RETRY_ATTEMPTS} attempts: {last}") from last


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

    # ── doc's Task 6 API ─────────────────────────────────────────────────────
    # put_raw / get_raw / sha256 / ensure_bucket are the names the Slice-1 doc
    # specifies. They wrap the methods above and add the retry the doc asks
    # for. stat_object / object_exists are kept alongside them: the doc's API
    # has no HEAD because its dedup lives in Postgres, whereas handover doc
    # section 8 makes the bucket itself the authority. Losing them would remove
    # the duplicate guard, so both survive.

    def put_raw(self, data: bytes, key: str, *, content_type: str = "application/json") -> str:
        """Write bytes and return the object path to store in Postgres.

        The returned path is the key, which is what ``get_raw`` accepts back
        and what ``src_gmail.message.object_path`` records.
        """
        _with_retry(
            f"put_raw {key}",
            lambda: self.put_bytes(key=key, body=data, content_type=content_type),
        )
        return key

    def get_raw(self, object_path: str) -> bytes:
        """Read bytes back by object path.

        Accepts either a bare key or a ``bucket/key`` form, so a path read out
        of Postgres round-trips whichever way it was recorded.
        """
        key = object_path
        if key.startswith(f"{self.bucket}/"):
            key = key[len(self.bucket) + 1 :]
        return _with_retry(f"get_raw {key}", lambda: self.get_bytes(key))

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
