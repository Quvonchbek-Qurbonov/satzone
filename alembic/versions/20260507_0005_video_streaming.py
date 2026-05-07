"""Protected video streaming: HLS columns on lessons + media_keys table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


HLS_STATUS = postgresql.ENUM("pending", "ready", "failed", name="hls_status")


def upgrade() -> None:
    bind = op.get_bind()
    HLS_STATUS.create(bind, checkfirst=True)

    op.add_column(
        "lessons",
        sa.Column("hls_master_key", sa.String(500), nullable=True),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "hls_status",
            postgresql.ENUM(name="hls_status", create_type=False),
            nullable=True,
        ),
    )

    op.create_table(
        "media_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE", name="fk_media_keys_lesson_id_lessons"),
            nullable=False,
            unique=True,
        ),
        sa.Column("encrypted_key", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_media_keys_lesson_id", "media_keys", ["lesson_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_media_keys_lesson_id", table_name="media_keys")
    op.drop_table("media_keys")
    op.drop_column("lessons", "hls_status")
    op.drop_column("lessons", "hls_master_key")
    HLS_STATUS.drop(op.get_bind(), checkfirst=True)
