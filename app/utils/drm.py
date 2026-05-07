"""DRM (Widevine / FairPlay / PlayReady) integration point.

True DRM stops a determined attacker (Widevine/FairPlay run inside a
hardware-backed black box on the client device), but it requires a paid
license server. This module is the seam where you plug one in.

Two providers are sketched out:

* ``ezdrm`` — third-party multi-DRM service. Uses the per-content-id key
  delivery API; you'll need to switch the HLS packager to fMP4 + CENC and
  push the content key to ezDRM at packaging time.
* ``widevine_proxy`` — DIY: stand up your own Widevine license proxy in
  front of Google's license service. Covered in the Widevine Cloud License
  API (https://developers.google.com/widevine/drm/overview).

Until you wire one of these in, ``DRM_PROVIDER`` should stay at ``"none"``
and lessons rely on the HLS+AES-128 layer in ``app/utils/hls.py``.
"""

from __future__ import annotations

import uuid
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


class DRMProvider(Protocol):
    """Minimal interface every provider implementation must satisfy."""

    async def issue_license(
        self, *, lesson_id: uuid.UUID, user_id: uuid.UUID, license_request: bytes
    ) -> bytes:
        """Forward a player's binary license challenge to the DRM service and
        return the binary license response. The HTTP layer is responsible for
        bytes-in / bytes-out — neither side parses CENC.
        """
        ...


class _NoOpProvider:
    async def issue_license(
        self, *, lesson_id: uuid.UUID, user_id: uuid.UUID, license_request: bytes
    ) -> bytes:
        raise AppError(
            "DRM is not configured. Set DRM_PROVIDER and credentials in .env, "
            "and ship encrypted CENC content from the packager.",
            code="drm_not_configured",
        )


class _EzDRMProvider:
    async def issue_license(
        self, *, lesson_id: uuid.UUID, user_id: uuid.UUID, license_request: bytes
    ) -> bytes:
        if not settings.DRM_LICENSE_URL or not settings.DRM_API_KEY:
            raise AppError(
                "ezDRM provider requires DRM_LICENSE_URL and DRM_API_KEY",
                code="drm_misconfigured",
            )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.DRM_LICENSE_URL,
                content=license_request,
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-Api-Key": settings.DRM_API_KEY,
                    "X-Content-Id": str(lesson_id),
                    "X-User-Id": str(user_id),
                },
            )
        if resp.status_code != 200:
            logger.warning("drm_license_failed", status=resp.status_code, body=resp.text[:300])
            raise AppError("DRM license server rejected the request", code="drm_license_failed")
        return resp.content


class _WidevineProxyProvider:
    async def issue_license(
        self, *, lesson_id: uuid.UUID, user_id: uuid.UUID, license_request: bytes
    ) -> bytes:
        if not settings.DRM_LICENSE_URL:
            raise AppError(
                "widevine_proxy requires DRM_LICENSE_URL pointing at your license proxy",
                code="drm_misconfigured",
            )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.DRM_LICENSE_URL,
                content=license_request,
                headers={"Content-Type": "application/octet-stream"},
            )
        if resp.status_code != 200:
            raise AppError("Widevine proxy rejected the request", code="drm_license_failed")
        return resp.content


def get_provider() -> DRMProvider:
    if settings.DRM_PROVIDER == "ezdrm":
        return _EzDRMProvider()
    if settings.DRM_PROVIDER == "widevine_proxy":
        return _WidevineProxyProvider()
    return _NoOpProvider()
