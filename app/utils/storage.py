"""Local media storage helper for instructor uploads.

Files are written under ``settings.MEDIA_ROOT`` and exposed as URLs prefixed
with ``settings.MEDIA_URL``. Swapping this out for S3/GCS later only requires
replacing :func:`save_upload` — the rest of the app deals in URLs.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Final

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import ValidationAppError

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Conservative defaults; tune via env if needed.
MAX_VIDEO_BYTES: Final[int] = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_IMAGE_BYTES: Final[int] = 20 * 1024 * 1024  # 20 MB
MAX_DOCUMENT_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DOCUMENT_EXTS = {".pdf", ".zip", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".csv"}


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


async def save_upload(
    upload: UploadFile,
    *,
    kind: str,
    subdir: str,
) -> tuple[str, int]:
    """Persist ``upload`` under ``MEDIA_ROOT/subdir`` and return ``(url, size_bytes)``.

    ``kind`` is one of ``video``, ``image``, ``document`` and controls the
    accepted extensions and size cap.
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

    media_root = Path(settings.MEDIA_ROOT)
    target_dir = media_root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    unique = f"{uuid.uuid4().hex}{ext}"
    target_path = target_dir / unique

    size = 0
    chunk_size = 1024 * 1024  # 1 MiB

    def _open() -> object:
        return target_path.open("wb")

    f = await asyncio.to_thread(_open)
    try:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                await asyncio.to_thread(f.close)
                await asyncio.to_thread(target_path.unlink, missing_ok=True)
                raise ValidationAppError(
                    f"File exceeds maximum size of {max_bytes} bytes",
                    code="file_too_large",
                    details={"max_bytes": max_bytes},
                )
            await asyncio.to_thread(f.write, chunk)
    finally:
        await asyncio.to_thread(f.close)
        await upload.close()

    rel = f"{subdir.strip('/')}/{unique}"
    url = f"{settings.MEDIA_URL.rstrip('/')}/{rel}"
    return url, size
