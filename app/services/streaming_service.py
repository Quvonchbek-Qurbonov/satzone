"""Protected video streaming — token issuance, access checks, and KEK helpers.

The streaming endpoints (``/lessons/{id}/stream``, the HLS manifest, segments
and AES-128 key URL) accept a short-lived signed token in a ``?t=`` query
parameter. We use the query string rather than the ``Authorization`` header
so that HTML5 ``<video>`` and HLS players — which can't easily attach custom
headers to byte-range or segment fetches — can still play protected content.

The signing path:

* ``issue_playback_token`` returns a JWT scoped to a single ``(user_id,
  lesson_id, scope)`` tuple with a TTL pulled from settings.
* ``verify_playback_token`` re-authenticates that token on each segment /
  range / key request. The returned context lets the route enforce that the
  caller is requesting *their* token for *this* lesson — substituting another
  user's token or another lesson's token fails verification.

Per-lesson AES-128 keys are wrapped at rest with a Fernet master key
(``settings.MEDIA_KEK``). Plaintext content keys exist only for the duration
of an authorized key-fetch request.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.models.course import Course, CourseSection, Lesson
from app.models.enrollment import Enrollment
from app.models.enums import PublishStatus, UserRole
from app.models.media import MediaKey
from app.models.user import User

PlaybackScope = Literal["lesson", "course_preview"]


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------- Token issue / verify ----------


def request_client_ip(request) -> str:
    """Best-effort client IP. Honours ``X-Forwarded-For`` so the API works
    behind a reverse proxy; in dev it falls back to the socket peer.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def issue_playback_token(
    *,
    user_id: uuid.UUID,
    resource_id: uuid.UUID,
    scope: PlaybackScope,
    client_ip: str,
    ttl_seconds: int | None = None,
) -> tuple[str, datetime]:
    expire = _now() + timedelta(seconds=ttl_seconds or settings.STREAM_TOKEN_TTL_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "rid": str(resource_id),
        "scope": scope,
        "cip": client_ip,
        "type": "playback",
        "iat": int(_now().timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expire


def verify_playback_token(
    token: str,
    *,
    expected_resource_id: uuid.UUID,
    expected_scope: PlaybackScope,
    expected_client_ip: str,
) -> uuid.UUID:
    """Validate ``token`` and return the user id baked into it.

    Raises :class:`UnauthorizedError` if the token is missing/expired/forged,
    doesn't match the requested resource/scope, or was minted for a different
    client IP. Tokens are non-transferable across networks.
    """
    # Lazy import — keeps streaming_service usable from scripts that don't
    # boot the FastAPI app (and thus don't register the Prometheus collectors).
    from app.core.metrics import playback_token_rejections_total

    def _reject(reason: str, message: str) -> UnauthorizedError:
        playback_token_rejections_total.labels(reason=reason).inc()
        return UnauthorizedError(message, code=reason)

    if not token:
        raise _reject("missing_playback_token", "Missing playback token")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise _reject("playback_token_expired", "Playback token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _reject("invalid_playback_token", "Invalid playback token") from exc
    if payload.get("type") != "playback":
        raise _reject("invalid_playback_token", "Wrong token type")
    if payload.get("scope") != expected_scope:
        raise _reject("playback_scope_mismatch", "Token scope mismatch")
    if payload.get("rid") != str(expected_resource_id):
        raise _reject("playback_resource_mismatch", "Token resource mismatch")
    if payload.get("cip") != expected_client_ip:
        raise _reject("playback_ip_mismatch", "Token bound to a different IP")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _reject("invalid_playback_token", "Invalid token subject") from exc


# ---------- Access checks ----------


async def authorize_lesson_playback(
    session: AsyncSession,
    user: User,
    lesson_id: uuid.UUID,
) -> Lesson:
    """Return ``lesson`` if ``user`` is allowed to play it.

    Allowed when any of:

    * the lesson is marked ``is_free_preview`` and the parent course is
      published,
    * the user is enrolled in the course,
    * the user owns the course (instructor) or is an admin.
    """
    stmt = (
        select(Lesson, CourseSection, Course)
        .join(CourseSection, CourseSection.id == Lesson.section_id)
        .join(Course, Course.id == CourseSection.course_id)
        .where(Lesson.id == lesson_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFoundError("Lesson not found", code="lesson_not_found")
    lesson, _section, course = row

    if user.role == UserRole.ADMIN:
        return lesson

    from app.models.catalog import Instructor

    owner_user_id = (
        await session.execute(
            select(Instructor.user_id).where(Instructor.id == course.instructor_id)
        )
    ).scalar_one_or_none()
    if owner_user_id is not None and owner_user_id == user.id:
        return lesson

    if lesson.is_free_preview and course.status == PublishStatus.PUBLISHED:
        return lesson

    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course.id
            )
        )
    ).first()
    if enrolled is None:
        raise ForbiddenError(
            "Enroll in this course to watch the lesson",
            code="not_enrolled",
        )
    return lesson


async def authorize_course_preview(
    session: AsyncSession, user: User | None, course_id: uuid.UUID
) -> Course:
    """Course preview videos are openable by any authenticated user when the
    course is published; admins/owners can preview unpublished drafts.
    """
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    if course.status == PublishStatus.PUBLISHED:
        return course
    if user is None:
        raise ForbiddenError("Course preview not available", code="course_not_published")
    if user.role == UserRole.ADMIN:
        return course
    from app.models.catalog import Instructor

    owner_user_id = (
        await session.execute(
            select(Instructor.user_id).where(Instructor.id == course.instructor_id)
        )
    ).scalar_one_or_none()
    if owner_user_id == user.id:
        return course
    raise ForbiddenError("Course preview not available", code="course_not_published")


# ---------- KEK (Fernet) helpers ----------


def _fernet() -> Fernet:
    if not settings.MEDIA_KEK:
        raise RuntimeError(
            "MEDIA_KEK is not configured — generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and set it in .env"
        )
    return Fernet(settings.MEDIA_KEK.encode("utf-8"))


def wrap_content_key(plain: bytes) -> bytes:
    return _fernet().encrypt(plain)


def unwrap_content_key(wrapped: bytes) -> bytes:
    try:
        return _fernet().decrypt(wrapped)
    except InvalidToken as exc:
        raise RuntimeError("Failed to unwrap content key — KEK rotated or wrong?") from exc


def generate_content_key() -> bytes:
    """Fresh 16-byte AES-128 content key."""
    return os.urandom(16)


async def get_or_create_lesson_key(
    session: AsyncSession, lesson_id: uuid.UUID
) -> tuple[MediaKey, bytes]:
    """Return ``(record, plaintext_key)``; mints + persists if absent."""
    existing = (
        await session.execute(select(MediaKey).where(MediaKey.lesson_id == lesson_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, unwrap_content_key(existing.encrypted_key)
    plain = generate_content_key()
    record = MediaKey(lesson_id=lesson_id, encrypted_key=wrap_content_key(plain))
    session.add(record)
    await session.flush()
    return record, plain


async def get_lesson_key_plaintext(
    session: AsyncSession, lesson_id: uuid.UUID
) -> bytes | None:
    record = (
        await session.execute(select(MediaKey).where(MediaKey.lesson_id == lesson_id))
    ).scalar_one_or_none()
    if record is None:
        return None
    return unwrap_content_key(record.encrypted_key)
