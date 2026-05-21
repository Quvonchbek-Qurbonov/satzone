"""Smoke-test the USE_SMS_PROVIDER routing flag.

Patches send_email / send_sms so the test confirms which delivery channel
_issue_phone_code chooses for each value of settings.USE_SMS_PROVIDER,
without actually hitting Brevo or Infobip.

Run inside the api container:
    docker compose exec -T api python scripts/test_use_sms_provider.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, patch

import redis.asyncio as redis_asyncio


async def main() -> int:
    from app.core.config import settings
    from app.services import auth_service

    redis_url = os.environ.get("REDIS_URL", str(settings.REDIS_URL))
    r = redis_asyncio.from_url(redis_url, decode_responses=True)
    await r.flushdb()

    fake_user = types.SimpleNamespace(
        id=uuid.uuid4(),
        email="otp-routing-test@example.local",
        full_name="OTP Routing Test",
    )
    phone = "+14155552671"

    failures: list[str] = []

    # ---- Case 1: USE_SMS_PROVIDER=False -> must email, must NOT sms ----
    with patch.object(settings, "USE_SMS_PROVIDER", False), \
         patch.object(auth_service, "send_email", new=AsyncMock()) as m_email, \
         patch.object(auth_service, "send_sms", new=AsyncMock()) as m_sms:
        code = await auth_service._issue_phone_code(r, fake_user, phone)

        if not (isinstance(code, str) and code.isdigit() and len(code) == settings.PHONE_CODE_LENGTH):
            failures.append(f"[off] generated code wrong shape: {code!r}")
        if m_sms.await_count != 0:
            failures.append(f"[off] send_sms was called ({m_sms.await_count}x)")
        if m_email.await_count != 1:
            failures.append(f"[off] send_email expected 1 call, got {m_email.await_count}")
        else:
            kwargs = m_email.await_args.kwargs
            if kwargs.get("to") != fake_user.email:
                failures.append(f"[off] email sent to {kwargs.get('to')!r}, expected {fake_user.email!r}")
            if code not in (kwargs.get("body_text") or ""):
                failures.append("[off] OTP not present in email body")
            if "disabled" not in (kwargs.get("body_text") or "").lower():
                failures.append("[off] email body missing dev-mode disclaimer")

        key = auth_service._phone_verify_key(fake_user.id)
        stored = await r.hgetall(key)
        if stored.get("phone_number") != phone:
            failures.append(f"[off] redis phone_number mismatch: {stored!r}")
        if "code_hash" not in stored:
            failures.append("[off] redis missing code_hash")
        if stored.get("attempts") != "0":
            failures.append(f"[off] redis attempts not reset: {stored.get('attempts')!r}")

        print(f"[USE_SMS_PROVIDER=False] code={code}  email_calls={m_email.await_count}  sms_calls={m_sms.await_count}  redis_keys={list(stored)}")

    # ---- Case 2: USE_SMS_PROVIDER=True -> must sms, must NOT email ----
    await r.flushdb()
    with patch.object(settings, "USE_SMS_PROVIDER", True), \
         patch.object(auth_service, "send_email", new=AsyncMock()) as m_email, \
         patch.object(auth_service, "send_sms", new=AsyncMock()) as m_sms:
        code = await auth_service._issue_phone_code(r, fake_user, phone)

        if m_email.await_count != 0:
            failures.append(f"[on] send_email was called ({m_email.await_count}x)")
        if m_sms.await_count != 1:
            failures.append(f"[on] send_sms expected 1 call, got {m_sms.await_count}")
        else:
            kwargs = m_sms.await_args.kwargs
            if kwargs.get("to") != phone:
                failures.append(f"[on] sms sent to {kwargs.get('to')!r}, expected {phone!r}")
            body = kwargs.get("body") or ""
            if code not in body:
                failures.append("[on] OTP not present in SMS body")
            if len(body) > 160:
                failures.append(f"[on] SMS body exceeds 1 segment: {len(body)} chars")

        print(f"[USE_SMS_PROVIDER=True ] code={code}  email_calls={m_email.await_count}  sms_calls={m_sms.await_count}  sms_len={len(m_sms.await_args.kwargs.get('body', ''))}")

    # ---- Case 3: SMS path failure must NOT crash _issue_phone_code ----
    await r.flushdb()
    with patch.object(settings, "USE_SMS_PROVIDER", True), \
         patch.object(auth_service, "send_sms", new=AsyncMock(side_effect=RuntimeError("infobip down"))):
        try:
            await auth_service._issue_phone_code(r, fake_user, phone)
            print("[USE_SMS_PROVIDER=True ] SMS-send failure swallowed (function returned normally)")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"[on/fail] _issue_phone_code raised on SMS failure: {exc!r}")

    await r.aclose()

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nAll routing checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
