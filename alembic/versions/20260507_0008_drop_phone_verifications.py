"""Drop phone_verifications table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07

The pending phone + code now lives in Redis (key ``phone_verify:<user_id>``)
with a TTL matching ``PHONE_VERIFY_EXPIRE_MINUTES``. Nothing is written to
Postgres until the user redeems a code, so the persistent table is dead
weight. The ``users.phone_number`` / ``is_phone_verified`` / ``phone_verified_at``
columns introduced in 0006 stay — those record the *verified* state.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("phone_verifications")


def downgrade() -> None:
    op.create_table(
        "phone_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", name="uq_phone_verifications_user_id"),
    )
