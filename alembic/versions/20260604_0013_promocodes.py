"""Course promocodes — single-use discount codes issued by instructors

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-04

Adds:

* ``promocode_discount_kind`` enum (``percent`` / ``fixed``).
* ``promocodes`` table — owner (instructor), course, code (globally
  unique), discount math, expiry, reservation counter. The
  ``uses_count <= max_uses`` CHECK is the storage-layer backstop for the
  race-safe ``UPDATE ... WHERE uses_count < max_uses`` reservation in
  ``promocode_service.try_reserve``.
* ``orders.promocode_id`` (FK, SET NULL on delete), ``orders.discount_cents``,
  ``orders.original_amount_cents`` — record what code was applied to an
  order and how much was knocked off. Keeping ``original_amount_cents``
  separately means refunds / audits can reconstruct the original price
  even after the code is deleted.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROMOCODE_DISCOUNT_KIND = postgresql.ENUM(
    "percent", "fixed", name="promocode_discount_kind"
)


def upgrade() -> None:
    PROMOCODE_DISCOUNT_KIND.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "promocodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instructor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instructors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column(
            "discount_kind",
            postgresql.ENUM(
                "percent", "fixed", name="promocode_discount_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("discount_value", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
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
        sa.UniqueConstraint("code", name="uq_promocodes_code"),
        sa.CheckConstraint(
            "max_uses >= 1", name="ck_promocodes_max_uses_positive"
        ),
        sa.CheckConstraint(
            "uses_count >= 0 AND uses_count <= max_uses",
            name="ck_promocodes_uses_in_range",
        ),
        sa.CheckConstraint(
            "(discount_kind = 'percent' AND discount_value BETWEEN 1 AND 100) "
            "OR (discount_kind = 'fixed' AND discount_value >= 1)",
            name="ck_promocodes_discount_value_valid",
        ),
    )

    op.create_index("ix_promocodes_course_id", "promocodes", ["course_id"])
    op.create_index("ix_promocodes_instructor_id", "promocodes", ["instructor_id"])

    op.add_column(
        "orders",
        sa.Column(
            "promocode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promocodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("original_amount_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "discount_cents", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_index("ix_orders_promocode_id", "orders", ["promocode_id"])
    op.create_check_constraint(
        "ck_orders_discount_cents_non_negative",
        "orders",
        "discount_cents >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_orders_discount_cents_non_negative", "orders", type_="check"
    )
    op.drop_index("ix_orders_promocode_id", table_name="orders")
    op.drop_column("orders", "discount_cents")
    op.drop_column("orders", "original_amount_cents")
    op.drop_column("orders", "promocode_id")

    op.drop_index("ix_promocodes_instructor_id", table_name="promocodes")
    op.drop_index("ix_promocodes_course_id", table_name="promocodes")
    op.drop_table("promocodes")
    PROMOCODE_DISCOUNT_KIND.drop(op.get_bind(), checkfirst=True)
