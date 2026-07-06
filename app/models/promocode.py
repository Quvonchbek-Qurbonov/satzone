"""Course promocodes.

Promo codes are issued by an instructor for one of their courses and are
single-use by default. The single-use guarantee is enforced atomically at
order-creation time via an ``UPDATE ... WHERE uses_count < max_uses
RETURNING`` race-safe reservation; ``CHECK (uses_count <= max_uses)``
backs it up at the storage layer so the invariant can never silently
break, even if a future code path forgets the guard.

A reservation is held by the pending order. When the order is paid the
reservation becomes permanent; when the order is cancelled before payment
the reservation is released (``uses_count`` decremented) so the code is
available again. This means an order in PENDING state effectively locks
the code from other buyers until either it pays or is cancelled — the
expected behaviour for one-time codes.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
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
from app.models.enums import PromocodeDiscountKind

if TYPE_CHECKING:
    from app.models.catalog import Instructor
    from app.models.course import Course


promocode_discount_kind_enum = PgEnum(
    PromocodeDiscountKind,
    name="promocode_discount_kind",
    create_type=False,
    values_callable=lambda x: [e.value for e in x],
)


class Promocode(UUIDPKMixin, TimestampMixin, Base):
    """A single-use discount code issued by a course's instructor."""

    __tablename__ = "promocodes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_promocodes_code"),
        CheckConstraint("max_uses >= 1", name="ck_promocodes_max_uses_positive"),
        CheckConstraint(
            "uses_count >= 0 AND uses_count <= max_uses",
            name="ck_promocodes_uses_in_range",
        ),
        CheckConstraint(
            "(discount_kind = 'percent' AND discount_value BETWEEN 1 AND 100) "
            "OR (discount_kind = 'fixed' AND discount_value >= 1)",
            name="ck_promocodes_discount_value_valid",
        ),
        Index("ix_promocodes_course_id", "course_id"),
        Index("ix_promocodes_instructor_id", "instructor_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    instructor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instructors.id", ondelete="RESTRICT"), nullable=False
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    discount_kind: Mapped[PromocodeDiscountKind] = mapped_column(
        promocode_discount_kind_enum, nullable=False
    )
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False)

    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    course: Mapped["Course"] = relationship()
    instructor: Mapped["Instructor"] = relationship()


class SavedPromocode(UUIDPKMixin, TimestampMixin, Base):
    """A promocode a user has stashed in their profile "discounts" wallet.

    Saving is a *bookmark*, not a reservation: it records that the user
    wants this code handy at checkout. The single-use reservation still
    happens only at order creation (``promocode_service.try_reserve``), so
    saving the same code to several wallets is fine — at most one buyer
    ultimately redeems it. Because a code can expire, be revoked, or be
    used up after it was saved, the row carries no cached validity; callers
    recompute status against the live ``Promocode`` at read time.

    ``ondelete=CASCADE`` on both FKs means the wallet self-cleans when
    either the user or the underlying code is deleted.
    """

    __tablename__ = "saved_promocodes"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "promocode_id", name="uq_saved_promocodes_user_code"
        ),
        Index("ix_saved_promocodes_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    promocode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promocodes.id", ondelete="CASCADE"), nullable=False
    )

    promocode: Mapped["Promocode"] = relationship()
