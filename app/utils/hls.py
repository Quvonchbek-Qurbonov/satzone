"""HLS + AES-128 packaging.

We package the freshly uploaded source video into an HLS playlist with each
``.ts`` segment encrypted under a fresh per-lesson AES-128 content key. The
key itself is wrapped with the Fernet master key (``MEDIA_KEK``) and stored
in the ``media_keys`` table; the *plaintext* key is only ever served from
:func:`app.services.streaming_service.get_lesson_key_plaintext` to clients
holding a valid playback token.

Packaging runs synchronously inside a FastAPI ``BackgroundTasks`` callback
(see :func:`app.api.v1.instructor.upload_lesson_video`). For larger
deployments lift this into a real worker (arq, RQ, Celery) — the function
signature is intentionally side-effect-free apart from ``write_object`` and
the DB session it's handed.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    hls_packaging_duration_seconds,
    hls_packaging_in_flight,
    hls_packaging_total,
)
from app.db.session import SessionLocal
from app.models.course import Lesson
from app.models.enums import HlsStatus
from app.services.streaming_service import get_or_create_lesson_key
from app.utils.storage import read_object, write_object

logger = get_logger(__name__)


def _ffmpeg_available() -> bool:
    return shutil.which(settings.FFMPEG_BIN) is not None


def _key_info_file(workdir: Path, key_bytes: bytes, key_uri: str) -> Path:
    """Write the three-line ``key_info`` ffmpeg expects for ``-hls_key_info_file``.

    Layout:
        line 1 — URI written into the EXT-X-KEY tag (rewritten at serve time)
        line 2 — local path to the raw 16-byte key file
        line 3 — IV (optional; we let ffmpeg pick a per-segment IV by omitting)
    """
    key_path = workdir / "content.key"
    key_path.write_bytes(key_bytes)
    info = workdir / "key.info"
    info.write_text(f"{key_uri}\n{key_path}\n", encoding="utf-8")
    return info


def _run_ffmpeg(source: Path, workdir: Path, key_info: Path) -> None:
    out_manifest = workdir / "master.m3u8"
    seg_template = workdir / "seg_%04d.ts"
    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-i", str(source),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-hls_time", str(settings.HLS_SEGMENT_SECONDS),
        "-hls_playlist_type", "vod",
        "-hls_segment_type", "mpegts",
        "-hls_key_info_file", str(key_info),
        "-hls_segment_filename", str(seg_template),
        str(out_manifest),
    ]
    logger.info("ffmpeg_start", cmd=" ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("ffmpeg_failed", returncode=proc.returncode, stderr=proc.stderr[-2000:])
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {proc.stderr[-500:]}")


async def package_lesson_hls(lesson_id: uuid.UUID) -> None:
    """Package a lesson's source video into encrypted HLS.

    Runs in its own async session so it can be scheduled from a
    BackgroundTasks callback that has already committed the upload.
    """
    import time

    hls_packaging_in_flight.inc()
    started = time.monotonic()
    try:
        await _package_lesson_hls_impl(lesson_id)
    finally:
        hls_packaging_duration_seconds.observe(time.monotonic() - started)
        hls_packaging_in_flight.dec()


async def _package_lesson_hls_impl(lesson_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        lesson = await session.get(Lesson, lesson_id)
        if lesson is None or not lesson.video_url:
            logger.warning("hls_skip_no_source", lesson_id=str(lesson_id))
            return
        if not _ffmpeg_available():
            logger.error("hls_skip_ffmpeg_missing", bin=settings.FFMPEG_BIN)
            lesson.hls_status = HlsStatus.FAILED
            await session.commit()
            return

        lesson.hls_status = HlsStatus.PENDING
        await session.commit()

        # Mint or load the AES-128 content key (Fernet-wrapped at rest).
        _, plaintext_key = await get_or_create_lesson_key(session, lesson_id)
        await session.commit()

        source_bytes = read_object(lesson.video_url)
        if source_bytes is None:
            logger.error("hls_source_missing", key=lesson.video_url)
            lesson.hls_status = HlsStatus.FAILED
            await session.commit()
            return

        try:
            seg_count = await asyncio.to_thread(
                _run_packaging, lesson_id, source_bytes, plaintext_key
            )
            lesson.hls_master_key = f"lessons/{lesson_id}/hls/master.m3u8"
            lesson.hls_segments_count = seg_count
            lesson.hls_status = HlsStatus.READY
            await session.commit()
            hls_packaging_total.labels(outcome="ready").inc()
            logger.info("hls_ready", lesson_id=str(lesson_id), segments=seg_count)
        except Exception:  # noqa: BLE001
            logger.exception("hls_packaging_failed", lesson_id=str(lesson_id))
            lesson.hls_status = HlsStatus.FAILED
            await session.commit()
            hls_packaging_total.labels(outcome="failed").inc()


def _run_packaging(lesson_id: uuid.UUID, source_bytes: bytes, key_bytes: bytes) -> int:
    """Sync helper — runs ffmpeg in a temp dir, then ships outputs to storage.

    Returns the number of ``seg_*.ts`` segments produced; the caller persists
    that on the Lesson row so the anti-seek gate knows the final segment
    index.

    The manifest written by ffmpeg references segments by relative name and
    embeds the placeholder ``URI=`` we hand it; the streaming endpoint
    rewrites both at serve time so the player never gets a direct URL into
    storage.
    """
    with tempfile.TemporaryDirectory(prefix=f"hls_{lesson_id}_") as tmp:
        workdir = Path(tmp)
        source = workdir / "source.bin"
        source.write_bytes(source_bytes)

        # The URI we put on disk is a placeholder — the manifest endpoint
        # rewrites it to a signed URL on every request.
        key_info = _key_info_file(workdir, key_bytes, key_uri="placeholder://key")
        _run_ffmpeg(source, workdir, key_info)

        prefix = f"lessons/{lesson_id}/hls"
        seg_count = 0
        for path in sorted(workdir.iterdir()):
            if path.name in ("source.bin", "content.key", "key.info"):
                continue
            data = path.read_bytes()
            write_object(f"{prefix}/{path.name}", data)
            if path.name.startswith("seg_") and path.name.endswith(".ts"):
                seg_count += 1
        return seg_count
