from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TokenType = Literal["access", "refresh", "verify_email", "password_reset"]


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _pwd_context.needs_update(password_hash)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def create_access_token(
    subject: str | uuid.UUID,
    *,
    expires_in: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    expire = _now() + (expires_in or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "access",
        "iat": int(_now().timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expire


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token expired", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid token", code="invalid_token") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type", code="invalid_token")
    return payload


def generate_opaque_token(num_bytes: int = 48) -> str:
    """URL-safe random token for refresh / verify / reset flows."""
    return secrets.token_urlsafe(num_bytes)


def hash_opaque_token(token: str) -> str:
    """Stable hash for storing opaque tokens at rest. Argon2 is fine here too,
    but we want deterministic lookup, so we use SHA-256.
    """
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def consteq(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)