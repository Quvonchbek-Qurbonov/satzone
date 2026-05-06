from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer

# Field names whose values are stored as opaque media-storage keys (not URLs).
# At serialization time they're resolved to a fresh URL — presigned for S3, or
# the static-media URL for local. Absolute URLs already in the value pass
# through unchanged, so seed data and external avatars keep working.
_MEDIA_FIELDS = (
    "avatar_url",
    "thumbnail_url",
    "preview_video_url",
    "video_url",
    "resource_url",
    "icon_url",
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer(*_MEDIA_FIELDS, check_fields=False, when_used="json")
    def _serialize_media_url(self, value: str | None) -> str | None:
        # Local import to avoid a circular pull (storage → config → ...).
        from app.utils.storage import media_url

        return media_url(value)


class Message(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail