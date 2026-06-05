"""Payments domain.

Three tables back the checkout + Payme integration:

- ``payment_methods`` — cards saved on file. We never store the PAN; only
  the Payme card ``token`` (returned by ``cards.create`` + verified via
  ``cards.verify``), the masked last 4 digits, and the brand/expiry.
- ``orders`` — a purchase intent for one course or program. Owns one or more
  transactions over its lifetime (the user may retry after a cancel).
- ``transactions`` — exact mirror of Payme's Merchant API transaction state
  machine. Each callback (CreateTransaction / PerformTransaction /
  CancelTransaction) flips columns here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import (
    CardBrand,
    OrderItemKind,
    OrderStatus,
    PaymentProvider,
    TransactionState,
)

if TYPE_CHECKING:
    from app.models.user import User


order_status_enum = PgEnum(
    OrderStatus, name="order_status", create_type=False,
    values_callable=lambda x: [e.value for e in x],
)
order_item_kind_enum = PgEnum(
    OrderItemKind, name="order_item_kind", create_type=False,
    values_callable=lambda x: [e.value for e in x],
)
payment_provider_enum = PgEnum(
    PaymentProvider, name="payment_provider", create_type=False,
    values_callable=lambda x: [e.value for e in x],
)
transaction_state_enum = PgEnum(
    TransactionState, name="transaction_state", create_type=False,
    values_callable=lambda x: [e.value for e in x],
)
card_brand_enum = PgEnum(
    CardBrand, name="card_brand", create_type=False,
    values_callable=lambda x: [e.value for e in x],
)


class PaymentMethod(UUIDPKMixin, TimestampMixin, Base):
    """A card on file. We hold only the Payme card token + last4 + expiry."""

    __tablename__ = "payment_methods"
    __table_args__ = (
        UniqueConstraint("user_id", "token", name="uq_payment_methods_user_token"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        payment_provider_enum, nullable=False, default=PaymentProvider.CARD
    )
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[CardBrand] = mapped_column(
        card_brand_enum, nullable=False, default=CardBrand.UNKNOWN
    )
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    expires_month: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_year: Mapped[int] = mapped_column(Integer, nullable=False)
    cardholder_name: Mapped[str | None] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Order(UUIDPKMixin, TimestampMixin, Base):
    """One purchase intent — fronted by exactly one course or program."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(
            "discount_cents >= 0", name="discount_cents_non_negative"
        ),
        Index("ix_orders_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    item_kind: Mapped[OrderItemKind] = mapped_column(order_item_kind_enum, nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), index=True
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("programs.id", ondelete="RESTRICT"), index=True
    )

    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="UZS")

    # Promocode applied at order creation. ``promocode_id`` is the reservation
    # holder — released on cancel, kept on paid. ``discount_cents`` records
    # how much was knocked off ``original_amount_cents`` so audit / refunds
    # can reconstruct the math; ``amount_cents`` is what Payme charges.
    promocode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("promocodes.id", ondelete="SET NULL"), index=True
    )
    original_amount_cents: Mapped[int | None] = mapped_column(Integer)
    discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[OrderStatus] = mapped_column(
        order_status_enum, nullable=False, default=OrderStatus.PENDING, index=True
    )
    provider: Mapped[PaymentProvider | None] = mapped_column(payment_provider_enum)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="Transaction.created_at"
    )


class Transaction(UUIDPKMixin, TimestampMixin, Base):
    """One Payme Merchant API transaction. Tied 1:1 with a provider txn id."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("provider_txn_id", name="uq_transactions_provider_txn_id"),
        Index("ix_transactions_order_state", "order_id", "state"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(payment_provider_enum, nullable=False)
    # Payme's id field — opaque string we store verbatim
    provider_txn_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Payme's "time" param at create — millisecond unix timestamp
    provider_create_time: Mapped[int | None] = mapped_column(BigInteger)

    state: Mapped[TransactionState] = mapped_column(
        transaction_state_enum, nullable=False, default=TransactionState.CREATED
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    perform_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[int | None] = mapped_column(Integer)

    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL")
    )

    order: Mapped[Order] = relationship(back_populates="transactions")
