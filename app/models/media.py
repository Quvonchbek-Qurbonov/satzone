"""Models for protected video streaming.

:class:`MediaKey` stores the Fernet-wrapped AES-128 content key used to
encrypt a lesson's HLS segments. The key never leaves the backend in plain
form — it is decrypted in memory only when serving the per-lesson
``GET /lessons/{id}/hls/key`` endpoint to an authenticated, enrolled user.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class MediaKey(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "media_keys"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
