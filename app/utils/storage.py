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
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
        endpoint_url=f"https://s3.{settings.AWS_REGION}.amazonaws.com",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
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
    else:
        await _save_local(buf, key)
    return key, size


def media_url(value: str | None) -> str | None:
    """Resolve a stored media reference to a URL the client can fetch.

    * ``None`` / empty → ``None``.
    * Already an absolute URL (``http://`` / ``https://``) → returned as-is so
      seeded data and external URLs (e.g. Gravatar, social-OAuth avatars)
      keep working without migration.
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
