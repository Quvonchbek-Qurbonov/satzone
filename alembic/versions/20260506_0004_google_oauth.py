"""Google OAuth: add users.google_sub and make users.password_hash nullable

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))
    op.create_index(
        "ix_users_google_sub", "users", ["google_sub"], unique=True
    )
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    # Best-effort: rows where password_hash IS NULL would block the NOT NULL flip.
    op.execute("UPDATE users SET password_hash='' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")
