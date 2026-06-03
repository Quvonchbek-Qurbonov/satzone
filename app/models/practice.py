from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import PracticeItemType

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


practice_item_type_enum = PgEnum(
    PracticeItemType,
    name="practice_item_type",
    create_type=False,
    values_callable=lambda x: [e.value for e in x],
)


class PracticePack(UUIDPKMixin, TimestampMixin, Base):
    """One bundle of practice quizzes per course.

    Auto-created the first time an instructor adds a quiz to a course, so the
    1:1 with `courses` is enforced by a unique constraint on `course_id`
    rather than by mirroring course creation.
    """

    __tablename__ = "practice_packs"
    __table_args__ = (
        UniqueConstraint("course_id", name="uq_practice_packs_course_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    course: Mapped["Course"] = relationship()
    quizzes: Mapped[list["PracticeQuiz"]] = relationship(
        back_populates="pack",
        cascade="all, delete-orphan",
        order_by="PracticeQuiz.order",
    )


class PracticeQuiz(UUIDPKMixin, TimestampMixin, Base):
    """A Duolingo-style mini-lesson inside a pack.

    `order` establishes the linear path the student walks. Items per quiz are
    capped at 50 in the service layer (no DB constraint — keeps inserts cheap).
    `is_published` lets instructors stage edits without exposing them.
    """

    __tablename__ = "practice_quizzes"
    __table_args__ = (
        UniqueConstraint("pack_id", "order", name="uq_practice_quizzes_pack_id_order"),
    )

    pack_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_packs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    pack: Mapped[PracticePack] = relationship(back_populates="quizzes")
    items: Mapped[list["PracticeItem"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="PracticeItem.order",
    )


class PracticeItem(UUIDPKMixin, TimestampMixin, Base):
    """One question inside a quiz; payload shape depends on `type`.

    `data` is a JSONB blob whose schema is enforced by the service layer
    (see app.services.practice_service.validate_item_data). Keeping it in a
    single column avoids a 2× polymorphic table split for what is, in v1,
    only two item types.

    MCQ::

        {
          "prompt": "Tap the apple",
          "image_url": null,
          "options": [
            {"id": "a", "text": "Apple", "image_url": null, "is_correct": true},
            {"id": "b", "text": "Banana", "image_url": null, "is_correct": false}
          ]
        }

    MATCHING::

        {
          "prompt": "Match the English word to its French translation",
          "pairs": [
            {"id": "p1", "left": "Apple", "right": "Pomme"},
            {"id": "p2", "left": "Bread", "right": "Pain"}
          ]
        }
    """

    __tablename__ = "practice_items"
    __table_args__ = (
        UniqueConstraint("quiz_id", "order", name="uq_practice_items_quiz_id_order"),
        CheckConstraint("points >= 0", name="ck_practice_items_points_non_negative"),
    )

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_quizzes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[PracticeItemType] = mapped_column(practice_item_type_enum, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    quiz: Mapped[PracticeQuiz] = relationship(back_populates="items")


class PracticeAttempt(UUIDPKMixin, TimestampMixin, Base):
    """One full play-through of a quiz by a user.

    Attempts are unlimited; `best_score_percent` is derived at read time via
    MAX over this table. We persist every attempt (rather than just the best)
    so analytics can track learning curves later without a backfill.

    `answers` is a JSON list — one entry per item — each shaped as
    `{"item_id": ..., "response": ..., "is_correct": bool}`. Response shape
    depends on the item type:

        MCQ      → {"option_id": "<id>"}
        MATCHING → {"pairs": [{"left_id": "<id>", "right_id": "<id>"}, ...]}
    """

    __tablename__ = "practice_attempts"
    __table_args__ = (
        CheckConstraint(
            "score_percent BETWEEN 0 AND 100",
            name="ck_practice_attempts_score_percent_range",
        ),
    )

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_quizzes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    score_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answers: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)

    quiz: Mapped[PracticeQuiz] = relationship()
    user: Mapped["User"] = relationship()
