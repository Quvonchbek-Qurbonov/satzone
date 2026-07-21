from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin

# The landing-page statistics live in a single, always-present row. Every
# read/write targets this fixed primary key so the table can never grow a
# second row — see ``app/api/v1/landing.py``.
SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class LandingStats(UUIDPKMixin, TimestampMixin, Base):
    """Hand-curated marketing figures shown on the public landing page.

    Not derived from live platform data — an admin edits them directly. Held
    as a singleton (one row, keyed by :data:`SINGLETON_ID`).
    """

    __tablename__ = "landing_stats"
    __table_args__ = (
        CheckConstraint(
            "students_count >= 0",
            name="ck_landing_stats_students_count_non_negative",
        ),
        CheckConstraint(
            "average_score_gain >= 0",
            name="ck_landing_stats_average_score_gain_non_negative",
        ),
        CheckConstraint(
            "practice_questions >= 0",
            name="ck_landing_stats_practice_questions_non_negative",
        ),
        CheckConstraint(
            "top_student_sat_score >= 0",
            name="ck_landing_stats_top_student_sat_score_non_negative",
        ),
    )

    students_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_score_gain: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    practice_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_student_sat_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
