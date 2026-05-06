from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPKMixin
from app.models.course import Course
from app.models.program import Program
from app.models.user import User


class Certificate(UUIDPKMixin, Base):
    __tablename__ = "certificates"
    __table_args__ = (
        CheckConstraint(
            "(course_id IS NOT NULL) OR (program_id IS NOT NULL)",
            name="certificate_target_present",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL"), index=True
    )
    serial_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(String(500))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship()
    course: Mapped[Course | None] = relationship()
    program: Mapped[Program | None] = relationship()