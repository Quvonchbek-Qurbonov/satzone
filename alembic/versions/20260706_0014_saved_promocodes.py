"""User discount wallet — saved promocodes

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-06

Adds ``saved_promocodes`` — the per-user "discounts" wallet on the profile.
A row is a *bookmark* linking a user to a promocode; it holds no cached
validity (status is recomputed at read time against the live promocode) and
imposes no reservation. Both FKs cascade so the wallet self-cleans when the
user or the underlying code is removed. ``(user_id, promocode_id)`` is unique
so the same code can't be saved twice by one user.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_promocodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "promocode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promocodes.id", ondelete="CASCADE"),
            nullable=False,
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
        sa.UniqueConstraint(
            "user_id", "promocode_id", name="uq_saved_promocodes_user_code"
        ),
    )
    op.create_index(
        "ix_saved_promocodes_user_id", "saved_promocodes", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_saved_promocodes_user_id", table_name="saved_promocodes")
    op.drop_table("saved_promocodes")
