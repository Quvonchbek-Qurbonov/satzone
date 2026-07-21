"""Landing-page statistics singleton

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-21

Adds ``landing_stats`` — a single-row table of hand-curated marketing figures
shown on the public landing page (student count, average score gain, practice
question count, top student SAT score). Admin-editable via ``PUT
/landing/stats``; publicly readable via ``GET /landing/stats``. One row is
seeded with zeros so the public read always returns a payload.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SINGLETON_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "landing_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "students_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "average_score_gain", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "practice_questions", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "top_student_sat_score", sa.Integer(), nullable=False, server_default="0"
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
            "students_count >= 0", name="ck_landing_stats_students_count_non_negative"
        ),
        sa.CheckConstraint(
            "average_score_gain >= 0",
            name="ck_landing_stats_average_score_gain_non_negative",
        ),
        sa.CheckConstraint(
            "practice_questions >= 0",
            name="ck_landing_stats_practice_questions_non_negative",
        ),
        sa.CheckConstraint(
            "top_student_sat_score >= 0",
            name="ck_landing_stats_top_student_sat_score_non_negative",
        ),
    )

    op.execute(
        sa.text(
            "INSERT INTO landing_stats (id) VALUES (CAST(:id AS uuid)) "
            "ON CONFLICT DO NOTHING"
        ).bindparams(id=_SINGLETON_ID)
    )


def downgrade() -> None:
    op.drop_table("landing_stats")
