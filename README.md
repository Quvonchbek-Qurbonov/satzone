# Edure backend

Production-ready FastAPI backend powering the Edure learning platform (Sign Up, Onboarding,
Homepage, Explore, Detail Course, My Learnings, Degree, Account & Settings).

## Stack

- **Python 3.13**, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic
- **PostgreSQL 16**, **Redis 7**
- Argon2 password hashing, JWT access + opaque rotating refresh tokens
- Structured logging (structlog), per-request IDs, sliding-window rate limit
- Pluggable email backend (console for dev, SMTP/Brevo for prod)
- Pluggable media storage (local disk for dev, AWS S3 with presigned URLs for prod)
- Protected video streaming: auth-gated byte-range proxy + HLS/AES-128 packaging + DRM seam

## Layout

```
app/
  api/v1/            FastAPI routers per section (auth, onboarding, home, courses, ...)
  core/              config, security, logging, errors, pagination
  db/                async engine + session
  middleware/        request-id, rate-limit
  models/            SQLAlchemy models
  schemas/           Pydantic v2 request/response models
  services/          business logic (auth, course, enrollment, program, home, onboarding)
  utils/             email
alembic/             migrations
scripts/seed.py      sample data
tests/               pytest + httpx smoke tests
```

## Run with Docker (recommended)

```bash
cp .env.example .env
# REQUIRED — replace JWT_SECRET_KEY with a strong value:
#   python -c "import secrets; print(secrets.token_hex(32))"

docker compose up --build -d

# Apply migrations
docker compose exec api alembic upgrade head

# Seed sample data (optional but recommended)
docker compose exec api python -m scripts.seed
```

API root: <http://localhost:8000>
OpenAPI docs: <http://localhost:8000/docs>

## Run locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Bring up Postgres + Redis only
docker compose up -d db redis

cp .env.example .env  # set POSTGRES_HOST=localhost, REDIS_HOST=localhost

alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

## API surface (v1, `/api/v1`)

| Section            | Endpoints                                                                                      |
| ------------------ | ---------------------------------------------------------------------------------------------- |
| Auth               | `POST /auth/register`, `/login`, `/refresh`, `/logout`, `/verify-email`, `/resend-verification`, `/phone`, `/verify-phone`, `/resend-phone-code`, `/password/forgot`, `/password/reset`, `GET /auth/me` |
| Onboarding         | `GET/PUT /onboarding`                                                                          |
| Home               | `GET /home` (personalized when token provided)                                                 |
| Explore            | `GET /courses` (filters: search, category_id/slug, instructor_id, level, is_free, min_rating, duration, tags, sort), `GET /categories`, `GET /categories/tree`, `GET /instructors`, `GET /instructors/{slug}` |
| Course detail      | `GET /courses/{slug}`, `/curriculum`, `/related`, `/reviews` (list/create/update/delete)        |
| My Learnings       | `POST /me/enrollments`, `GET /me/enrollments`, `PUT .../lessons/{lesson_id}/progress`, `GET /me/certificates`, `/me/wishlist` |
| Degree (Programs)  | `GET /programs`, `GET /programs/{slug}`, `POST /programs/{id}/enroll`, `GET /me/programs`       |
| Account & Settings | `GET/PATCH/DELETE /me`, `POST/DELETE /me/avatar` (multipart image upload), `PUT /me/password`, `GET/PATCH /me/preferences/notifications`, `GET/DELETE /me/sessions`, `GET /me/activity/weekly`, `PUT /me/activity/weekly-goal` |
| Notes              | `POST /me/notes`, `GET /me/notes` (filter `lesson_id`/`course_id`), `PATCH/DELETE /me/notes/{id}` |
| Downloads          | `GET /lessons/{id}/attachments`, `POST/GET /me/downloads`, `DELETE /me/downloads/{id}` (resource files only — videos stay HLS-streamed) |
| Payments           | `GET/POST /me/payment-methods`, `POST /me/payment-methods/{id}/verify/start`, `POST /me/payment-methods/{id}/verify/confirm`, `DELETE /me/payment-methods/{id}`, `POST /orders`, `GET /orders/{id}`, `DELETE /orders/{id}`, `POST /orders/{id}/pay/card`, `POST /orders/{id}/pay/payme`, `GET /me/orders`, `POST /payments/payme/callback` (Payme JSON-RPC) |
| Admin              | `/admin/users`, `/admin/categories`, `/admin/instructors`, `/admin/courses`, `/admin/programs` (+ `/programs/{id}/courses` linking), `/admin/reviews`, `/admin/enrollments`, `/admin/certificates` — full CRUD + lifecycle (`publish`/`unpublish`/`archive`) + media uploads. All routes gated by `role=admin`. |

## Video streaming protection

Lesson videos are **HLS-only with AES-128 segment encryption**. There is no
direct-MP4 endpoint for lessons because plain MP4 over HTTP is trivially
downloadable. A `curl` of any signed URL gives you encrypted bytes that
require both the per-lesson content key (auth-gated) and a valid
IP-bound playback token to decrypt.

1. **HLS + AES-128.** Every uploaded lesson video is repackaged with ffmpeg into encrypted HLS in the background (`HLS_AUTO_PACKAGE=true`). The manifest endpoint rewrites segment + key URIs on each request to signed paths under our domain; the 16-byte content key is wrapped at rest with a Fernet key (`MEDIA_KEK`) and only handed out by `GET /lessons/{id}/hls/key?t=…` to a holder of a valid playback token. Generate the KEK once with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. **IP-bound playback tokens.** `GET /lessons/{id}/playback` (Bearer auth) mints a JWT that bakes the requester's IP (`cip` claim) and expires after `STREAM_TOKEN_TTL_SECONDS` (default 1800 — long enough for full playback, short enough to limit damage). Every manifest, segment, and key request re-verifies both the IP and the bound resource. A token shared with another network returns 401.
3. **DRM (Widevine / FairPlay / PlayReady).** A `POST /lessons/{id}/drm/license` proxy is wired to forward binary EME challenges to the provider configured by `DRM_PROVIDER`. A real provider (ezDRM, Bitmovin, AWS MediaPackage…) requires a paid license server — leave `DRM_PROVIDER=none` until you have one.

The layers are honest about their limits: no protection prevents a determined user from screen-recording playback. The goal is to make casual download impossible and scripted download annoying enough that only DRM-tier protection matters beyond it.

| Endpoint | Purpose |
| -------- | ------- |
| `GET /lessons/{id}/playback` | Mint IP-bound `hls_url` (Bearer auth, enrollment / preview / owner check) |
| `GET /lessons/{id}/hls/master.m3u8?t=…` | HLS manifest with rewritten signed URIs |
| `GET /lessons/{id}/hls/seg/{name}?t=…` | Encrypted segment (server first, S3 fallback) |
| `GET /lessons/{id}/hls/key?t=…` | Plaintext AES-128 content key (after Fernet unwrap) |
| `POST /lessons/{id}/drm/license` | DRM license proxy (configure `DRM_PROVIDER`) |
| `GET /courses/{slug}/preview-playback` + `/courses/{id}/preview-stream?t=…` | Course preview video — direct MP4 (marketing content, intentionally watchable) |

## Payments (Payme + card-on-file)

Course / program purchases run through a small order-then-pay flow. Both
payment methods talk to **Payme (Uzbekistan)** under the hood — there is no
direct PAN storage on this server.

```
POST /orders                                    # create pending order
POST /me/payment-methods                        # save a card → Payme cards.create → token
POST /me/payment-methods/{id}/verify/start      # Payme cards.get_verify_code (OTP)
POST /me/payment-methods/{id}/verify/confirm    # Payme cards.verify
POST /orders/{id}/pay/card                      # synchronous: receipts.create + receipts.pay
POST /orders/{id}/pay/payme                     # async hosted checkout: returns checkout_url
POST /payments/payme/callback                   # Merchant API JSON-RPC (Basic Paycom:<key>)
```

Set `PAYME_MERCHANT_ID` and `PAYME_KEY` in `.env`. Without them, every
`pay/*` endpoint returns `502 payment_provider_unconfigured`. Default
`PAYME_TEST_MODE=true` hits the sandbox — flip it off for production.

When the order flips to `paid` (synchronously for card-on-file, or via
`PerformTransaction` for the hosted flow) the user is auto-enrolled in the
purchased course / program. Programs additionally enroll the user in every
required course, exactly as `POST /programs/{id}/enroll` does for the free
path.

## Observability

`docker compose up -d` brings up four extra services for metrics, logs, and dashboards:

| Service | URL | Notes |
| ------- | --- | ----- |
| Prometheus | <http://localhost:9090> | Scrapes `satzone-api:8000/metrics` every 15 s, 15 d retention |
| Loki | <http://localhost:3100> | Receives logs shipped by Promtail, 7 d retention |
| Promtail | (no UI) | Tails Docker JSON logs, parses structlog, ships to Loki |
| Grafana | <http://localhost:3001> | `admin` / `admin` (override via `GRAFANA_USER`/`GRAFANA_PASSWORD`) |

Grafana auto-provisions both data sources and a starter dashboard ("Satzone — Streaming Overview") covering request rate, p95/p99 latency, playback-token issuance/rejection, HLS local-vs-S3 cache hit ratio, packaging in-flight + duration, and a live tail of error/warning logs from Loki.

The API exposes both default HTTP metrics (request count, duration histogram by handler) and streaming-specific counters defined in `app/core/metrics.py`. Add new dashboards by dropping JSON into `ops/grafana/dashboards/` — Grafana picks them up within 30 s without a restart.

Logs ship as JSON because `LOG_JSON=true`; Promtail promotes `level`, `event`, `request_id`, `method`, `path`, `status_code` to Loki labels so you can filter in Grafana with `{service="api"} | json | level="error"`.

## Auth model

- **Access token** (JWT, 15 min) — sent as `Authorization: Bearer <token>`.
- **Refresh token** — opaque random string, hashed (SHA-256) at rest.
  - Rotated on every `/auth/refresh` call.
  - Reuse detection: if a revoked token is presented, **all** of that user's refresh tokens are revoked.
  - Revoked on logout, password change, password reset.

## Migrations

```bash
# Create new revision
alembic revision -m "add foo to bar"

# Autogenerate from model diff (requires DB up to date)
alembic revision --autogenerate -m "...."

alembic upgrade head
alembic downgrade -1
```

## Tests

```bash
pytest
```

Smoke tests need live Postgres + Redis; bring them up via `docker compose up -d db redis` first.
The auth smoke test self-skips if the DB isn't migrated.

## Production checklist

- [ ] Set a strong `JWT_SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] Set `ENV=production`, `DEBUG=false`, `LOG_JSON=true`
- [ ] Set `MAIL_BACKEND=brevo` (+ `BREVO_API_KEY`, `MAIL_FROM`, `MAIL_FROM_NAME`) or `MAIL_BACKEND=smtp` and configure SMTP_*
- [ ] Set `STORAGE_BACKEND=s3` and configure `AWS_*` (bucket should keep "Block all public access" — the API serves via presigned URLs); add CloudFront in front and set `AWS_S3_PUBLIC_BASE_URL` for cheap streaming
- [ ] Restrict `BACKEND_CORS_ORIGINS` to known frontend hosts
- [ ] Run behind a reverse proxy that sets `X-Forwarded-For` (rate limiter relies on it)
- [ ] Use a managed Postgres + Redis with backups
- [ ] Add a real worker (`arq` recommended) when adding heavy background work
