"""Anti-seek / max-2x playback gating columns.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-09

Adds the state needed to enforce "no skipping ahead, max 2x playback speed"
purely from segment-fetch signals (no JS heartbeat).

* ``lessons.hls_segments_count`` — populated by the packager once ffmpeg has
  finished, used as the authoritative "how many segments to watch before
  the lesson is complete" value.
* ``lesson_progress.max_segment_index`` — highest segment index the user
  has legitimately fetched. Watermark is monotonic; rewatching a segment
  doesn't move it backwards.
* ``lesson_progress.play_credit_seconds`` — accumulated effective play time,
  computed by clamping each inter-segment gap at one segment duration so
  long pauses (or backgrounded tabs) don't bank credit.
* ``lesson_progress.last_segment_at`` — wall-clock timestamp of the last
  segment fetch, used to compute the next gap.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("hls_segments_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "lesson_progress",
        sa.Column(
            "max_segment_index",
            sa.Integer(),
            nullable=False,
            server_default="-1",
        ),
    )
    op.add_column(
        "lesson_progress",
        sa.Column(
            "play_credit_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "lesson_progress",
        sa.Column("last_segment_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lesson_progress", "last_segment_at")
    op.drop_column("lesson_progress", "play_credit_seconds")
    op.drop_column("lesson_progress", "max_segment_index")
    op.drop_column("lessons", "hls_segments_count")
