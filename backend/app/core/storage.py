"""
Where uploaded bytes live: private S3, and nothing else.

Every file the system accepts — supplier quotations, proformas, tax
invoices, purchase orders, rate lists, whatever a supplier sends — arrives
through one endpoint and one `documents` row, so this one module is the
whole storage surface. There is no local-disk path any more, deliberately:
a fallback that writes to disk when S3 is misconfigured is exactly the
fallback that silently ships unencrypted customer documents to a server's
filesystem. If S3 is not reachable, the upload fails.

BR-DOC-03 — "files are stored only in S3 with server-side encryption;
downloads are pre-signed and expire in 5 minutes" — is satisfied here:

  * `put()` sends `ServerSideEncryption` on every object, so an object
    cannot be written unencrypted even if the bucket default were removed.
  * `presigned_get_url()` signs for `s3_presign_ttl_seconds` (300).
  * Nothing in the codebase ever makes an object or the bucket public.

## The key

    co/{company_id}/{document_type}/{yyyy}/{mm}/{uuid4hex}{.ext}

Random, not content-addressed, and the original filename is not in it. Two
reasons. A key built from the user's filename leaks
"Acme_Q3_price_list.xlsx" to anyone who can see a log line, a metrics
label or a signed URL; and a key built from the content hash lets someone
who can guess a document's bytes confirm the guess by probing for the key.
The real filename lives in `documents.original_filename`, is served back in
the download's `Content-Disposition`, and is never a security boundary.

De-duplication does not need the key: `uq_document_hash (company_id,
sha256_hash)` does it in Postgres, per tenant, which is where BR-DOC-02
says it belongs. The cost is that two tenants uploading identical bytes
store two objects. That is correct — tenant deletion must not be able to
take another tenant's file with it.

## Credentials

Read from settings, which read the environment. Never logged, never
returned in an error body, never written into a key. `aws_endpoint_url`
exists so a LocalStack / MinIO endpoint can stand in for AWS in
development; when it is set, path-style addressing is forced, because
`http://bucket.localhost:4566` does not resolve.

## Async

boto3 is synchronous. Every call here has an `a`-prefixed async twin that
runs the blocking call on a worker thread, so a 20 MB upload does not stall
the event loop for every other request on the process. Handlers use the
async twins; scripts can use the sync ones.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import anyio.to_thread
import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings


class StorageError(RuntimeError):
    """S3 would not do what we asked.

    Carries a short, non-leaking reason. The AWS error code is included
    because it is operationally useful and contains no secret; the
    credentials, endpoint and bucket are not.
    """

    def __init__(self, action: str, code: str = "") -> None:
        self.action = action
        self.code = code
        super().__init__(f"Object storage could not {action}" + (f" ({code})" if code else ""))


class StorageNotConfigured(RuntimeError):
    """No bucket configured. Raised at startup, not on the first upload."""


# Keys that mean "this object is not there", as opposed to "S3 is unhappy".
_MISSING = {"NoSuchKey", "404", "NotFound"}


@lru_cache
def _client():
    """One client per process. Thread-safe for the calls made here, and
    expensive enough to build that per-request construction shows up."""
    settings = get_settings()
    if not settings.s3_bucket:
        raise StorageNotConfigured(
            "S3_BUCKET is not set. Uploads and downloads are disabled — "
            "there is deliberately no local-disk fallback."
        )
    endpoint = settings.aws_endpoint_url or None
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=endpoint,
        # Explicit rather than relying on the ambient credential chain, so a
        # stray ~/.aws/credentials on a dev box cannot quietly point the app
        # at a real bucket. Empty values fall back to the chain, which is
        # what an EC2/ECS instance role needs.
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        config=Config(
            # v4 is required for SSE-KMS and for presigned URLs that expire
            # in minutes rather than hours.
            signature_version="s3v4",
            # A custom endpoint is almost always LocalStack or MinIO, where
            # virtual-host addressing does not resolve.
            s3={"addressing_style": "path" if endpoint else "auto"},
            retries={"max_attempts": settings.s3_max_attempts, "mode": "standard"},
            connect_timeout=settings.s3_connect_timeout_seconds,
            read_timeout=settings.s3_read_timeout_seconds,
        ),
    )


def reset_client() -> None:
    """Drop the cached client. Tests and the settings cache need this."""
    _client.cache_clear()


def bucket() -> str:
    return get_settings().s3_bucket


def _sse_args() -> dict:
    settings = get_settings()
    args: dict = {"ServerSideEncryption": settings.s3_sse}
    if settings.s3_sse == "aws:kms" and settings.s3_kms_key_id:
        args["SSEKMSKeyId"] = settings.s3_kms_key_id
    return args


# --------------------------------------------------------------------- keys


def build_key(
    *,
    company_id: str,
    document_type: Optional[str] = None,
    extension: str = "",
    at: Optional[datetime] = None,
) -> str:
    """A fresh random key. Never derived from the filename or the bytes.

    `document_type` is what the uploader claimed, or `unclassified` when
    they claimed nothing — the classifier's later verdict does not move the
    object, because rewriting a key would mean a copy, a delete and a window
    where the row points at neither.
    """
    when = at or datetime.now(timezone.utc)
    kind = (document_type or "unclassified").strip().lower().replace("/", "_") or "unclassified"
    ext = extension.strip().lstrip(".").lower()
    suffix = f".{ext}" if ext.isalnum() and 0 < len(ext) <= 8 else ""
    return f"co/{company_id}/{kind}/{when:%Y}/{when:%m}/{uuid.uuid4().hex}{suffix}"


# ------------------------------------------------------------------ writing


def put(key: str, blob: bytes, *, content_type: str = "application/octet-stream") -> None:
    """Write one object, encrypted. Retries are botocore's (`standard` mode:
    exponential backoff on throttling and 5xx); a failure that survives them
    is real and is raised rather than swallowed."""
    try:
        _client().put_object(
            Bucket=bucket(),
            Key=key,
            Body=blob,
            ContentType=content_type,
            **_sse_args(),
        )
    except ClientError as exc:
        raise StorageError("store the file", exc.response.get("Error", {}).get("Code", "")) from exc
    except BotoCoreError as exc:
        raise StorageError("store the file") from exc


async def aput(key: str, blob: bytes, *, content_type: str = "application/octet-stream") -> None:
    await anyio.to_thread.run_sync(lambda: put(key, blob, content_type=content_type))


# ------------------------------------------------------------------ reading


def get(key: str) -> Optional[bytes]:
    """The bytes, or None when the object is not there. A missing object is
    a normal outcome the caller reports as 404; anything else is an error."""
    try:
        return _client().get_object(Bucket=bucket(), Key=key)["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _MISSING:
            return None
        raise StorageError("read the file", code) from exc
    except BotoCoreError as exc:
        raise StorageError("read the file") from exc


async def aget(key: str) -> Optional[bytes]:
    return await anyio.to_thread.run_sync(lambda: get(key))


def exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=bucket(), Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code", "") in _MISSING:
            return False
        raise StorageError("check the file", exc.response.get("Error", {}).get("Code", "")) from exc
    except BotoCoreError as exc:
        raise StorageError("check the file") from exc


async def aexists(key: str) -> bool:
    return await anyio.to_thread.run_sync(lambda: exists(key))


# ----------------------------------------------------------------- deleting


def delete(key: str) -> None:
    """Idempotent: deleting an absent key is a success, because every caller
    is either cleaning up after a failure or deleting something already
    gone, and neither wants an exception for that."""
    try:
        _client().delete_object(Bucket=bucket(), Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _MISSING:
            return
        raise StorageError("delete the file", code) from exc
    except BotoCoreError as exc:
        raise StorageError("delete the file") from exc


async def adelete(key: str) -> None:
    await anyio.to_thread.run_sync(lambda: delete(key))


async def adelete_quietly(key: str) -> bool:
    """Best-effort cleanup for the compensating path after a failed commit.

    The caller is already handling one failure and must not be derailed by a
    second; an object we could not delete becomes an orphan, which
    `scripts/s3_orphans.py` finds later. Returns whether it went.
    """
    try:
        await adelete(key)
        return True
    except (StorageError, StorageNotConfigured):
        return False


# --------------------------------------------------------------- presigning


def presigned_get_url(
    key: str, *, filename: str, content_type: str = "application/octet-stream"
) -> tuple[str, datetime]:
    """A time-limited URL for exactly this object (BR-DOC-03).

    The signature covers the response headers too, so the link cannot be
    edited into one that renders an HTML document inline in the browser —
    `attachment` is signed in, not suggested. Returns the URL and the moment
    it dies, so the caller can tell the client rather than let it discover
    a 403.

    Authorisation happens *before* this is called: by the time a URL exists,
    the caller has been checked for `document.download` and the row has been
    read under the tenant's RLS scope. The URL is the last step, not the
    check.
    """
    ttl = get_settings().s3_presign_ttl_seconds
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "")[:200] or "document"
    try:
        url = _client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket(),
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{safe}"',
                "ResponseContentType": content_type,
            },
            ExpiresIn=ttl,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageError("sign a download link") from exc
    return url, datetime.now(timezone.utc) + timedelta(seconds=ttl)


async def apresigned_get_url(
    key: str, *, filename: str, content_type: str = "application/octet-stream"
) -> tuple[str, datetime]:
    return await anyio.to_thread.run_sync(
        lambda: presigned_get_url(key, filename=filename, content_type=content_type)
    )


# ------------------------------------------------------------------ listing


def iter_keys(prefix: str = "co/"):
    """Every key under a prefix. Used by the orphan reconciler, not by any
    request path — a tenant listing its own objects is never needed, because
    `documents` is the index."""
    paginator = _client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"], obj["LastModified"]


# ------------------------------------------------------------------- health


def _recreate_emulator_bucket(settings) -> bool:
    """Local S3 emulators (Floci, LocalStack, moto) keep buckets in memory,
    so restarting Docker loses the bucket and the API would refuse to boot.
    In development, against an emulator only, recreate it — private, the
    same as `start-storage.ps1` does. Never on real AWS (no endpoint URL)
    and never outside development: there a missing bucket is a real fault."""
    if not (settings.is_development and settings.aws_endpoint_url):
        return False
    import logging

    client = _client()
    try:
        client.create_bucket(Bucket=settings.s3_bucket)
        try:
            client.put_public_access_block(
                Bucket=settings.s3_bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )
        except (ClientError, BotoCoreError):
            pass  # some emulators don't implement it; the bucket is private by default
        client.head_bucket(Bucket=settings.s3_bucket)
    except (ClientError, BotoCoreError):
        return False
    logging.getLogger(__name__).warning(
        "Bucket %r was missing on the local S3 emulator at %s (in-memory storage is lost on restart) "
        "and has been recreated. Previously uploaded files are gone.",
        settings.s3_bucket,
        settings.aws_endpoint_url,
    )
    return True


def assert_ready() -> None:
    """Refuse to start when storage is not usable.

    Called from the app's lifespan. The alternative — discovering it on the
    first upload — means the first person to use the feature gets the 500,
    and nobody notices in an environment where nobody uploads for a day.
    """
    settings = get_settings()
    if not settings.s3_bucket:
        raise StorageNotConfigured(
            "S3_BUCKET is not set. Set S3_BUCKET (and AWS credentials, or an "
            "instance role) before starting the API — document upload and "
            "download have no local-disk fallback by design."
        )
    if settings.s3_sse not in {"AES256", "aws:kms"}:
        raise StorageNotConfigured(
            f"S3_SSE must be 'AES256' or 'aws:kms', not {settings.s3_sse!r}. "
            "BR-DOC-03 requires server-side encryption."
        )
    try:
        _client().head_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchBucket", "NotFound"} and _recreate_emulator_bucket(settings):
            return
        raise StorageNotConfigured(
            f"Bucket {settings.s3_bucket!r} is not reachable ({code}). Check the bucket "
            "name, the region, and that the credentials can read it."
        ) from exc
    except BotoCoreError as exc:
        raise StorageNotConfigured(
            f"Bucket {settings.s3_bucket!r} is not reachable. Check AWS_ENDPOINT_URL and the network."
        ) from exc
