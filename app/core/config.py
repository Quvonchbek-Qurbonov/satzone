from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ENV: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    PROJECT_NAME: str = "Edure"
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = Field(default_factory=list)

    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    SQL_ECHO: bool = False

    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    EMAIL_VERIFY_EXPIRE_HOURS: int = 48
    # Phone verification — code is currently delivered over email as a stand-in
    # for SMS, so the expiry is shorter than the email-verify link.
    PHONE_VERIFY_EXPIRE_MINUTES: int = 15
    PHONE_VERIFY_MAX_ATTEMPTS: int = 5
    PHONE_CODE_LENGTH: int = 6

    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 120

    MAIL_BACKEND: Literal["console", "smtp", "brevo"] = "console"
    MAIL_FROM: str = "no-reply@edure.local"
    MAIL_FROM_NAME: str = "Edure"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_TLS: bool = True
    BREVO_API_KEY: str | None = None

    FRONTEND_URL: str = "http://localhost:3000"
    API_BASE_URL: str = "http://localhost:8000"

    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    # If unset we derive {API_BASE_URL}{API_V1_PREFIX}/auth/google/callback at runtime.
    GOOGLE_REDIRECT_URI: str | None = None

    # Media uploads (videos, images, resources)
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    MEDIA_ROOT: str = "media"  # local backend
    MEDIA_URL: str = "/media"  # local backend
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_REGION: str | None = None
    AWS_S3_BUCKET: str | None = None
    # When set, served URLs use this base (e.g. CloudFront) instead of presigning.
    AWS_S3_PUBLIC_BASE_URL: str | None = None
    # Lifetime of S3 presigned GET URLs (seconds). Default 1h — short enough that a
    # leaked URL stops working quickly, long enough that page reloads don't churn.
    AWS_S3_URL_TTL_SECONDS: int = 3600

    # Video streaming protection
    # When STORAGE_BACKEND=s3, mirror uploads to MEDIA_ROOT so the streaming proxy
    # can serve from the local box first and fall back to S3.
    STORAGE_DUAL_WRITE: bool = True
    # TTL of the signed token embedded in manifest/segment/key URLs. The
    # token must outlast a full playback session because the manifest bakes
    # it into every segment URI; IP binding (``cip`` claim) compensates for
    # the longer window by making the token non-transferable.
    STREAM_TOKEN_TTL_SECONDS: int = 1800
    # Key-encryption key used to wrap per-lesson AES-128 HLS keys at rest.
    # Generate once: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MEDIA_KEK: str | None = None
    # ffmpeg binary path (override if not on PATH).
    FFMPEG_BIN: str = "ffmpeg"
    # HLS segment length in seconds.
    HLS_SEGMENT_SECONDS: int = 6
    # Auto-package on lesson video upload. Disable to package out-of-band.
    HLS_AUTO_PACKAGE: bool = True

    # DRM (Widevine/FairPlay/PlayReady) — provider integration point.
    # "none" disables DRM. Other values require a paid license server (ezDRM,
    # Bitmovin, AWS MediaPackage, etc.); plug credentials into app/utils/drm.py.
    DRM_PROVIDER: Literal["none", "ezdrm", "widevine_proxy"] = "none"
    DRM_LICENSE_URL: str | None = None
    DRM_API_KEY: str | None = None

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, v: object) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return [str(o).strip() for o in json.loads(v)]
            return [o.strip() for o in v.split(",") if o.strip()]
        if isinstance(v, list):
            return [str(o) for o in v]
        raise TypeError(f"Invalid CORS origins value: {v!r}")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SYNC_DATABASE_URL(self) -> str:
        dsn = PostgresDsn.build(
            scheme="postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        dsn = RedisDsn.build(
            scheme="redis",
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            path=str(self.REDIS_DB),
        )
        url = str(dsn)
        if auth:
            url = url.replace("redis://", f"redis://{auth}", 1)
        return url

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()