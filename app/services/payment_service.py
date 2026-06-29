"""Payments orchestration.

Three responsibilities:

1. **Order lifecycle** — create an order for a course/program at the
   current discount price, expose status, mark cancelled.
2. **Card-on-file flow** — wrap Payme ``cards.*`` calls so the frontend
   never holds a PAN longer than one HTTP round-trip.
3. **Merchant callback** — implement Payme's JSON-RPC merchant API
   (``CheckPerformTransaction`` / ``CreateTransaction`` / ``PerformTransaction``
   / ``CancelTransaction`` / ``CheckTransaction`` / ``GetStatement``).

Once an order flips to ``PAID`` we provision the matching enrollment
through the existing enrollment service.
"""
from __future__ import annotations

import base64
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.course import Course
from app.models.enums import (
    CardBrand,
    OrderItemKind,
    OrderStatus,
    PaymentProvider,
    PublishStatus,
    TransactionState,
)
from app.models.payment import Order, PaymentMethod, Transaction
from app.models.program import Program
from app.models.promocode import Promocode
from app.models.user import User
from app.services import enrollment_service, payme_client, program_service, promocode_service

logger = get_logger(__name__)


# Payme JSON-RPC error codes (subset we surface).
ERR_INSUFFICIENT_PRIVILEGES = -32504
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_AMOUNT = -31001
ERR_TXN_NOT_FOUND = -31003
ERR_CANT_CANCEL = -31007
ERR_CANT_PERFORM = -31008
ERR_INVALID_ACCOUNT = -31050


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _detect_brand(card_number: str) -> CardBrand:
    n = card_number
    if n.startswith("8600") or n.startswith("5614"):
        return CardBrand.UZCARD
    if n.startswith("9860"):
        return CardBrand.HUMO
    if n.startswith("4"):
        return CardBrand.VISA
    if n[:2] in {"51", "52", "53", "54", "55"} or (
        len(n) >= 4 and 2221 <= int(n[:4]) <= 2720
    ):
        return CardBrand.MASTERCARD
    return CardBrand.UNKNOWN


# --- Saved cards --------------------------------------------------------


async def list_payment_methods(session: AsyncSession, user: User) -> list[PaymentMethod]:
    stmt = (
        select(PaymentMethod)
        .where(PaymentMethod.user_id == user.id, PaymentMethod.revoked_at.is_(None))
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_payment_method(
    session: AsyncSession,
    user: User,
    *,
    card_number: str,
    expires_month: int,
    expires_year: int,
    cardholder_name: str | None,
    set_default: bool,
) -> PaymentMethod:
    expire = f"{expires_month:02d}{expires_year % 100:02d}"
    result = await payme_client.cards_create(card_number, expire)
    card_obj = (result.get("card") or {})
    token = card_obj.get("token")
    if not token:
        raise ValidationAppError("Payme did not return a card token")

    if set_default:
        # demote previous default
        await session.execute(
            PaymentMethod.__table__.update()
            .where(PaymentMethod.user_id == user.id)
            .values(is_default=False)
        )

    pm = PaymentMethod(
        user_id=user.id,
        provider=PaymentProvider.CARD,
        token=token,
        brand=_detect_brand(card_number),
        last4=card_number[-4:],
        expires_month=expires_month,
        expires_year=expires_year,
        cardholder_name=cardholder_name,
        is_default=set_default,
        is_verified=bool(card_obj.get("verify")),
    )
    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return pm


async def start_card_verification(
    session: AsyncSession, user: User, pm_id: uuid.UUID
) -> dict[str, Any]:
    pm = await _get_pm(session, user, pm_id)
    if pm.is_verified:
        raise ConflictError("Card is already verified")
    return await payme_client.cards_get_verify_code(pm.token)


async def confirm_card_verification(
    session: AsyncSession, user: User, pm_id: uuid.UUID, code: str
) -> PaymentMethod:
    pm = await _get_pm(session, user, pm_id)
    if pm.is_verified:
        return pm
    await payme_client.cards_verify(pm.token, code)
    pm.is_verified = True
    await session.commit()
    await session.refresh(pm)
    return pm


async def delete_payment_method(
    session: AsyncSession, user: User, pm_id: uuid.UUID
) -> None:
    pm = await _get_pm(session, user, pm_id)
    try:
        await payme_client.cards_remove(pm.token)
    except Exception as exc:  # noqa: BLE001  (best-effort revoke at provider)
        logger.warning("payme_cards_remove_failed", error=str(exc), pm_id=str(pm_id))
    pm.revoked_at = _now()
    await session.commit()


async def _get_pm(session: AsyncSession, user: User, pm_id: uuid.UUID) -> PaymentMethod:
    pm = await session.get(PaymentMethod, pm_id)
    if pm is None or pm.user_id != user.id or pm.revoked_at is not None:
        raise NotFoundError("Payment method not found")
    return pm


# --- Orders -------------------------------------------------------------


async def create_order(
    session: AsyncSession,
    user: User,
    *,
    item_kind: OrderItemKind,
    course_id: uuid.UUID | None,
    program_id: uuid.UUID | None,
    promocode: str | None = None,
) -> Order:
    if item_kind is OrderItemKind.COURSE:
        course = await get_published_course(session, course_id)
        original_amount = course.effective_price_cents
        currency = course.currency
        if original_amount == 0:
            raise ValidationAppError(
                "Course is free — call /me/enrollments directly", code="free_item"
            )
    else:
        if promocode:
            raise ValidationAppError(
                "Promocodes are not supported for program orders",
                code="promocode_not_applicable",
            )
        program = await _published_program(session, program_id)
        original_amount = program.price_cents
        currency = program.currency
        if original_amount == 0:
            raise ValidationAppError(
                "Program is free — call /programs/{id}/enroll directly",
                code="free_item",
            )

    # Reuse a pending order for the same item (idempotency for double-clicks).
    # A different promo code on retry replaces the prior reservation so the
    # buyer can swap codes without leaking the old reservation.
    existing = (
        await session.execute(
            select(Order).where(
                Order.user_id == user.id,
                Order.status == OrderStatus.PENDING,
                Order.item_kind == item_kind,
                Order.course_id == course_id,
                Order.program_id == program_id,
            )
        )
    ).scalar_one_or_none()

    promo: Promocode | None = None
    discount_cents = 0
    if promocode and item_kind is OrderItemKind.COURSE and course_id is not None:
        promo = await promocode_service.find_active_promocode_for_course(
            session, code=promocode, course_id=course_id
        )
        discount_cents = promocode_service.compute_discount_cents(
            kind=promo.discount_kind,
            value=promo.discount_value,
            base_amount_cents=original_amount,
        )
        final_amount = original_amount - discount_cents
        if final_amount <= 0:
            raise ValidationAppError(
                "Promocode would make the order free; use free enrollment instead",
                code="promocode_makes_free",
            )
    else:
        final_amount = original_amount

    if existing is not None:
        # If the buyer is re-applying the same code, return the order untouched.
        if existing.promocode_id == (promo.id if promo else None):
            return existing
        # Otherwise: release the previous reservation, then attempt the new one.
        if existing.promocode_id is not None:
            await promocode_service.release(session, existing.promocode_id)
            existing.promocode_id = None
            existing.discount_cents = 0
            existing.original_amount_cents = None
            existing.amount_cents = original_amount
            await session.flush()
        if promo is not None:
            if not await promocode_service.try_reserve(session, promo):
                await session.rollback()
                raise ConflictError(
                    "Promocode has already been used",
                    code="promocode_exhausted",
                )
            existing.promocode_id = promo.id
            existing.discount_cents = discount_cents
            existing.original_amount_cents = original_amount
            existing.amount_cents = final_amount
        await session.commit()
        await session.refresh(existing)
        return existing

    if promo is not None:
        if not await promocode_service.try_reserve(session, promo):
            await session.rollback()
            raise ConflictError(
                "Promocode has already been used",
                code="promocode_exhausted",
            )

    order = Order(
        user_id=user.id,
        item_kind=item_kind,
        course_id=course_id,
        program_id=program_id,
        amount_cents=final_amount,
        original_amount_cents=original_amount if promo is not None else None,
        discount_cents=discount_cents,
        promocode_id=promo.id if promo is not None else None,
        currency=currency,
        status=OrderStatus.PENDING,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_order(session: AsyncSession, user: User, order_id: uuid.UUID) -> Order:
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise NotFoundError("Order not found")
    return order


async def list_orders(session: AsyncSession, user: User) -> list[Order]:
    stmt = (
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def cancel_order(session: AsyncSession, user: User, order_id: uuid.UUID) -> Order:
    order = await get_order(session, user, order_id)
    if order.status not in {OrderStatus.PENDING, OrderStatus.PROCESSING}:
        raise ConflictError("Order cannot be cancelled in its current state")
    if order.promocode_id is not None:
        await promocode_service.release(session, order.promocode_id)
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = _now()
    await session.commit()
    await session.refresh(order)
    return order


# --- Pay actions --------------------------------------------------------


async def pay_with_card(
    session: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    payment_method_id: uuid.UUID,
) -> tuple[Order, Transaction]:
    order = await get_order(session, user, order_id)
    if order.status != OrderStatus.PENDING:
        raise ConflictError("Order is not awaiting payment")
    pm = await _get_pm(session, user, payment_method_id)
    if not pm.is_verified:
        raise ForbiddenError("Card is not verified", code="card_not_verified")

    receipt = await payme_client.receipts_create(order.amount_cents, str(order.id))
    receipt_obj = (receipt.get("receipt") or {})
    receipt_id = receipt_obj.get("_id") or receipt_obj.get("id")
    if not receipt_id:
        raise ValidationAppError("Payme did not return a receipt id")
    pay_result = await payme_client.receipts_pay(receipt_id, pm.token)

    txn = Transaction(
        order_id=order.id,
        provider=PaymentProvider.CARD,
        provider_txn_id=str(receipt_id),
        state=TransactionState.PERFORMED,
        amount_cents=order.amount_cents,
        perform_time=_now(),
        payment_method_id=pm.id,
    )
    session.add(txn)

    order.status = OrderStatus.PAID
    order.provider = PaymentProvider.CARD
    order.paid_at = _now()
    await session.flush()
    await _grant_entitlement(session, order)
    await session.commit()
    await session.refresh(order)
    await session.refresh(txn)
    logger.info("order_paid_card", order_id=str(order.id), receipt=str(receipt_id), result=pay_result.get("state"))
    return order, txn


async def pay_with_payme(
    session: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    return_url: str | None,
) -> tuple[Order, str]:
    order = await get_order(session, user, order_id)
    if order.status != OrderStatus.PENDING:
        raise ConflictError("Order is not awaiting payment")
    if not settings.PAYME_MERCHANT_ID:
        raise ValidationAppError(
            "Payme is not configured", code="payment_provider_unconfigured"
        )
    order.provider = PaymentProvider.PAYME
    await session.commit()
    url = payme_client.build_checkout_url(
        merchant_id=settings.PAYME_MERCHANT_ID,
        order_id=str(order.id),
        amount_tiyin=order.amount_cents,
        return_url=return_url,
    )
    return order, url


# --- Entitlement provisioning ------------------------------------------


async def _grant_entitlement(session: AsyncSession, order: Order) -> None:
    user = await session.get(User, order.user_id)
    if user is None:  # pragma: no cover  (FK guarantees presence)
        return
    if order.item_kind is OrderItemKind.COURSE and order.course_id:
        await enrollment_service.enroll(session, user, order.course_id)
    elif order.item_kind is OrderItemKind.PROGRAM and order.program_id:
        await program_service.enroll_in_program(session, user, order.program_id)


# --- Lookups ------------------------------------------------------------


async def get_published_course(session: AsyncSession, course_id: uuid.UUID | None) -> Course:
    if course_id is None:
        raise ValidationAppError("course_id required")
    course = (
        await session.execute(
            select(Course).where(
                Course.id == course_id, Course.status == PublishStatus.PUBLISHED
            )
        )
    ).scalar_one_or_none()
    if course is None:
        raise NotFoundError("Course not found")
    return course


async def _published_program(session: AsyncSession, program_id: uuid.UUID | None) -> Program:
    if program_id is None:
        raise ValidationAppError("program_id required")
    program = (
        await session.execute(
            select(Program).where(
                Program.id == program_id, Program.status == PublishStatus.PUBLISHED
            )
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")
    return program


# --- Payme merchant JSON-RPC callback -----------------------------------


def _verify_basic_auth(auth_header: str | None) -> bool:
    """Payme authenticates merchant calls via HTTP Basic ``Paycom:<key>``."""

    if not auth_header or not auth_header.lower().startswith("basic "):
        return False
    if not settings.PAYME_KEY:
        return False
    try:
        raw = base64.b64decode(auth_header.split(None, 1)[1]).decode("utf-8")
    except Exception:
        return False
    if ":" not in raw:
        return False
    user, key = raw.split(":", 1)
    return secrets.compare_digest(key, settings.PAYME_KEY) and user in {"Paycom", "paycom"}


def _err(code: int, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": {"en": message, "ru": message, "uz": message}}}


async def handle_merchant_rpc(
    session: AsyncSession, auth_header: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch one Payme JSON-RPC request to its handler.

    Always returns a valid JSON-RPC envelope (with ``result`` or ``error``);
    the caller wraps it in HTTP 200 — Payme expects all replies on 200.
    """

    if not _verify_basic_auth(auth_header):
        return _err(ERR_INSUFFICIENT_PRIVILEGES, "Insufficient privileges")

    method = body.get("method")
    params = body.get("params") or {}
    rpc_id = body.get("id")

    handlers = {
        "CheckPerformTransaction": _check_perform_transaction,
        "CreateTransaction": _create_transaction,
        "PerformTransaction": _perform_transaction,
        "CancelTransaction": _cancel_transaction,
        "CheckTransaction": _check_transaction,
        "GetStatement": _get_statement,
    }
    handler = handlers.get(method)
    if handler is None:
        return {"jsonrpc": "2.0", "id": rpc_id, **_err(ERR_METHOD_NOT_FOUND, "Method not found")}

    try:
        result = await handler(session, params)
    except _RpcError as exc:
        return {"jsonrpc": "2.0", "id": rpc_id, **_err(exc.code, exc.message)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("payme_rpc_handler_error", method=method, error=str(exc))
        return {"jsonrpc": "2.0", "id": rpc_id, **_err(-32400, "Internal error")}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message


async def _resolve_order(session: AsyncSession, params: dict[str, Any]) -> Order:
    account = params.get("account") or {}
    order_id_raw = account.get("order_id")
    if not order_id_raw:
        raise _RpcError(ERR_INVALID_ACCOUNT, "order_id is required")
    try:
        order_id = uuid.UUID(str(order_id_raw))
    except ValueError as exc:
        raise _RpcError(ERR_INVALID_ACCOUNT, "order_id is not a valid UUID") from exc
    order = await session.get(Order, order_id)
    if order is None:
        raise _RpcError(ERR_INVALID_ACCOUNT, "Order not found")
    return order


async def _check_perform_transaction(
    session: AsyncSession, params: dict[str, Any]
) -> dict[str, Any]:
    order = await _resolve_order(session, params)
    amount = int(params.get("amount") or 0)
    if amount != order.amount_cents:
        raise _RpcError(ERR_INVALID_AMOUNT, "Amount does not match order total")
    if order.status != OrderStatus.PENDING:
        raise _RpcError(ERR_CANT_PERFORM, "Order is not awaiting payment")
    return {"allow": True}


async def _create_transaction(session: AsyncSession, params: dict[str, Any]) -> dict[str, Any]:
    order = await _resolve_order(session, params)
    amount = int(params.get("amount") or 0)
    txn_id = str(params.get("id") or "")
    create_time = int(params.get("time") or 0)
    if not txn_id:
        raise _RpcError(ERR_INVALID_ACCOUNT, "id is required")
    if amount != order.amount_cents:
        raise _RpcError(ERR_INVALID_AMOUNT, "Amount does not match order total")

    existing = (
        await session.execute(
            select(Transaction).where(Transaction.provider_txn_id == txn_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.state != TransactionState.CREATED:
            raise _RpcError(ERR_CANT_PERFORM, "Transaction already finalised")
        return {
            "create_time": existing.provider_create_time or create_time,
            "transaction": str(existing.id),
            "state": 1,
        }

    if order.status != OrderStatus.PENDING:
        raise _RpcError(ERR_CANT_PERFORM, "Order is not awaiting payment")

    txn = Transaction(
        order_id=order.id,
        provider=PaymentProvider.PAYME,
        provider_txn_id=txn_id,
        provider_create_time=create_time,
        state=TransactionState.CREATED,
        amount_cents=amount,
    )
    session.add(txn)
    order.status = OrderStatus.PROCESSING
    order.provider = PaymentProvider.PAYME
    await session.commit()
    await session.refresh(txn)
    return {"create_time": create_time, "transaction": str(txn.id), "state": 1}


async def _perform_transaction(session: AsyncSession, params: dict[str, Any]) -> dict[str, Any]:
    txn = await _txn_by_provider_id(session, params)
    if txn.state == TransactionState.PERFORMED:
        return {
            "transaction": str(txn.id),
            "perform_time": int(txn.perform_time.timestamp() * 1000) if txn.perform_time else 0,
            "state": 2,
        }
    if txn.state != TransactionState.CREATED:
        raise _RpcError(ERR_CANT_PERFORM, "Transaction is not in created state")
    txn.state = TransactionState.PERFORMED
    txn.perform_time = _now()
    txn.order.status = OrderStatus.PAID
    txn.order.paid_at = txn.perform_time
    await session.flush()
    await _grant_entitlement(session, txn.order)
    await session.commit()
    await session.refresh(txn)
    return {
        "transaction": str(txn.id),
        "perform_time": int(txn.perform_time.timestamp() * 1000),
        "state": 2,
    }


async def _cancel_transaction(session: AsyncSession, params: dict[str, Any]) -> dict[str, Any]:
    txn = await _txn_by_provider_id(session, params)
    reason = int(params.get("reason") or 0)
    if txn.state == TransactionState.CANCELLED or txn.state == TransactionState.REVERSED:
        return {
            "transaction": str(txn.id),
            "cancel_time": int(txn.cancel_time.timestamp() * 1000) if txn.cancel_time else 0,
            "state": -1 if txn.state == TransactionState.CANCELLED else -2,
        }
    new_state = (
        TransactionState.REVERSED if txn.state == TransactionState.PERFORMED else TransactionState.CANCELLED
    )
    txn.state = new_state
    txn.cancel_time = _now()
    txn.cancel_reason = reason
    if new_state == TransactionState.REVERSED:
        txn.order.status = OrderStatus.REFUNDED
    else:
        # Cancel-before-perform: release the promocode reservation so the
        # next buyer can use the code. Refund-after-perform keeps the
        # consumption — the seat was sold and then returned, but the code
        # itself is single-use.
        if txn.order.promocode_id is not None:
            await promocode_service.release(session, txn.order.promocode_id)
        txn.order.status = OrderStatus.CANCELLED
        txn.order.cancelled_at = txn.cancel_time
    await session.commit()
    await session.refresh(txn)
    return {
        "transaction": str(txn.id),
        "cancel_time": int(txn.cancel_time.timestamp() * 1000),
        "state": -1 if new_state == TransactionState.CANCELLED else -2,
    }


async def _check_transaction(session: AsyncSession, params: dict[str, Any]) -> dict[str, Any]:
    txn = await _txn_by_provider_id(session, params)
    state_map = {
        TransactionState.CREATED: 1,
        TransactionState.PERFORMED: 2,
        TransactionState.CANCELLED: -1,
        TransactionState.REVERSED: -2,
    }
    return {
        "create_time": txn.provider_create_time or 0,
        "perform_time": int(txn.perform_time.timestamp() * 1000) if txn.perform_time else 0,
        "cancel_time": int(txn.cancel_time.timestamp() * 1000) if txn.cancel_time else 0,
        "transaction": str(txn.id),
        "state": state_map[txn.state],
        "reason": txn.cancel_reason,
    }


async def _get_statement(session: AsyncSession, params: dict[str, Any]) -> dict[str, Any]:
    from_ms = int(params.get("from") or 0)
    to_ms = int(params.get("to") or 0)
    stmt = select(Transaction).where(Transaction.provider == PaymentProvider.PAYME)
    rows = list((await session.execute(stmt)).scalars().all())
    transactions = []
    for txn in rows:
        if txn.provider_create_time is None:
            continue
        if not (from_ms <= txn.provider_create_time <= to_ms):
            continue
        transactions.append(
            {
                "id": txn.provider_txn_id,
                "time": txn.provider_create_time,
                "amount": txn.amount_cents,
                "account": {"order_id": str(txn.order_id)},
                "create_time": txn.provider_create_time,
                "perform_time": int(txn.perform_time.timestamp() * 1000) if txn.perform_time else 0,
                "cancel_time": int(txn.cancel_time.timestamp() * 1000) if txn.cancel_time else 0,
                "transaction": str(txn.id),
                "state": {
                    TransactionState.CREATED: 1,
                    TransactionState.PERFORMED: 2,
                    TransactionState.CANCELLED: -1,
                    TransactionState.REVERSED: -2,
                }[txn.state],
                "reason": txn.cancel_reason,
            }
        )
    return {"transactions": transactions}


async def _txn_by_provider_id(
    session: AsyncSession, params: dict[str, Any]
) -> Transaction:
    txn_id = str(params.get("id") or "")
    if not txn_id:
        raise _RpcError(ERR_TXN_NOT_FOUND, "Transaction id required")
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.order))
        .where(Transaction.provider_txn_id == txn_id)
    )
    txn = (await session.execute(stmt)).scalar_one_or_none()
    if txn is None:
        raise _RpcError(ERR_TXN_NOT_FOUND, "Transaction not found")
    return txn
