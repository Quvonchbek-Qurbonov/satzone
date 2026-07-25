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
import re
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


def _ffprobe_fields(source: Path, stream: str, fields: list[str]) -> dict[str, str]:
    """Return the requested ``stream`` entry ``fields`` for ``source``.

    Keys map to ffprobe's ``key=value`` output (lower-cased values). Missing
    keys / a failed probe yield an empty dict, which the caller treats as
    "unknown → don't risk a stream-copy".
    """
    proc = subprocess.run(
        [
            settings.FFPROBE_BIN,
            "-v", "error",
            "-select_streams", stream,
            "-show_entries", f"stream={','.join(fields)}",
            "-of", "default=noprint_wrappers=1",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip().lower()
    return out


def _can_stream_copy(source: Path) -> bool:
    """True when the source can be segmented without re-encoding.

    Stream-copy is the fast path, but it ships the raw bitstream straight to
    the player — so we only take it when that bitstream is one every browser
    can decode. ``codec_name == h264`` alone is not enough: a High 10 / 4:4:4 /
    10-bit source is still "h264" but fails to play in a ``<video>`` tag, and a
    copy of it would package cleanly yet stall on playback. We additionally
    require a browser-safe profile and pixel format; anything else (or a
    missing/failed probe) falls back to a normalising transcode.

    Non-uniform segment lengths are *not* a reason to refuse the copy — the
    anti-seek gate reads real per-segment durations, so it no longer depends
    on keyframe-aligned 6s segments.
    """
    if shutil.which(settings.FFPROBE_BIN) is None:
        logger.warning("ffprobe_missing", bin=settings.FFPROBE_BIN)
        return False

    video = _ffprobe_fields(source, "v:0", ["codec_name", "profile", "pix_fmt"])
    vcodec = video.get("codec_name")
    if vcodec is None or vcodec not in settings.HLS_COPY_VIDEO_CODECS:
        return False
    profile = video.get("profile", "")
    if profile not in {p.lower() for p in settings.HLS_COPY_VIDEO_PROFILES}:
        logger.info("hls_copy_reject_profile", profile=profile, pix_fmt=video.get("pix_fmt"))
        return False
    if video.get("pix_fmt") not in {p.lower() for p in settings.HLS_COPY_PIX_FMTS}:
        logger.info("hls_copy_reject_pix_fmt", pix_fmt=video.get("pix_fmt"))
        return False

    audio = _ffprobe_fields(source, "a:0", ["codec_name"])
    acodec = audio.get("codec_name")
    if acodec is not None and acodec not in settings.HLS_COPY_AUDIO_CODECS:
        return False
    return True


def _run_ffmpeg(source: Path, workdir: Path, key_info: Path, *, copy: bool) -> None:
    out_manifest = workdir / "master.m3u8"
    seg_template = workdir / "seg_%04d.ts"
    seg_seconds = settings.HLS_SEGMENT_SECONDS
    if copy:
        # Remux only — no frame re-compression. Segments split at the source's
        # existing keyframes nearest each ``hls_time`` boundary. This is the
        # fast path (seconds vs minutes) for already-H.264/AAC uploads.
        #
        # ``-avoid_negative_ts make_zero`` rebases timestamps to start at zero:
        # MP4 sources with edit lists / non-zero start PTS otherwise carry
        # negative or discontinuous DTS into the MPEG-TS segments, which the
        # player rejects mid-stream (segments download but fail to decode).
        codec_args = ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    else:
        # Full transcode → guaranteed MSE-safe HLS.
        #  * -fps_mode cfr : force constant frame rate so segment timestamps
        #    stay contiguous across boundaries (VFR sources break MSE).
        #    On ffmpeg < 5.1 use ["-vsync", "cfr"] instead.
        #  * -force_key_frames at each segment boundary → libx264 emits an IDR
        #    there, so every .ts is independently decodable (open-GOP sources
        #    otherwise produce non-IDR segment starts that MSE rejects) and each
        #    ``.ts`` is exactly ``seg_seconds`` long.
        #  * -avoid_negative_ts make_zero : rebase timestamps to start at zero
        #    (covers edit-list / non-zero-start-PTS sources).
        #  * audio normalised to stereo 48 kHz AAC-LC.
        codec_args = [
            "-c:v", "libx264",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "20",
            "-fps_mode", "cfr",
            "-force_key_frames", f"expr:gte(t,n_forced*{seg_seconds})",
            "-avoid_negative_ts", "make_zero",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-ac", "2",
        ]
    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-i", str(source),
        *codec_args,
        "-hls_time", str(seg_seconds),
        "-hls_playlist_type", "vod",
        "-hls_segment_type", "mpegts",
        "-hls_key_info_file", str(key_info),
        "-hls_segment_filename", str(seg_template),
        str(out_manifest),
    ]
    logger.info("ffmpeg_start", mode="copy" if copy else "transcode", cmd=" ".join(cmd))
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
            seg_count, seg_durations = await asyncio.to_thread(
                _run_packaging, lesson_id, source_bytes, plaintext_key
            )
            lesson.hls_master_key = f"lessons/{lesson_id}/hls/master.m3u8"
            lesson.hls_segments_count = seg_count
            lesson.hls_segment_durations = seg_durations or None
            lesson.hls_status = HlsStatus.READY
            await session.commit()
            hls_packaging_total.labels(outcome="ready").inc()
            logger.info("hls_ready", lesson_id=str(lesson_id), segments=seg_count)
        except Exception:  # noqa: BLE001
            logger.exception("hls_packaging_failed", lesson_id=str(lesson_id))
            lesson.hls_status = HlsStatus.FAILED
            await session.commit()
            hls_packaging_total.labels(outcome="failed").inc()


_EXTINF_RE = re.compile(r"^#EXTINF:([0-9]+(?:\.[0-9]+)?)")
_SEG_LINE_RE = re.compile(r"^seg_(\d+)\.ts$")


def _parse_segment_durations(manifest_text: str) -> list[float]:
    """Extract per-segment durations (seconds) from a VOD media playlist.

    Each segment is introduced by an ``#EXTINF:<dur>,`` line immediately
    followed by its ``seg_NNNN.ts`` URI. We key durations by the segment index
    in the filename (not merely appearance order) so the returned list is
    positionally aligned with segment indices even if ffmpeg ever skips one.
    Returns ``[]`` if nothing parses, letting the gate fall back to uniform
    segment lengths.
    """
    by_index: dict[int, float] = {}
    pending: float | None = None
    for raw in manifest_text.splitlines():
        line = raw.strip()
        m = _EXTINF_RE.match(line)
        if m:
            pending = float(m.group(1))
            continue
        seg = _SEG_LINE_RE.match(line)
        if seg and pending is not None:
            by_index[int(seg.group(1))] = pending
            pending = None
    if not by_index:
        return []
    return [by_index.get(i, float(settings.HLS_SEGMENT_SECONDS)) for i in range(max(by_index) + 1)]


def _run_packaging(
    lesson_id: uuid.UUID, source_bytes: bytes, key_bytes: bytes
) -> tuple[int, list[float]]:
    """Sync helper — runs ffmpeg in a temp dir, then ships outputs to storage.

    Returns ``(segment_count, per_segment_durations)``. The caller persists
    both on the Lesson row: the count so the anti-seek gate knows the final
    segment index, the durations so it can gate against the real timeline
    (stream-copy segments are non-uniform).

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

        # Fast path: if the source is already H.264/AAC, segment by stream-copy
        # (seconds). Otherwise transcode. If copy fails mid-way (odd container /
        # bitstream), fall back to a transcode so the upload still succeeds.
        use_copy = settings.HLS_STREAM_COPY_ENABLED and _can_stream_copy(source)
        try:
            _run_ffmpeg(source, workdir, key_info, copy=use_copy)
        except RuntimeError:
            if not use_copy:
                raise
            logger.warning("hls_copy_failed_retry_transcode", lesson_id=str(lesson_id))
            for stale in workdir.glob("seg_*.ts"):
                stale.unlink(missing_ok=True)
            (workdir / "master.m3u8").unlink(missing_ok=True)
            _run_ffmpeg(source, workdir, key_info, copy=False)

        manifest_path = workdir / "master.m3u8"
        durations = (
            _parse_segment_durations(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else []
        )

        prefix = f"lessons/{lesson_id}/hls"
        seg_count = 0
        for path in sorted(workdir.iterdir()):
            if path.name in ("source.bin", "content.key", "key.info"):
                continue
            data = path.read_bytes()
            write_object(f"{prefix}/{path.name}", data)
            if path.name.startswith("seg_") and path.name.endswith(".ts"):
                seg_count += 1
        return seg_count, durations
