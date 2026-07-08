"""Widen avatar_url columns to 2048 chars

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-08

Google OAuth profile picture URLs (lh3.googleusercontent.com/...) regularly
exceed 500 characters, which caused ``StringDataRightTruncationError`` on the
Google sign-in callback when inserting ``users.avatar_url``. Both ``users`` and
``instructors`` store external avatar URLs (and instructor rows can inherit a
user's Google avatar), so widen both from VARCHAR(500) to VARCHAR(2048).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(500),
        type_=sa.String(2048),
        existing_nullable=True,
    )
    op.alter_column(
        "instructors",
        "avatar_url",
        existing_type=sa.String(500),
        type_=sa.String(2048),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "instructors",
        "avatar_url",
        existing_type=sa.String(2048),
        type_=sa.String(500),
        existing_nullable=True,
    )
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(2048),
        type_=sa.String(500),
        existing_nullable=True,
    )
