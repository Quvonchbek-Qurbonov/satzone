from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _phone_hash(phone: str | None) -> str | None:
    if not phone:
        return None
    digest = hashlib.sha256(phone.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"


@dataclass(slots=True)
class SMS:
    to: str  # E.164, e.g. +14155552671
    body: str


class SMSBackend(Protocol):
    async def send(self, sms: SMS) -> None: ...


class ConsoleSMSBackend:
    """Dev-only backend — logs the full SMS body (incl. the OTP) so a
    developer can grab the code without a real provider. **Never** ship
    SMS_BACKEND=console to production.
    """

    async def send(self, sms: SMS) -> None:
        logger.info("sms_send_console", to=sms.to, body=sms.body)


class BrevoSMSBackend:
    """Sends transactional SMS via Brevo (https://api.brevo.com/v3/transactionalSMS/sms)."""

    _ENDPOINT = "https://api.brevo.com/v3/transactionalSMS/sms"

    async def send(self, sms: SMS) -> None:
        import httpx

        if not settings.BREVO_API_KEY:
            raise RuntimeError("BREVO_API_KEY is not configured")
        if not settings.BREVO_SMS_SENDER:
            raise RuntimeError("BREVO_SMS_SENDER is not configured")

        # Brevo wants the recipient as digits with country code, no leading "+".
        recipient = sms.to.lstrip("+")

        payload = {
            "sender": settings.BREVO_SMS_SENDER,
            "recipient": recipient,
            "content": sms.body,
            "type": "transactional",
        }
        headers = {
            "api-key": settings.BREVO_API_KEY,
            "accept": "application/json",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self._ENDPOINT, json=payload, headers=headers)

        if resp.status_code >= 400:
            err_summary = ""
            try:
                err_json = resp.json()
                err_summary = f"{err_json.get('code', '')}: {err_json.get('message', '')}"
            except ValueError:
                err_summary = resp.text[:120]
            logger.error(
                "sms_send_brevo_failed",
                to_hash=_phone_hash(sms.to),
                status=resp.status_code,
                error=err_summary,
            )
            resp.raise_for_status()

        message_id = None
        if resp.content:
            try:
                message_id = resp.json().get("messageId")
            except ValueError:
                pass
        logger.info(
            "sms_send_brevo",
            to_hash=_phone_hash(sms.to),
            message_id=message_id,
        )


class InfobipSMSBackend:
    """Sends transactional SMS via Infobip (POST {base}/sms/2/text/advanced)."""

    async def send(self, sms: SMS) -> None:
        import httpx

        if not settings.INFOBIP_API_KEY:
            raise RuntimeError("INFOBIP_API_KEY is not configured")
        if not settings.INFOBIP_BASE_URL:
            raise RuntimeError("INFOBIP_BASE_URL is not configured")

        base = settings.INFOBIP_BASE_URL.rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        url = f"{base}/sms/2/text/advanced"

        # Infobip wants digits, no leading "+".
        recipient = sms.to.lstrip("+")

        payload = {
            "messages": [
                {
                    "destinations": [{"to": recipient}],
                    "from": settings.INFOBIP_SMS_SENDER,
                    "text": sms.body,
                }
            ]
        }
        headers = {
            "Authorization": f"App {settings.INFOBIP_API_KEY}",
            "accept": "application/json",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code >= 400:
            err_summary = ""
            try:
                err_json = resp.json()
                err_summary = str(err_json.get("requestError") or err_json)[:200]
            except ValueError:
                err_summary = resp.text[:200]
            logger.error(
                "sms_send_infobip_failed",
                to_hash=_phone_hash(sms.to),
                status=resp.status_code,
                error=err_summary,
            )
            resp.raise_for_status()

        message_id = None
        status_name = None
        if resp.content:
            try:
                first = (resp.json().get("messages") or [{}])[0]
                message_id = first.get("messageId")
                status_name = (first.get("status") or {}).get("name")
            except ValueError:
                pass
        logger.info(
            "sms_send_infobip",
            to_hash=_phone_hash(sms.to),
            message_id=message_id,
            status=status_name,
        )


def get_sms_backend() -> SMSBackend:
    if settings.SMS_BACKEND == "brevo":
        return BrevoSMSBackend()
    if settings.SMS_BACKEND == "infobip":
        return InfobipSMSBackend()
    return ConsoleSMSBackend()


async def send_sms(to: str, body: str) -> None:
    backend = get_sms_backend()
    await backend.send(SMS(to=to, body=body))
