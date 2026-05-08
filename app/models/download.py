"""Lesson resource attachments + per-user "saved for offline" records.

A lesson can carry multiple downloadable files (PDFs, slides, code zips, ...).
Videos are *not* downloadable — those go through the HLS+AES streaming
pipeline. ``UserResourceDownload`` is just a saved-for-offline marker so the
``GET /me/downloads`` view (My Learning → Download) can list what the user
has flagged. The actual file URL is fetched fresh each time the user wants
to download (it may be a presigned S3 URL with TTL).
"""
from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class LessonAttachment(UUIDPKMixin, TimestampMixin, Base):
    """One downloadable file attached to a lesson."""

    __tablename__ = "lesson_attachments"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Storage key (resolved to a fresh URL at serialize time).
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(120))


class UserResourceDownload(UUIDPKMixin, TimestampMixin, Base):
    """User has flagged this attachment as "saved for offline" on a device."""

    __tablename__ = "user_resource_downloads"
    __table_args__ = (
        UniqueConstraint("user_id", "attachment_id", name="uq_user_attachment"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lesson_attachments.id", ondelete="CASCADE"), index=True, nullable=False
    )
