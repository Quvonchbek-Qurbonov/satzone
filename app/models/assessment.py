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
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import AssessmentStatus, QuestionType

if TYPE_CHECKING:
    from app.models.course import Course, CourseSection
    from app.models.user import User


question_type_enum = PgEnum(
    QuestionType,
    name="question_type",
    create_type=False,
    values_callable=lambda x: [e.value for e in x],
)
assessment_status_enum = PgEnum(
    AssessmentStatus,
    name="assessment_status",
    create_type=False,
    values_callable=lambda x: [e.value for e in x],
)


class Assessment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint("pass_percent BETWEEN 0 AND 100", name="pass_percent_range"),
        CheckConstraint(
            "max_attempts IS NULL OR max_attempts > 0",
            name="max_attempts_positive",
        ),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("course_sections.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)
    pass_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    max_attempts: Mapped[int | None] = mapped_column(Integer)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_correct_answers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[AssessmentStatus] = mapped_column(
        assessment_status_enum, nullable=False, default=AssessmentStatus.DRAFT, index=True
    )

    course: Mapped["Course"] = relationship()
    section: Mapped["CourseSection | None"] = relationship()
    questions: Mapped[list["Question"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="Question.order",
    )
    submissions: Mapped[list["AssessmentSubmission"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class Question(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "assessment_questions"
    __table_args__ = (
        UniqueConstraint("assessment_id", "order", name="uq_question_assessment_order"),
        CheckConstraint("points >= 0", name="question_points_non_negative"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[QuestionType] = mapped_column(question_type_enum, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # For SHORT_ANSWER: list of accepted answers (case-insensitive match).
    expected_answers: Mapped[list[str] | None] = mapped_column(JSONB)

    assessment: Mapped[Assessment] = relationship(back_populates="questions")
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionOption.order",
    )


class QuestionOption(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "assessment_question_options"
    __table_args__ = (
        UniqueConstraint("question_id", "order", name="uq_option_question_order"),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    question: Mapped[Question] = relationship(back_populates="options")


class AssessmentSubmission(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "assessment_submissions"
    __table_args__ = (
        CheckConstraint("score_percent BETWEEN 0 AND 100", name="submission_score_range"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="submissions")
    user: Mapped["User"] = relationship()
    answers: Mapped[list["SubmissionAnswer"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class SubmissionAnswer(UUIDPKMixin, Base):
    __tablename__ = "assessment_submission_answers"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "question_id", name="uq_submission_answer_question"
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_submissions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # JSON-encoded selected option ids (list[str]) or short answer text.
    response: Mapped[dict | list | None] = mapped_column(JSONB)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    awarded_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    submission: Mapped[AssessmentSubmission] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
