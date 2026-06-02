"""Payments, lesson notes, lesson attachments + downloads, daily activity

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-08

Closes the gap between the SATZone designs and the backend:

* Payments domain — ``payment_methods``, ``orders``, ``transactions`` plus the
  five enums Payme's merchant API needs (``order_status``, ``order_item_kind``,
  ``payment_provider``, ``transaction_state``, ``card_brand``).
* Lesson notes — ``lesson_notes`` for the My Learning → Note screens.
* Lesson attachments + per-user download tracking — ``lesson_attachments`` and
  ``user_resource_downloads`` for the My Learning → Download screen. We
  intentionally keep video downloads off the table; the streaming pipeline
  stays the only path to lesson video bytes.
* Daily activity rollups — ``daily_activity`` feeds the home weekly chart.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres ENUM helpers — created/dropped explicitly so re-runs are clean.
order_status_enum = postgresql.ENUM(
    "pending", "processing", "paid", "cancelled", "refunded", "failed",
    name="order_status",
    create_type=False,
)
order_item_kind_enum = postgresql.ENUM(
    "course", "program", name="order_item_kind", create_type=False,
)
payment_provider_enum = postgresql.ENUM(
    "payme", "card", name="payment_provider", create_type=False,
)
transaction_state_enum = postgresql.ENUM(
    "created", "performed", "cancelled", "reversed",
    name="transaction_state",
    create_type=False,
)
card_brand_enum = postgresql.ENUM(
    "uzcard", "humo", "visa", "mastercard", "unknown",
    name="card_brand",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    order_status_enum.create(bind, checkfirst=True)
    order_item_kind_enum.create(bind, checkfirst=True)
    payment_provider_enum.create(bind, checkfirst=True)
    transaction_state_enum.create(bind, checkfirst=True)
    card_brand_enum.create(bind, checkfirst=True)

    # ---- payment_methods ----
    op.create_table(
        "payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            payment_provider_enum,
            nullable=False,
            server_default="card",
        ),
        sa.Column("token", sa.String(255), nullable=False),
        sa.Column("brand", card_brand_enum, nullable=False, server_default="unknown"),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("expires_month", sa.Integer(), nullable=False),
        sa.Column("expires_year", sa.Integer(), nullable=False),
        sa.Column("cardholder_name", sa.String(120), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("user_id", "token", name="uq_payment_methods_user_token"),
    )
    op.create_index("ix_payment_methods_user_id", "payment_methods", ["user_id"])

    # ---- orders ----
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_kind", order_item_kind_enum, nullable=False),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="UZS"),
        sa.Column("status", order_status_enum, nullable=False, server_default="pending"),
        sa.Column("provider", payment_provider_enum, nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("amount_cents > 0", name="ck_orders_amount_positive"),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_course_id", "orders", ["course_id"])
    op.create_index("ix_orders_program_id", "orders", ["program_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])

    # ---- transactions ----
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", payment_provider_enum, nullable=False),
        sa.Column("provider_txn_id", sa.String(64), nullable=False),
        sa.Column("provider_create_time", sa.BigInteger(), nullable=True),
        sa.Column(
            "state",
            transaction_state_enum,
            nullable=False,
            server_default="created",
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("perform_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Integer(), nullable=True),
        sa.Column(
            "payment_method_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_methods.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.UniqueConstraint("provider_txn_id", name="uq_transactions_provider_txn_id"),
    )
    op.create_index("ix_transactions_order_id", "transactions", ["order_id"])
    op.create_index(
        "ix_transactions_order_state", "transactions", ["order_id", "state"]
    )

    # ---- lesson_notes ----
    op.create_table(
        "lesson_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "timestamp_seconds", sa.Integer(), nullable=False, server_default="0"
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
    )
    op.create_index("ix_lesson_notes_user_id", "lesson_notes", ["user_id"])
    op.create_index("ix_lesson_notes_lesson_id", "lesson_notes", ["lesson_id"])
    op.create_index("ix_lesson_notes_course_id", "lesson_notes", ["course_id"])
    op.create_index(
        "ix_lesson_notes_user_lesson", "lesson_notes", ["user_id", "lesson_id"]
    )

    # ---- lesson_attachments ----
    op.create_table(
        "lesson_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("file_key", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(120), nullable=True),
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
    )
    op.create_index(
        "ix_lesson_attachments_lesson_id", "lesson_attachments", ["lesson_id"]
    )

    # ---- user_resource_downloads ----
    op.create_table(
        "user_resource_downloads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lesson_attachments.id", ondelete="CASCADE"),
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
        sa.UniqueConstraint("user_id", "attachment_id", name="uq_user_attachment"),
    )
    op.create_index(
        "ix_user_resource_downloads_user_id", "user_resource_downloads", ["user_id"]
    )
    op.create_index(
        "ix_user_resource_downloads_attachment_id",
        "user_resource_downloads",
        ["attachment_id"],
    )

    # ---- daily_activity ----
    op.create_table(
        "daily_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column(
            "minutes_learned", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "lessons_completed", sa.Integer(), nullable=False, server_default="0"
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
            "user_id", "activity_date", name="uq_daily_activity_user_date"
        ),
    )
    op.create_index("ix_daily_activity_user_id", "daily_activity", ["user_id"])
    op.create_index(
        "ix_daily_activity_activity_date", "daily_activity", ["activity_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_daily_activity_activity_date", table_name="daily_activity")
    op.drop_index("ix_daily_activity_user_id", table_name="daily_activity")
    op.drop_table("daily_activity")

    op.drop_index(
        "ix_user_resource_downloads_attachment_id", table_name="user_resource_downloads"
    )
    op.drop_index(
        "ix_user_resource_downloads_user_id", table_name="user_resource_downloads"
    )
    op.drop_table("user_resource_downloads")

    op.drop_index(
        "ix_lesson_attachments_lesson_id", table_name="lesson_attachments"
    )
    op.drop_table("lesson_attachments")

    op.drop_index("ix_lesson_notes_user_lesson", table_name="lesson_notes")
    op.drop_index("ix_lesson_notes_course_id", table_name="lesson_notes")
    op.drop_index("ix_lesson_notes_lesson_id", table_name="lesson_notes")
    op.drop_index("ix_lesson_notes_user_id", table_name="lesson_notes")
    op.drop_table("lesson_notes")

    op.drop_index("ix_transactions_order_state", table_name="transactions")
    op.drop_index("ix_transactions_order_id", table_name="transactions")
    op.drop_table("transactions")

    op.drop_index("ix_orders_user_status", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_program_id", table_name="orders")
    op.drop_index("ix_orders_course_id", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_payment_methods_user_id", table_name="payment_methods")
    op.drop_table("payment_methods")

    bind = op.get_bind()
    card_brand_enum.drop(bind, checkfirst=True)
    transaction_state_enum.drop(bind, checkfirst=True)
    payment_provider_enum.drop(bind, checkfirst=True)
    order_item_kind_enum.drop(bind, checkfirst=True)
    order_status_enum.drop(bind, checkfirst=True)
