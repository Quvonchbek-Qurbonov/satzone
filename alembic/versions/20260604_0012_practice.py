"""Practice quizzes: standalone Duolingo-style MCQ + matching drills.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-04

Adds the four tables and one enum that back the practice feature:

* ``practice_packs`` — one pack per course (1:1; unique on course_id).
* ``practice_quizzes`` — Duolingo "lesson" units, ordered within a pack.
* ``practice_items`` — MCQ or MATCHING questions, JSONB payload per item.
* ``practice_attempts`` — user × quiz play-throughs; score derived as MAX
  on read. Unlimited replays.

Separate from the ``assessments`` family on purpose: practice has no
pass/fail gating, no time limit, no attempt cap, and never blocks lesson
progression.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRACTICE_ITEM_TYPE = postgresql.ENUM("mcq", "matching", name="practice_item_type")


def upgrade() -> None:
    PRACTICE_ITEM_TYPE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "practice_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200)),
        sa.Column("description", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("course_id", name="uq_practice_packs_course_id"),
    )

    op.create_table(
        "practice_quizzes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practice_packs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("pack_id", "order", name="uq_practice_quizzes_pack_id_order"),
    )
    op.create_index("ix_practice_quizzes_pack_id", "practice_quizzes", ["pack_id"])

    op.create_table(
        "practice_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "quiz_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practice_quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(name="practice_item_type", create_type=False),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("quiz_id", "order", name="uq_practice_items_quiz_id_order"),
        sa.CheckConstraint("points >= 0", name="ck_practice_items_points_non_negative"),
    )
    op.create_index("ix_practice_items_quiz_id", "practice_items", ["quiz_id"])

    op.create_table(
        "practice_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "quiz_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practice_quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("score_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "score_percent BETWEEN 0 AND 100",
            name="ck_practice_attempts_score_percent_range",
        ),
    )
    op.create_index(
        "ix_practice_attempts_quiz_id_user_id",
        "practice_attempts",
        ["quiz_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_practice_attempts_quiz_id_user_id", table_name="practice_attempts")
    op.drop_table("practice_attempts")
    op.drop_index("ix_practice_items_quiz_id", table_name="practice_items")
    op.drop_table("practice_items")
    op.drop_index("ix_practice_quizzes_pack_id", table_name="practice_quizzes")
    op.drop_table("practice_quizzes")
    op.drop_table("practice_packs")
    PRACTICE_ITEM_TYPE.drop(op.get_bind(), checkfirst=True)
