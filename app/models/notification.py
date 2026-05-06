from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPKMixin
from app.models.enums import NotificationType
from app.models.user import User

notification_type_enum = PgEnum(
    NotificationType,
    name="notification_type",
    create_type=False,
    values_callable=lambda x: [e.value for e in x],
)


class Notification(UUIDPKMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(
        notification_type_enum, nullable=False, default=NotificationType.SYSTEM
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship()