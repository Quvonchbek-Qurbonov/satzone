from __future__ import annotations

import uuid

import pytest


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
    assert register.status_code == 201
    body = register.json()
    assert body["email"] == email

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
