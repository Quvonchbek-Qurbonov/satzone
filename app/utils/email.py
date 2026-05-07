from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.core.config import settings
from app.core.logging import email_hash, get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Email:
    to: str
    subject: str
    body_text: str
    body_html: str | None = None


class EmailBackend(Protocol):
    async def send(self, email: Email) -> None: ...


class ConsoleEmailBackend:
    """Dev-only backend — prints the full email (incl. address + body) to
    the log so a developer can grab the verify/reset link without setting
    up SMTP. **Never** ship MAIL_BACKEND=console to production: it leaks
    PII and reset tokens to anyone with log access.
    """

    async def send(self, email: Email) -> None:
        logger.info(
            "email_send_console",
            to=email.to,
            subject=email.subject,
            body=email.body_text,
        )


class SMTPEmailBackend:
    async def send(self, email: Email) -> None:
        # Lazy import — only required when SMTP is enabled.
        import asyncio
        import smtplib

        msg = EmailMessage()
        msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>"
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg.set_content(email.body_text)
        if email.body_html:
            msg.add_alternative(email.body_html, subtype="html")

        def _send() -> None:
            host = settings.SMTP_HOST or "localhost"
            with smtplib.SMTP(host, settings.SMTP_PORT, timeout=15) as smtp:
                if settings.SMTP_TLS:
                    smtp.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)

        await asyncio.to_thread(_send)


class BrevoEmailBackend:
    """Sends mail via Brevo's transactional REST API (https://api.brevo.com/v3/smtp/email)."""

    _ENDPOINT = "https://api.brevo.com/v3/smtp/email"

    async def send(self, email: Email) -> None:
        import httpx

        if not settings.BREVO_API_KEY:
            raise RuntimeError("BREVO_API_KEY is not configured")

        payload: dict[str, object] = {
            "sender": {"name": settings.MAIL_FROM_NAME, "email": settings.MAIL_FROM},
            "to": [{"email": email.to}],
            "subject": email.subject,
            "textContent": email.body_text,
        }
        if email.body_html:
            payload["htmlContent"] = email.body_html

        headers = {
            "api-key": settings.BREVO_API_KEY,
            "accept": "application/json",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self._ENDPOINT, json=payload, headers=headers)

        if resp.status_code >= 400:
            # Brevo error responses can echo the recipient address back in
            # the body — strip it down to just the upstream code/message
            # before it lands in Loki. The full body stays out of logs.
            err_summary = ""
            try:
                err_json = resp.json()
                err_summary = f"{err_json.get('code', '')}: {err_json.get('message', '')}"
            except ValueError:
                err_summary = resp.text[:120]
            logger.error(
                "email_send_brevo_failed",
                to_hash=email_hash(email.to),
                subject=email.subject,
                status=resp.status_code,
                error=err_summary,
            )
            resp.raise_for_status()

        logger.info(
            "email_send_brevo",
            to_hash=email_hash(email.to),
            subject=email.subject,
            message_id=resp.json().get("messageId") if resp.content else None,
        )


def get_email_backend() -> EmailBackend:
    if settings.MAIL_BACKEND == "smtp":
        return SMTPEmailBackend()
    if settings.MAIL_BACKEND == "brevo":
        return BrevoEmailBackend()
    return ConsoleEmailBackend()


async def send_email(to: str, subject: str, body_text: str, body_html: str | None = None) -> None:
    backend = get_email_backend()
    await backend.send(Email(to=to, subject=subject, body_text=body_text, body_html=body_html))