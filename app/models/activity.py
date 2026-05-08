"""Daily learning-activity rollups for the home weekly chart.

One row per (user, date). Lesson-progress writes upsert into this table so
the home screen can render minutes-learned per day without a heavy
aggregation query at read time.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class DailyActivity(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "daily_activity"
    __table_args__ = (
        UniqueConstraint("user_id", "activity_date", name="uq_daily_activity_user_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    activity_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    minutes_learned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lessons_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
