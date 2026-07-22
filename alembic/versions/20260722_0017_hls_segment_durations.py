"""Per-segment HLS durations for duration-aware anti-seek gating.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-22

The anti-seek gate originally assumed every HLS segment was exactly
``HLS_SEGMENT_SECONDS`` long — true for the transcode path, which forces a
keyframe at every segment boundary. The stream-copy fast path cuts at the
source's existing keyframes instead, so segments are non-uniform. This column
stores each segment's real playback length (seconds, parsed from the
manifest's ``#EXTINF`` lines) so the gate can compute watch-time requirements
from the actual timeline rather than a nominal segment length.

Null for lessons packaged before this column existed; the gate falls back to
the uniform ``HLS_SEGMENT_SECONDS`` assumption in that case.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column(
            "hls_segment_durations",
            sa.ARRAY(sa.Float()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lessons", "hls_segment_durations")
