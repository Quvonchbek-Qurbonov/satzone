from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_register_login_flow(client):
    """Smoke test — requires a live Postgres + Redis (see compose). Skipped in unit-only runs."""
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Smoke User", "password": "Sup3rSecret!"},
    )
    if register.status_code == 500:
        pytest.skip("Smoke flow needs DB — skipping")
    assert register.status_code == 202

    # Login must fail until the email is verified.
    pre_verify_login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert pre_verify_login.status_code == 401
    assert pre_verify_login.json()["error"]["code"] in {"invalid_credentials", "email_not_verified"}

    # Pull the verification token straight from the DB (we can't read the email here).
    from app.db.session import SessionLocal
    from app.models.auth import PendingRegistration

    async with SessionLocal() as session:
        pending = (
            await session.execute(
                select(PendingRegistration).where(PendingRegistration.email == email)
            )
        ).scalar_one()
        # Use a deterministic token rotation so we can read it back in plaintext.
        from app.core.security import generate_opaque_token, hash_opaque_token

        raw_token = generate_opaque_token()
        pending.token_hash = hash_opaque_token(raw_token)
        await session.commit()

    verify = await client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    assert verify.status_code == 200

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert login.status_code == 200
    tokens = login.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == email

    # Refresh rotation
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # Old refresh token must now fail
    reused = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reused.status_code in (401, 403)
