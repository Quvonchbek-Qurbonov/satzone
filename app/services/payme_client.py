"""Thin async client for Payme's Subscribe (cards) API.

We use this for the card-on-file flow:

1. ``cards.create`` — exchange raw PAN+expiry for an unverified token.
2. ``cards.get_verify_code`` — Payme texts an OTP to the cardholder.
3. ``cards.verify`` — submit the OTP; token becomes "verified" / chargeable.
4. ``receipts.create`` + ``receipts.pay`` — create a receipt for an order
   amount and pay it with the verified token.

This module is **not** the merchant-callback handler. That receives JSON-RPC
*from* Payme into our backend (``CheckPerformTransaction`` etc.) — see
``payment_service.handle_merchant_rpc``.

Ref: https://developer.help.paycom.uz/
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


class PaymeError(AppError):
    """Surfaced as 502 — provider rejected the call."""

    status_code = 502
    code = "payment_provider_error"
    message = "Payment provider error"


def _api_url() -> str:
    return settings.PAYME_API_URL or (
        "https://checkout.test.paycom.uz/api"
        if settings.PAYME_TEST_MODE
        else "https://checkout.paycom.uz/api"
    )


def _checkout_base() -> str:
    return settings.PAYME_CHECKOUT_URL or (
        "https://test.paycom.uz"
        if settings.PAYME_TEST_MODE
        else "https://checkout.paycom.uz"
    )


# Subscribe API methods that require the merchant key in X-Auth.
# Cards endpoints used during enrollment (cards.create / get_verify_code /
# verify) are authenticated with the merchant id alone; anything that moves
# money or touches a verified token must include ``:KEY``.
_PROTECTED_METHODS = frozenset(
    {
        "receipts.create",
        "receipts.pay",
        "receipts.send",
        "receipts.check",
        "receipts.cancel",
        "receipts.get",
        "receipts.get_all",
        "cards.remove",
        "cards.check",
    }
)


async def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if not settings.PAYME_MERCHANT_ID:
        raise PaymeError(
            "Payme is not configured (PAYME_MERCHANT_ID missing)",
            code="payment_provider_unconfigured",
        )
    if method in _PROTECTED_METHODS:
        if not settings.PAYME_KEY:
            raise PaymeError(
                "Payme is not configured (PAYME_KEY missing for protected method)",
                code="payment_provider_unconfigured",
            )
        x_auth = f"{settings.PAYME_MERCHANT_ID}:{settings.PAYME_KEY}"
    else:
        x_auth = settings.PAYME_MERCHANT_ID
    payload = {"id": 1, "method": method, "params": params}
    headers = {"X-Auth": x_auth, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.post(_api_url(), json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("payme_rpc_transport_error", method=method, error=str(exc))
            raise PaymeError("Payme is unreachable") from exc
    if resp.status_code != 200:
        logger.error(
            "payme_rpc_http_error",
            method=method,
            status=resp.status_code,
            body=resp.text[:500],
        )
        raise PaymeError(f"Payme returned HTTP {resp.status_code}")
    body = resp.json()
    if "error" in body and body["error"]:
        err = body["error"]
        msg = err.get("message")
        if isinstance(msg, dict):
            msg = msg.get("en") or msg.get("ru") or next(iter(msg.values()), str(err))
        raise PaymeError(str(msg or "Payme error"), details={"raw": err})
    return body.get("result") or {}


# ---------- Cards ----------


async def cards_create(card_number: str, expire: str) -> dict[str, Any]:
    """Create an unverified card token.

    ``expire`` is ``MMYY`` per Payme spec (we accept ``MM/YY`` and strip).
    """

    expire_clean = expire.replace("/", "").replace(" ", "")
    return await _rpc("cards.create", {"card": {"number": card_number, "expire": expire_clean}, "save": True})


async def cards_get_verify_code(token: str) -> dict[str, Any]:
    return await _rpc("cards.get_verify_code", {"token": token})


async def cards_verify(token: str, code: str) -> dict[str, Any]:
    return await _rpc("cards.verify", {"token": token, "code": code})


async def cards_remove(token: str) -> dict[str, Any]:
    return await _rpc("cards.remove", {"token": token})


# ---------- Receipts ----------


async def receipts_create(amount: int, order_id: str) -> dict[str, Any]:
    """Create a receipt for ``amount`` (in tiyin) bound to our ``order_id``."""

    return await _rpc(
        "receipts.create",
        {"amount": amount, "account": {"order_id": order_id}},
    )


async def receipts_pay(receipt_id: str, token: str) -> dict[str, Any]:
    return await _rpc("receipts.pay", {"id": receipt_id, "token": token})


# ---------- Hosted checkout URL ----------


def build_checkout_url(merchant_id: str, order_id: str, amount_tiyin: int, return_url: str | None) -> str:
    """Build a one-time hosted-checkout URL.

    Payme expects a base64 of ``m=...;ac.order_id=...;a=<tiyin>;c=<return>``.
    """

    import base64

    parts = [f"m={merchant_id}", f"ac.order_id={order_id}", f"a={amount_tiyin}"]
    if return_url:
        parts.append(f"c={return_url}")
    raw = ";".join(parts).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"{_checkout_base()}/{encoded}"
