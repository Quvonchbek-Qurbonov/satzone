"""Drop pending_registrations.phone_number

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-07

The phone-verification flow moved off the registration form to a separate
authenticated step (POST /auth/phone), so the column on pending_registrations
is no longer populated. Drop it. The users.* phone columns and the
phone_verifications table introduced in 0006 stay.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("pending_registrations", "phone_number")


def downgrade() -> None:
    op.add_column(
        "pending_registrations",
        sa.Column("phone_number", sa.String(32), nullable=True),
    )
