"""Section-quiz support: image fields on questions/options + section-quiz flag.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-10

Adds the schema bits needed for end-of-section gating quizzes:

* ``assessments.is_section_quiz`` flags the quiz that gates progression past
  its parent section. A partial unique index keeps that to one per section.
* ``assessment_questions.image_url`` and
  ``assessment_question_options.image_url`` carry storage keys for question /
  option images so quizzes can include diagrams or photos.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column(
            "is_section_quiz",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # One section-quiz per section; non-section-quizzes are unconstrained.
    op.create_index(
        "uq_assessments_section_quiz_per_section",
        "assessments",
        ["section_id"],
        unique=True,
        postgresql_where=sa.text("is_section_quiz = TRUE AND section_id IS NOT NULL"),
    )

    op.add_column(
        "assessment_questions",
        sa.Column("image_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "assessment_question_options",
        sa.Column("image_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assessment_question_options", "image_url")
    op.drop_column("assessment_questions", "image_url")
    op.drop_index(
        "uq_assessments_section_quiz_per_section", table_name="assessments"
    )
    op.drop_column("assessments", "is_section_quiz")
