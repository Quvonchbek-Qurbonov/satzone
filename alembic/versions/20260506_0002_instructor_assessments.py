"""instructor user link and assessments

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


QUESTION_TYPE = postgresql.ENUM(
    "single_choice",
    "multi_choice",
    "true_false",
    "short_answer",
    name="question_type",
)
ASSESSMENT_STATUS = postgresql.ENUM(
    "draft", "published", "archived", name="assessment_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    QUESTION_TYPE.create(bind, checkfirst=True)
    ASSESSMENT_STATUS.create(bind, checkfirst=True)

    # Link Instructor → User (nullable so legacy seed data keeps working).
    op.add_column(
        "instructors",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_instructors_user_id_users",
        "instructors",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_instructors_user_id", "instructors", ["user_id"], unique=True
    )

    op.create_table(
        "assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_sections.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("instructions", sa.Text()),
        sa.Column("time_limit_minutes", sa.Integer()),
        sa.Column("pass_percent", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("max_attempts", sa.Integer()),
        sa.Column(
            "shuffle_questions", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "show_correct_answers",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="assessment_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "pass_percent BETWEEN 0 AND 100", name="ck_assessments_pass_percent_range"
        ),
        sa.CheckConstraint(
            "max_attempts IS NULL OR max_attempts > 0",
            name="ck_assessments_max_attempts_positive",
        ),
    )
    op.create_index("ix_assessments_course_id", "assessments", ["course_id"])
    op.create_index("ix_assessments_section_id", "assessments", ["section_id"])
    op.create_index("ix_assessments_status", "assessments", ["status"])

    op.create_table(
        "assessment_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(name="question_type", create_type=False),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text()),
        sa.Column("points", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_answers", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "assessment_id", "order", name="uq_question_assessment_order"
        ),
        sa.CheckConstraint(
            "points >= 0", name="ck_assessment_questions_question_points_non_negative"
        ),
    )
    op.create_index(
        "ix_assessment_questions_assessment_id",
        "assessment_questions",
        ["assessment_id"],
    )

    op.create_table(
        "assessment_question_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "is_correct", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("question_id", "order", name="uq_option_question_order"),
    )
    op.create_index(
        "ix_assessment_question_options_question_id",
        "assessment_question_options",
        ["question_id"],
    )

    op.create_table(
        "assessment_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_number", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("score_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "score_percent BETWEEN 0 AND 100",
            name="ck_assessment_submissions_submission_score_range",
        ),
    )
    op.create_index(
        "ix_assessment_submissions_assessment_id",
        "assessment_submissions",
        ["assessment_id"],
    )
    op.create_index(
        "ix_assessment_submissions_user_id",
        "assessment_submissions",
        ["user_id"],
    )

    op.create_table(
        "assessment_submission_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response", postgresql.JSONB()),
        sa.Column(
            "is_correct", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "awarded_points", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.UniqueConstraint(
            "submission_id", "question_id", name="uq_submission_answer_question"
        ),
    )
    op.create_index(
        "ix_assessment_submission_answers_submission_id",
        "assessment_submission_answers",
        ["submission_id"],
    )
    op.create_index(
        "ix_assessment_submission_answers_question_id",
        "assessment_submission_answers",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_table("assessment_submission_answers")
    op.drop_table("assessment_submissions")
    op.drop_table("assessment_question_options")
    op.drop_table("assessment_questions")
    op.drop_table("assessments")

    op.drop_index("ix_instructors_user_id", table_name="instructors")
    op.drop_constraint(
        "fk_instructors_user_id_users", "instructors", type_="foreignkey"
    )
    op.drop_column("instructors", "user_id")

    bind = op.get_bind()
    ASSESSMENT_STATUS.drop(bind, checkfirst=True)
    QUESTION_TYPE.drop(bind, checkfirst=True)
