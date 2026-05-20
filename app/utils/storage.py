"""Media storage helper for instructor uploads.

Two backends are supported, switched via ``settings.STORAGE_BACKEND``:

* ``local`` — files written under ``MEDIA_ROOT`` and exposed at ``MEDIA_URL``.
* ``s3``    — files uploaded to ``AWS_S3_BUCKET`` and served either from S3
              directly or from ``AWS_S3_PUBLIC_BASE_URL`` (e.g. CloudFront).

Uploads are streamed in 1 MiB chunks; the file size is enforced as the body
arrives so a malicious / oversized upload doesn't fill the disk before being
rejected.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Final

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import AppError, ValidationAppError
from app.core.logging import get_logger

logger = get_logger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Conservative defaults; tune via env if needed.
MAX_VIDEO_BYTES: Final[int] = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_IMAGE_BYTES: Final[int] = 20 * 1024 * 1024  # 20 MB
MAX_DOCUMENT_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DOCUMENT_EXTS = {".pdf", ".zip", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".csv"}

CONTENT_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".m4v": "video/x-m4v",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".csv": "text/csv",
}


def _sanitize(name: str) -> str:
    name = _SAFE_NAME_RE.sub("_", name).strip("._-")
    return name or "file"


def _kind_config(kind: str) -> tuple[set[str], int]:
    if kind == "video":
        return VIDEO_EXTS, MAX_VIDEO_BYTES
    if kind == "image":
        return IMAGE_EXTS, MAX_IMAGE_BYTES
    if kind == "document":
        return DOCUMENT_EXTS, MAX_DOCUMENT_BYTES
    raise ValueError(f"Unknown upload kind: {kind}")


async def _read_validated(
    upload: UploadFile, *, max_bytes: int
) -> tuple[BytesIO, int]:
    """Stream-read an UploadFile, enforce the size cap, return (buffer, size).

    The whole payload is held in memory; for our 2 GB video cap that means a
    worst-case 2 GB allocation per concurrent upload. Acceptable for the
    current scale — switch to multipart S3 streaming when uploads get larger
    or hotter.
    """
    buf = BytesIO()
    size = 0
    chunk_size = 1024 * 1024  # 1 MiB
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise ValidationAppError(
                f"File exceeds maximum size of {max_bytes} bytes",
                code="file_too_large",
                details={"max_bytes": max_bytes},
            )
        buf.write(chunk)
    buf.seek(0)
    return buf, size


def _key(subdir: str, ext: str) -> str:
    unique = f"{uuid.uuid4().hex}{ext}"
    return f"{subdir.strip('/')}/{unique}"


# ---------- Local backend ----------


async def _save_local(buf: BytesIO, key: str) -> None:
    media_root = Path(settings.MEDIA_ROOT)
    target = media_root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, buf.getvalue())


# ---------- S3 backend ----------


def _ensure_s3_configured() -> None:
    missing = [
        n
        for n, v in (
            ("AWS_ACCESS_KEY_ID", settings.AWS_ACCESS_KEY_ID),
            ("AWS_SECRET_ACCESS_KEY", settings.AWS_SECRET_ACCESS_KEY),
            ("AWS_REGION", settings.AWS_REGION),
            ("AWS_S3_BUCKET", settings.AWS_S3_BUCKET),
        )
        if not v
    ]
    if missing:
        raise AppError(
            f"S3 storage is not configured: missing {', '.join(missing)}",
            code="storage_not_configured",
        )


def _s3_client():
    import boto3
    from botocore.config import Config

    # Force the regional endpoint + SigV4 + virtual-host style. Without this,
    # boto3 may presign against the global ``s3.amazonaws.com`` host; on fetch,
    # S3 redirects (307) to the regional host and the signature breaks.
    #
    # Tighter-than-default timeouts so a stalled S3 socket fails fast instead
    # of holding an in-flight streaming response open for the full default
    # 60 s — that's the failure mode that bubbled up as
    # ``ReadTimeoutError`` mid-segment when the local cache was missing.
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
        endpoint_url=f"https://s3.{settings.AWS_REGION}.amazonaws.com",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
            connect_timeout=5,
            read_timeout=15,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _s3_presigned_url(key: str) -> str:
    client = _s3_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.AWS_S3_BUCKET, "Key": key},
        ExpiresIn=settings.AWS_S3_URL_TTL_SECONDS,
    )


async def _save_s3(buf: BytesIO, key: str, content_type: str) -> None:
    _ensure_s3_configured()

    def _put() -> None:
        client = _s3_client()
        client.put_object(
            Bucket=settings.AWS_S3_BUCKET,
            Key=key,
            Body=buf.getvalue(),
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    try:
        await asyncio.to_thread(_put)
    except Exception as exc:  # noqa: BLE001
        logger.exception("s3_upload_failed", key=key)
        raise AppError(
            "Failed to upload to S3", code="storage_upload_failed"
        ) from exc


# ---------- Public API ----------


async def save_upload(
    upload: UploadFile,
    *,
    kind: str,
    subdir: str,
) -> tuple[str, int]:
    """Persist ``upload`` and return ``(storage_key, size_bytes)``.

    ``kind`` is one of ``video``, ``image``, ``document`` and controls the
    accepted extensions and size cap. The destination (local disk vs S3) is
    chosen by ``settings.STORAGE_BACKEND``.

    The returned ``storage_key`` is the **opaque storage reference**, not a
    URL — pass it to :func:`media_url` to get a fresh URL each time it's
    served. The same string is what should be persisted in the DB.
    """
    allowed_exts, max_bytes = _kind_config(kind)

    original_name = _sanitize(upload.filename or "file")
    ext = Path(original_name).suffix.lower()
    if ext not in allowed_exts:
        raise ValidationAppError(
            f"Unsupported file type '{ext or '(none)'}' for {kind}",
            code="invalid_file_type",
            details={"allowed": sorted(allowed_exts)},
        )

    try:
        buf, size = await _read_validated(upload, max_bytes=max_bytes)
    finally:
        await upload.close()

    key = _key(subdir, ext)
    content_type = upload.content_type or CONTENT_TYPES.get(ext, "application/octet-stream")

    if settings.STORAGE_BACKEND == "s3":
        await _save_s3(buf, key, content_type)
        # Dual-write: keep a copy on the local box so the streaming proxy can
        # serve from disk first and only fall back to S3 on a miss.
        if settings.STORAGE_DUAL_WRITE:
            try:
                await _save_local(buf, key)
            except Exception:  # noqa: BLE001
                logger.exception("dual_write_local_failed", key=key)
    else:
        await _save_local(buf, key)
    return key, size


# ---------- Streaming reads (server-first, S3 fallback) ----------


def _local_path(key: str) -> Path:
    return Path(settings.MEDIA_ROOT) / key


def _local_size(key: str) -> int | None:
    p = _local_path(key)
    if not p.is_file():
        return None
    try:
        return p.stat().st_size
    except OSError:
        return None


def _s3_head(key: str) -> dict | None:
    if settings.STORAGE_BACKEND != "s3":
        return None
    try:
        return _s3_client().head_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
    except Exception:  # noqa: BLE001
        return None


def stat_object(key: str) -> tuple[int, str] | None:
    """Return (size_bytes, content_type) for ``key`` — local first, then S3.

    Returns ``None`` if the object doesn't exist anywhere.
    """
    size = _local_size(key)
    if size is not None:
        ext = Path(key).suffix.lower()
        return size, CONTENT_TYPES.get(ext, "application/octet-stream")
    head = _s3_head(key)
    if head is not None:
        return int(head["ContentLength"]), head.get("ContentType") or "application/octet-stream"
    return None


def _iter_local(path: Path, start: int, end: int, chunk: int = 1024 * 1024):
    with path.open("rb") as fh:
        fh.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _iter_s3(key: str, start: int, end: int, chunk: int = 1024 * 1024):
    """Stream ``[start, end]`` of ``key`` from S3 with one mid-stream resume.

    boto3's built-in retry config only covers the initial GET — once we're
    pulling chunks off ``Body``, a socket-level ``ReadTimeoutError`` would
    abort the streaming response. We catch one such failure and resume the
    download with a fresh ``Range:`` request starting at the next unread byte.
    """
    from botocore.exceptions import ReadTimeoutError as BotoReadTimeoutError

    client = _s3_client()
    cursor = start
    attempts = 0
    while cursor <= end:
        resp = client.get_object(
            Bucket=settings.AWS_S3_BUCKET,
            Key=key,
            Range=f"bytes={cursor}-{end}",
        )
        body = resp["Body"]
        try:
            while True:
                try:
                    data = body.read(chunk)
                except BotoReadTimeoutError:
                    if attempts >= 1:
                        logger.exception("s3_stream_timeout_giveup", key=key, cursor=cursor)
                        raise
                    attempts += 1
                    logger.warning("s3_stream_timeout_retry", key=key, cursor=cursor)
                    break  # break inner loop to re-issue with new Range
                if not data:
                    return
                cursor += len(data)
                yield data
            # If we get here via the timeout-break, fall through to retry.
        finally:
            body.close()


def open_range(key: str, start: int, end: int):
    """Yield bytes for ``key`` in ``[start, end]`` — local disk first, then S3.

    Caller is responsible for clamping ``start``/``end`` to the object size
    (use :func:`stat_object` first).
    """
    p = _local_path(key)
    if p.is_file():
        return _iter_local(p, start, end)
    if settings.STORAGE_BACKEND == "s3":
        # Lazy import to avoid a metrics dep on the storage layer at module
        # import time (storage is also used by scripts that don't run FastAPI).
        from app.core.metrics import s3_stream_fallback_total

        s3_stream_fallback_total.inc()
        return _iter_s3(key, start, end)
    raise FileNotFoundError(key)


def read_object(key: str) -> bytes | None:
    """Fetch the full object as bytes — local first, then S3."""
    p = _local_path(key)
    if p.is_file():
        return p.read_bytes()
    if settings.STORAGE_BACKEND == "s3":
        try:
            resp = _s3_client().get_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
            return resp["Body"].read()
        except Exception:  # noqa: BLE001
            return None
    return None


def write_object(key: str, data: bytes, content_type: str | None = None) -> None:
    """Persist raw ``data`` at ``key`` — same dual-write rules as save_upload.

    Used by the HLS packager for segments / manifests / key files generated
    server-side after upload.
    """
    ext = Path(key).suffix.lower()
    ct = content_type or CONTENT_TYPES.get(ext, "application/octet-stream")
    if settings.STORAGE_BACKEND == "s3":
        client = _s3_client()
        client.put_object(
            Bucket=settings.AWS_S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=ct,
        )
        if settings.STORAGE_DUAL_WRITE:
            target = _local_path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    else:
        target = _local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def media_url(value: str | None) -> str | None:
    """Resolve a stored media reference to a URL the client can fetch.

    * ``None`` / empty → ``None``.
    * Already an absolute URL (``http://`` / ``https://``) → returned as-is so
      external URLs (e.g. Gravatar, social-OAuth avatars) keep working.
    * A storage key under the local backend → ``{MEDIA_URL}/{key}``.
    * A storage key under the S3 backend → a fresh presigned GET URL, or a
      ``{AWS_S3_PUBLIC_BASE_URL}/{key}`` link when a CDN is configured.
    """
    if not value:
        return None
    if value.startswith(("http://", "https://", "//")):
        return value
    if settings.STORAGE_BACKEND == "s3":
        if settings.AWS_S3_PUBLIC_BASE_URL:
            return f"{settings.AWS_S3_PUBLIC_BASE_URL.rstrip('/')}/{value}"
        return _s3_presigned_url(value)
    return f"{settings.MEDIA_URL.rstrip('/')}/{value}"
