"""Raw landing zone (MinIO / S3-compatible object storage)."""

from scout.raw.keys import (
    InvalidMessageId,
    account_segment,
    build_object_key,
    day_prefix,
    partition_date,
    safe_message_id,
)
from scout.raw.minio_client import PutResult, RawLakeClient, RawLakeError

__all__ = [
    "InvalidMessageId",
    "PutResult",
    "RawLakeClient",
    "RawLakeError",
    "account_segment",
    "build_object_key",
    "day_prefix",
    "partition_date",
    "safe_message_id",
]
