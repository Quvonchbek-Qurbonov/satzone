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
| Auth               | `POST /auth/register`, `/login`, `/refresh`, `/logout`, `/verify-email`, `/resend-verification`, `/password/forgot`, `/password/reset`, `GET /auth/me` |
| Onboarding         | `GET/PUT /onboarding`                                                                          |
| Home               | `GET /home` (personalized when token provided)                                                 |
| Explore            | `GET /courses` (filters: search, category_id/slug, instructor_id, level, is_free, min_rating, duration, tags, sort), `GET /categories`, `GET /categories/tree`, `GET /instructors`, `GET /instructors/{slug}` |
| Course detail      | `GET /courses/{slug}`, `/curriculum`, `/related`, `/reviews` (list/create/update/delete)        |
| My Learnings       | `POST /me/enrollments`, `GET /me/enrollments`, `PUT .../lessons/{lesson_id}/progress`, `GET /me/certificates`, `/me/wishlist` |
| Degree (Programs)  | `GET /programs`, `GET /programs/{slug}`, `POST /programs/{id}/enroll`, `GET /me/programs`       |
| Account & Settings | `GET/PATCH/DELETE /me`, `PUT /me/password`, `GET/PATCH /me/preferences/notifications`, `GET/DELETE /me/sessions` |
| Admin              | `/admin/users`, `/admin/categories`, `/admin/instructors`, `/admin/courses`, `/admin/programs` (+ `/programs/{id}/courses` linking), `/admin/reviews`, `/admin/enrollments`, `/admin/certificates` — full CRUD + lifecycle (`publish`/`unpublish`/`archive`) + media uploads. All routes gated by `role=admin`. |

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
