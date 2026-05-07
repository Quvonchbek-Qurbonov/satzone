"""Phone number on users + phone_verifications table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-07

Adds phone number registration and confirmation:
- ``users.phone_number`` (unique, nullable so OAuth-only and pre-existing rows
  remain valid), ``users.is_phone_verified`` and ``users.phone_verified_at``.
- ``pending_registrations.phone_number`` so the value submitted at register
  time survives the email-verify hop.
- ``phone_verifications`` — one in-flight code per user (replaced on resend),
  with attempt counter for short-code brute-force protection.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone_number", sa.String(32), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_phone_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)
    # Drop server_default after backfill so future inserts must specify the value via the model.
    op.alter_column("users", "is_phone_verified", server_default=None)

    op.add_column(
        "pending_registrations",
        sa.Column("phone_number", sa.String(32), nullable=True),
    )

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


def downgrade() -> None:
    op.drop_table("phone_verifications")
    op.drop_column("pending_registrations", "phone_number")
    op.drop_index("ix_users_phone_number", table_name="users")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "is_phone_verified")
    op.drop_column("users", "phone_number")
