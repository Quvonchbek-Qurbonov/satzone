# Edure Backend — Frontend Integration Guide

A self-contained reference for the frontend (web/mobile) team. Read this before
wiring API calls; it covers the conventions every endpoint follows, the auth
loop, the streaming flow, and the section-by-section endpoint contracts.

The OpenAPI spec at `GET /api/v1/openapi.json` (Swagger UI at
`http://localhost:8000/docs`) is authoritative — this doc explains the *shapes
the schema doesn't show*: the auth dance, refresh rotation, the HLS/DRM flow,
which fields are media keys vs URLs, and the gotchas that matter when building
a UI.

---

## 1. Base URL, environments, CORS

| Env | Default base URL |
| --- | ---------------- |
| Local Docker | `http://localhost:8000` |
| API prefix   | `/api/v1` (everything below is relative to this) |
| Static media | `/media/...` (only when `STORAGE_BACKEND=local`) |

Add your dev origin to `BACKEND_CORS_ORIGINS` in the backend `.env` or you'll
hit CORS errors. The defaults already include `http://localhost:3000` and
`http://localhost:5173`. `expose_headers=["X-Request-ID"]` is set so you can
read the request ID from any response.

---

## 2. Auth model

### Tokens

- **Access token** — JWT, default 15-minute TTL, sent as
  `Authorization: Bearer <access_token>` on every authenticated request.
- **Refresh token** — opaque random string (10–200 chars), 30-day TTL, **rotated
  on every successful `/auth/refresh`**.

The `TokenResponse` shape:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "f3c2...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### Storage

- Web: refresh in `httpOnly`, `Secure`, `SameSite=Lax` cookie if you can; otherwise
  IndexedDB. Never `localStorage` for the refresh token in production.
- Access token can live in memory (preferred) or `sessionStorage`.

### Refresh loop (must implement)

1. Send the request with the current access token.
2. On `401` with `error.code` in `{"missing_token", "invalid_token", "invalid_user"}`:
   - Call `POST /auth/refresh` with the refresh token in the **body**.
   - Replace **both** access and refresh tokens with the new pair (rotation —
     the old refresh is now revoked).
   - Retry the original request **once**.
3. If `/auth/refresh` itself returns `401` with `code=token_reuse` or
   `invalid_refresh_token` or `refresh_expired` → wipe state and send the user
   to `/login`. `token_reuse` means **all of that user's refresh tokens have
   been revoked**; do not retry.

Concurrency: if multiple in-flight requests 401 at once, gate them on a single
shared "refreshing" promise so you don't burn through refresh tokens.

### Email verification gate

Newly registered users **must verify their email before they can log in**.
`POST /auth/login` returns `401 email_not_verified` until they click the
verification link. Show a "resend verification email" affordance pointing at
`POST /auth/resend-verification`.

Registration itself returns `202 Accepted` with a generic message — there's no
user record until the verify link is redeemed. Treat success as "go check your
inbox."

### Phone verification (post-login, hard gate on the rest of the API)

Phone is **not** part of registration. Users register with email/password,
verify email, log in — and *then* every other authenticated endpoint
returns `403 phone_not_verified` until they complete the phone-verify step.
Three endpoints are deliberately reachable while the gate is active so the
frontend can drive the flow:

- `GET /auth/me` — read current state (`is_phone_verified`).
- `POST /auth/phone` — set/replace the phone number; sends a 6-digit code.
- `POST /auth/verify-phone` — submit the code.
- `POST /auth/resend-phone-code` — rotate the code.

End-to-end:

1. **Register** `{email, full_name, password}` → 202.
2. **Verify email** (link from inbox, or `POST /auth/verify-email`) → real
   user created.
3. **Login** → tokens. `UserMe.is_phone_verified === false`.
4. **Hit any non-phone authed endpoint** → `403 phone_not_verified`.
   Treat this code as "redirect to verify-phone screen", not as a logout.
5. **`POST /auth/phone {phone_number}`** (Bearer auth) → the number and a
   freshly-minted 6-digit code are staged in Redis (TTL 15 min); nothing is
   written to the user record yet. **The code is sent as an SMS to the
   submitted number** (Brevo or Infobip transactional SMS) — show copy like
   "We've sent a verification code to your phone." In environments where
   `USE_SMS_PROVIDER=false` (typical for local dev) the same code is
   emailed to the user's account email instead — the API response is
   identical, so the frontend doesn't branch. Re-callable to fix typos
   until verified — each call replaces the staged number and resets the
   attempt counter.
6. **`POST /auth/verify-phone {code}`** (Bearer auth) → on match, the staged
   number is committed to `users.phone_number` and `is_phone_verified=true`.
   The rest of the API is now unblocked. If the staged entry has expired or
   doesn't exist, you get `invalid_phone_code` — bounce them back to the
   phone-input step.
7. **`POST /auth/resend-phone-code`** (Bearer auth, no body) when the user
   asks for a new code. Rotates the code on the same staged number; the
   previous code stops working. If the Redis entry has lapsed (TTL hit),
   you get `phone_not_submitted` — drive them back to step 5.

Google OAuth users land in the same gate: no phone on file, so any first
authenticated call returns `phone_not_verified`. Route them through the
same verify-phone flow.

Phone-verify error codes:

| HTTP | code | When |
| ---- | ---- | ---- |
| 403  | `phone_not_verified` | Catch globally — redirect to verify-phone screen, do NOT logout |
| 409  | `phone_already_verified` | Idempotent hint; stop showing the screen |
| 409  | `phone_taken` | Another verified user owns the number — show inline error on the phone field |
| 422  | `phone_not_submitted` | User hit verify/resend before submitting a phone — drive them back to the input step |
| 422  | `invalid_phone_code` | Wrong / expired code — keep messaging vague |
| 422  | `phone_code_attempts_exceeded` | 5 wrong tries — force "request a new code" |

### Google OAuth

The **redirect** flow lives entirely on the backend:

1. Frontend opens `GET /api/v1/auth/google/login` in a top-level navigation
   (not XHR). The backend issues a 307 to Google.
2. After consent, Google calls `/auth/google/callback`, the backend mints
   tokens, then renders an HTML page that redirects to:
   ```
   ${FRONTEND_URL}/auth/google/callback#access_token=...&refresh_token=...&expires_in=...
   ```
3. Implement `/auth/google/callback` in your app: read `window.location.hash`,
   stash the tokens, redirect to the home page. Do **not** keep the tokens in
   the URL — clear the hash with `history.replaceState` immediately.

If `code=oauth_only` comes back from `/auth/login`, route the user to the
"Sign in with Google" button instead of the password form — that account has
no password set.

---

## 3. Cross-cutting conventions

### Error envelope

Every non-2xx response is shaped the same way:

```json
{
  "error": {
    "code": "not_enrolled",
    "message": "You must be enrolled to review this course",
    "details": null
  }
}
```

- `error.code` is a stable machine-readable string. Branch UI on this, not on
  `message` (which is human prose and may be reworded).
- `error.details` carries Pydantic field errors for `validation_error` (HTTP
  422) — render them inline next to form fields. Shape:
  `[{loc: ["body","email"], msg: "value is not a valid email", type: "value_error.email"}, ...]`.

Common error codes to handle by name:

| HTTP | code | When |
| ---- | ---- | ---- |
| 400  | `app_error` | Generic |
| 401  | `missing_token` / `invalid_token` / `invalid_user` | Trigger refresh loop |
| 401  | `invalid_credentials` | Login failed |
| 401  | `email_not_verified` | Show "resend verification" |
| 401  | `oauth_only` | Account uses Google |
| 401  | `account_disabled` | Hard stop |
| 401  | `invalid_refresh_token` / `refresh_expired` / `token_reuse` | Force re-login |
| 403  | `forbidden` | Generic (e.g. wrong role) |
| 403  | `email_not_verified` | Verification gate on a non-auth route |
| 403  | `phone_not_verified` | Redirect to verify-phone screen — applies to ALL authed endpoints except `GET /auth/me` and `/auth/phone*` |
| 403  | `not_enrolled` | Show "Enroll" CTA |
| 403  | `instructor_role_required` | Hide instructor UI |
| 404  | `not_found`, `*_not_found` | 404 page or empty state |
| 409  | `email_taken`, `review_exists`, `course_in_program`, ... | Inline conflict UI |
| 422  | `validation_error` | Field-level form errors (see `details`) |
| 429  | `rate_limited` | Back off; show a toast |
| 500  | `internal_error`, `database_error` | Generic "something went wrong" |

### Pagination

Any list endpoint that takes `?page=&size=` returns:

```json
{
  "items": [...],
  "total": 137,
  "page": 1,
  "size": 20,
  "pages": 7
}
```

- `page` is 1-based. Default 1.
- `size` defaults to 20, max 100.
- `pages` is 0 when `total=0` — guard against that in pager UI.

### Request IDs

Every response carries an `X-Request-ID` header. When a user reports a bug,
capture it — it's the join key for every log line on the backend (Loki labels
include `request_id`).

You can pin a request ID by sending the header in; otherwise the server makes
one. Useful for correlating front+back logs on a complex action.

### Rate limits

- Default: **120 requests / minute / IP**.
- Auth endpoints (`/auth/*`): **10 / minute / IP / path**.

When you hit `429 rate_limited`, the response includes
`error.details = {"limit": 120, "window_seconds": 60}`. Implement exponential
backoff with jitter; don't hammer.

### IDs and slugs

- Resource IDs are UUIDs (string, with hyphens).
- Catalog resources (courses, programs, instructors, categories) also have a
  `slug`. Detail endpoints accept the slug:
  `GET /courses/{slug}`. List filters take the **id**: `?category_id=...`.
- The `Page<T>` total counts items, not pages.

### Date/time

All timestamps are **UTC ISO 8601** with offset, e.g.
`"2026-05-07T14:23:00+00:00"`. Convert to local time at render.

### Languages / locale

The backend captures the user's preferred language but does **not** translate
content yet — every catalog string (course titles, descriptions, category
names, lesson titles, etc.) is returned as-is, English by default. The
frontend handles its own UI translations.

- **Storage**: `user_profiles.locale` (string, max 10 chars, default `"en"`).
  Read it from `GET /onboarding` (`profile.locale`).
- **Update**: `PUT /onboarding` with `{locale: "uz"}` (or any BCP-47-ish
  short code your UI uses) — this is what onboarding's locale step writes.
- **Default**: `"en"` until the user picks something else.
- **Outbound content**: backend emails (verify, password reset) and the
  phone-code SMS are English-only today; localized copy will be added when
  content i18n lands.

When content translations land later, the existing `locale` value will drive
which translation gets returned — same field, no migration required on the
client. Until then, treat it purely as a UI-language hint.

### Money

- `price_cents` and `discount_price_cents` are integers (USD cents by default).
- `currency` is an ISO 4217 code (`"USD"`, `"EUR"`, ...).
- `is_free` (computed boolean on `CourseSummary`) is `true` when the effective
  price (discount or list) is `0`. Trust this rather than recomputing.

### Media URL handling

- Fields named `avatar_url`, `thumbnail_url`, `resource_url`, `icon_url` come
  back as **already-resolved absolute URLs** when serialized to JSON. With
  `STORAGE_BACKEND=local` they point at `/media/...`; with S3 they're presigned
  GETs (default 1-hour TTL).
- A pre-signed S3 URL **expires** — do not cache it across the TTL. If you
  show the same image for hours (e.g. a thumbnail in a long-running tab),
  re-fetch the parent resource to get a fresh URL.
- `video_url` and `preview_video_url` are **never** returned. To play any video
  you must hit a `/playback` endpoint and use the signed `hls_url` /
  `stream_url` that comes back. See §5.

### Enums

All enums are lowercase strings:

| Enum | Values |
| ---- | ------ |
| `UserRole` | `user`, `instructor`, `admin` |
| `SkillLevel` | `beginner`, `intermediate`, `advanced` |
| `CourseLevel` | `beginner`, `intermediate`, `advanced`, `all_levels` |
| `PublishStatus` | `draft`, `published`, `archived` |
| `LessonType` | `video`, `article`, `quiz`, `resource` |
| `QuestionType` | `single_choice`, `multi_choice`, `true_false`, `short_answer` |
| `AssessmentStatus` | `draft`, `published`, `archived` |
| `HlsStatus` | `pending`, `ready`, `failed` |

---

## 4. Endpoints by section

All paths below are prefixed with `/api/v1`. "Auth: required" means a Bearer
access token is needed.

### 4.1 Auth (`/auth`)

| Method & path | Auth | Body | Returns | Notes |
| --- | --- | --- | --- | --- |
| `POST /auth/register` | – | `{email, full_name, password (min 8)}` | 202 `{message}` | Sends verify email; no user row yet |
| `POST /auth/login` | – | `{email, password}` | `TokenResponse` | 401 `email_not_verified` until verified |
| `POST /auth/refresh` | – | `{refresh_token}` | `TokenResponse` | Rotates both tokens |
| `POST /auth/logout` | – | `{refresh_token}` | `{message}` | Idempotent |
| `POST /auth/verify-email` | – | `{token}` | `{message}` | Token from email link |
| `POST /auth/resend-verification` | – | `{email}` | `{message}` | Always 200 (no enumeration) |
| `POST /auth/phone` | ✓ | `{phone_number}` | `{message}` | Stages number in Redis, SMSes 6-digit code |
| `POST /auth/verify-phone` | ✓ | `{code}` | `{message}` | Marks `is_phone_verified` |
| `POST /auth/resend-phone-code` | ✓ | – | `{message}` | Rotates the in-flight code |
| `POST /auth/password/forgot` | – | `{email}` | `{message}` | Always 200 (no enumeration) |
| `POST /auth/password/reset` | – | `{token, new_password}` | `{message}` | Revokes all refresh tokens |
| `GET  /auth/me` | ✓ | – | `UserMe` | Same payload as `GET /me` |
| `GET  /auth/google/login` | – | redirect | – | Top-level nav |
| `GET  /auth/google/callback` | – | HTML | – | Backend-rendered handoff page |

`UserMe` shape:
```ts
{
  id: string, email: string, full_name: string,
  phone_number: string | null,
  avatar_url: string | null,
  role: "user" | "instructor" | "admin",
  is_active: boolean, is_verified: boolean, is_phone_verified: boolean,
  email_verified_at: string | null,
  phone_verified_at: string | null,
  onboarding_completed_at: string | null,
  last_login_at: string | null,
  created_at: string
}
```

### 4.2 Account & settings (`/me`)

| Method & path | Body | Returns | Notes |
| --- | --- | --- | --- |
| `GET /me` | – | `UserMe` | |
| `PATCH /me` | `{full_name?, avatar_url?}` | `UserMe` | Partial update |
| `DELETE /me` | – | 204 | Soft-deactivates + scrubs PII; revokes refresh tokens |
| `PUT /me/password` | `{current_password, new_password}` | `{message}` | 401 `invalid_credentials` if wrong |
| `GET /me/preferences/notifications` | – | `NotificationPreferenceSchema` | Auto-creates default row |
| `PATCH /me/preferences/notifications` | partial | `NotificationPreferenceSchema` | |
| `GET /me/sessions` | – | `[{id, user_agent, ip_address, created_at, expires_at}]` | Active refresh tokens |
| `DELETE /me/sessions/{id}` | – | 204 | Revoke one device |
| `DELETE /me/sessions` | – | 204 | Revoke every device (forces re-login everywhere) |

### 4.3 Onboarding (`/onboarding`)

| Method & path | Body | Returns |
| --- | --- | --- |
| `GET /onboarding` | – | `{profile, interests: Category[], onboarding_completed}` |
| `PUT /onboarding` | `OnboardingUpdate` | same |

`OnboardingUpdate`:
```ts
{
  headline?, bio?,
  skill_level?: "beginner"|"intermediate"|"advanced",
  weekly_goal_minutes?: 0..10000,
  learning_goal?, locale?, timezone?,
  interest_category_ids?: string[],   // replaces the set
  mark_completed?: boolean             // sets onboarding_completed_at on PUT
}
```

Set `mark_completed: true` on the final wizard step. After that,
`UserMe.onboarding_completed_at` is non-null — gate the "Continue onboarding"
banner on that.

### 4.4 Home feed (`/home`)

`GET /home` — auth optional. When no token is sent, `continue_learning` is `[]`
and `recommended` falls back to popularity. Returns:

```ts
{
  continue_learning: Enrollment[],
  recommended: CourseSummary[],
  featured: CourseSummary[],
  popular: CourseSummary[],
  new_courses: CourseSummary[],
  categories: Category[],
  programs: ProgramSummary[]
}
```

Single round-trip — render the whole landing page from this.

### 4.5 Catalog (Explore)

#### Categories

- `GET /categories` → flat list (`Category[]`)
- `GET /categories/tree` → nested (`CategoryTreeNode[]` with `children`)

#### Instructors

- `GET /instructors?page=&size=&search=` → `Page<InstructorSummary>`
- `GET /instructors/{slug}` → `InstructorRead` (adds bio, expertise, socials)

#### Courses (list & detail)

- `GET /courses` — query params:
  - `search` (string, max 100)
  - `category_id` (uuid) **or** `category_slug` (string)
  - `instructor_id` (uuid)
  - `level` ∈ `beginner|intermediate|advanced|all_levels`
  - `is_free` (bool)
  - `min_rating` (0..5, float)
  - `min_duration_minutes`, `max_duration_minutes` (int)
  - `tags` (repeat the param: `?tags=python&tags=ml`)
  - `sort` ∈ `popular|newest|rating|price_asc|price_desc` (default `popular`)
  - `page`, `size`
- `GET /courses/{slug}` → `CourseDetail`
- `GET /courses/{slug}/curriculum` → sections + lessons + totals
- `GET /courses/{slug}/related` → up to N related `CourseSummary[]`
- `GET /courses/{slug}/reviews?page=&size=` → `Page<ReviewRead>`
- `POST /courses/{slug}/reviews` (auth, must be enrolled) — `{rating: 1..5, comment?}`. 409 `not_enrolled` or `review_exists`.
- `PUT /courses/{slug}/reviews/me` — partial update
- `DELETE /courses/{slug}/reviews/me` — 204

`CourseDetail` adds (over `CourseSummary`):
```ts
{
  description, has_preview_video, preview_playback_url,
  learning_outcomes: string[]|null, requirements: string[]|null,
  target_audience: string[]|null, tags: string[]|null,
  status, published_at
}
```

`preview_playback_url` is the relative path you `GET` (with bearer auth) to mint
a preview stream URL — see §5.2.

`CurriculumRead` lessons are `LessonSummary` (no `playback_url` for the public
curriculum). To play a lesson you call `GET /lessons/{id}/playback` directly —
see §5.

### 4.6 Enrollments / My learnings

| Method & path | Body | Returns | Notes |
| --- | --- | --- | --- |
| `POST /me/enrollments` | `{course_id}` | `EnrollmentRead` | 201 |
| `GET /me/enrollments?status=all|active|completed&page=&size=` | – | `Page<EnrollmentRead>` | |
| `GET /me/enrollments/{id}` | – | `EnrollmentRead` | |
| `PUT /me/enrollments/{id}/lessons/{lesson_id}/progress` | `LessonProgressUpdate` | `LessonProgressRead` | Hit on every player tick or on visibility change |
| `GET /me/wishlist?page=&size=` | – | `Page<WishlistItemRead>` | |
| `POST /me/wishlist/{course_id}` | – | `{message}` | 201 |
| `DELETE /me/wishlist/{course_id}` | – | 204 | |
| `GET /me/certificates` | – | `CertificateRead[]` | |
| `GET /me/certificates/courses/{course_id}` | – | `CertificateRead` | 404 if not earned yet |

`LessonProgressUpdate`:
```ts
{ last_position_seconds?, watched_seconds?, completed?: boolean }
```
Send all three when you can — server uses them to compute course
`progress_percent`. When the **last** lesson is marked `completed: true`, the
server issues a certificate automatically; you'll find it under
`/me/certificates`.

Throttle progress writes — once every 10 s during playback is plenty; flush
on pause / unmount / `visibilitychange`.

### 4.7 Programs (Degree)

| Method & path | Auth | Returns |
| --- | --- | --- |
| `GET /programs?page=&size=` | – | `Page<ProgramSummary>` |
| `GET /programs/{slug}` | – | `ProgramDetail` (with ordered course list) |
| `POST /programs/{program_id}/enroll` | ✓ | `ProgramEnrollmentRead` (201) |
| `GET /me/programs?page=&size=` | ✓ | `Page<ProgramEnrollmentRead>` |

### 4.8 Assessments (student-facing)

| Method & path | Returns | Notes |
| --- | --- | --- |
| `GET /assessments/{id}` | `AssessmentStudentRead` | 403 if not enrolled / not published |
| `POST /assessments/{id}/submissions` | `AssessmentSubmissionRead` (201) | Body: `{answers: SubmissionAnswerWrite[]}` |
| `GET /assessments/{id}/submissions/me` | `AssessmentSubmissionRead[]` | History |

`SubmissionAnswerWrite`:
```ts
{
  question_id: string,
  selected_option_ids?: string[],   // for single/multi/true-false
  text?: string                     // for short_answer
}
```

`QuestionStudentRead` deliberately omits `is_correct` on options. Don't try to
reconstruct it — show the answer key only after submission, and only if
`show_correct_answers: true` on the assessment.

Score is server-computed: `score_percent`, `passed` (vs `pass_percent`), per-
answer `awarded_points` and `is_correct`.

### 4.9 Instructor management (`/instructor`, role: instructor or admin)

All routes return `403 instructor_role_required` for plain users.

- **Profile** — `GET/PUT/PATCH /instructor/me/profile`,
  `POST /instructor/me/profile/avatar` (multipart, field name `file`)
- **Courses** — `GET /instructor/courses?page=&size=&status=&search=`,
  `POST /instructor/courses` (`CourseCreate`),
  `GET/PATCH/DELETE /instructor/courses/{course_id}`,
  `POST .../publish`, `POST .../unpublish`, `POST .../archive`,
  `POST .../thumbnail` (multipart), `POST .../preview-video` (multipart)
- **Sections** — `GET/POST /instructor/courses/{course_id}/sections`,
  `POST .../sections/reorder` (`{items: [{id, order}]}`),
  `PATCH/DELETE /instructor/sections/{section_id}`
- **Lessons** — `GET/POST /instructor/sections/{section_id}/lessons`,
  `POST .../lessons/reorder`,
  `PATCH/DELETE /instructor/lessons/{lesson_id}`,
  `POST /instructor/lessons/{lesson_id}/video` (multipart, optional
  `duration_seconds` form field) — kicks off background HLS packaging,
  `POST /instructor/lessons/{lesson_id}/resource` (multipart)
- **Students / analytics** — `GET /instructor/courses/{course_id}/students`,
  `GET /instructor/courses/{course_id}/analytics`
- **Assessments** — `GET/POST /instructor/courses/{course_id}/assessments`,
  `GET/PATCH/DELETE /instructor/assessments/{id}`,
  `POST /instructor/assessments/{id}/questions`,
  `PATCH/DELETE /instructor/questions/{id}`,
  `GET /instructor/assessments/{id}/submissions`

After a video upload, `LessonAdminRead.hls_status` will be `pending`. Poll the
lesson (or just refetch the section) every few seconds — it transitions to
`ready` (or `failed`). Don't surface `playback_url` until `ready`.

### 4.10 Admin (`/admin`, role: admin)

Full CRUD + lifecycle for users, categories, instructors, courses, programs,
program-course links, reviews, enrollments, certificates. See OpenAPI for the
exact shapes — they all follow the same patterns:

- List endpoints take `page`, `size`, plus resource-specific filters.
- `POST .../publish` / `unpublish` / `archive` are lifecycle transitions.
- `POST .../feature` / `unfeature` toggles `is_featured` on courses.
- File uploads are multipart with field name `file`.

### 4.11 Health

- `GET /health` → `{status: "ok"}` (liveness)
- `GET /ready` → `{status: "ready"|"degraded", db, redis}` (readiness, checks
  Postgres + Redis)

These are unauthenticated and rate-limited only at the default tier — fine for
a status badge.

---

## 5. Video & DRM

This is the part of the API most likely to bite you. Read it.

### 5.1 Lesson playback (HLS-only, AES-128)

There is **no direct-MP4 endpoint for lessons**. To play a lesson:

1. **Mint a playback token.**
   ```
   GET /api/v1/lessons/{lesson_id}/playback
   Authorization: Bearer <access_token>
   ```
   Response (`LessonPlaybackResponse`):
   ```json
   {
     "lesson_id": "...",
     "expires_at": "2026-05-07T14:53:00+00:00",
     "hls_url": "https://api.../lessons/.../hls/master.m3u8?t=...",
     "hls_status": "ready",
     "total_segments": 124,
     "segment_seconds": 6,
     "drm": null
   }
   ```
   - `hls_url` is `null` while `hls_status` is `pending` (background packaging
     hasn't finished). Poll this endpoint every ~5 s until `ready`. Show a
     "video processing" state in the meantime.
   - `hls_status: failed` means packaging blew up — surface a generic error and
     have the instructor re-upload.
   - `total_segments` × `segment_seconds` is the **authoritative duration** —
     use it to render the progress bar and label, not `<video>.duration`. For
     enrolled students the manifest is sliding, so `<video>.duration` will lie
     (it reflects the currently-buffered window, not the whole lesson).

2. **Hand `hls_url` to the player.** Use **hls.js** on browsers without native
   HLS (Chrome/Firefox); Safari plays it natively via `<video src=...>`.
   ```js
   import Hls from "hls.js";
   const hls = new Hls({ xhrSetup: (xhr) => { /* nothing — token is in URL */ } });
   hls.loadSource(playback.hls_url);
   hls.attachMedia(videoEl);
   ```
   The manifest, segments, and AES-128 key are all served by the backend with
   the same `?t=<token>` query string. The player follows them automatically.

3. **Token is IP-bound.** If the user's IP changes mid-session (e.g. switches
   from Wi-Fi to LTE), segment fetches start returning
   `401 playback_ip_mismatch`. Catch the player error, call `/playback` again,
   call `hls.loadSource(newUrl)`. Do this on `Hls.Events.ERROR` with
   `data.fatal`.

4. **Token expires** after `STREAM_TOKEN_TTL_SECONDS` (default 1800 s / 30 min).
   For long lectures, refresh the token a couple of minutes before `expires_at`
   and reload the source. Same drill — `/playback` → `loadSource`.

#### Eligibility

`/playback` returns `403 not_enrolled` unless one of:
- The user is enrolled in the course, **or**
- `lesson.is_free_preview === true` and the course is published, **or**
- The user is the course owner (instructor) or an admin.

In the curriculum UI, lessons with `is_free_preview: true` should be playable
for non-enrolled users — everything else needs the "Enroll" CTA.

#### Anti-seek / max-2x playback (enrolled students only)

For enrolled students the backend enforces "watch the lesson fully, no
skipping, max 2× speed" purely from segment fetches — there is no JS
heartbeat the client needs to send.

What the server does on its own:

- The HLS manifest is **sliding**. Only segments up to `max_segment_index +
  STREAM_LOOKAHEAD_SEGMENTS` (default 8 — the player's normal forward
  buffer) appear in the playlist. Segments past that don't exist as far
  as the player is concerned, so `currentTime` cannot advance there.
- The playlist is served as `EXT-X-PLAYLIST-TYPE:EVENT` (no `ENDLIST` until
  the window covers the whole lesson). hls.js / Safari handle this natively
  by re-fetching the manifest periodically.
- Each segment fetch advances the user's watermark and accumulates "play
  credit" with each gap clamped at one segment duration. Fetches that would
  exceed `STREAM_MAX_RATE_MULTIPLIER × wall_clock` are rejected.
- Lesson completion is server-derived: when the watermark reaches the final
  segment, the backend marks `lesson_progress.completed_at`, recomputes
  `Enrollment.progress_percent`, and rolls forward `daily_activity`. A
  client `PUT /progress {completed: true}` no longer fakes completion —
  the watermark is the source of truth.

What the client must do:

1. **Hide the seek UI.** Don't pass `controls` to `<video>` — render your
   own shell. The progress bar is read-only (no pointer events). Render it
   from `(playback.total_segments, playback.segment_seconds)` and the
   user's `last_position_seconds` server-side, not from `<video>.duration`.
2. **Cap the rate selector at 2×.** Offer `1×`, `1.25×`, `1.5×`, `2×`.
   ```js
   videoEl.addEventListener("ratechange", () => {
     if (videoEl.playbackRate > 2) videoEl.playbackRate = 2;
   });
   ```
3. **Clamp seeks.** Even though the manifest physically prevents seeking
   beyond the buffer window, you still want a clean UX:
   ```js
   let lastTime = 0;
   videoEl.addEventListener("timeupdate", () => { lastTime = videoEl.currentTime; });
   videoEl.addEventListener("seeking", () => {
     // Only allow seeking backwards (rewatch) — never forwards past the buffer.
     if (videoEl.currentTime > lastTime + 0.5) videoEl.currentTime = lastTime;
   });
   ```
4. **Handle the new error codes** (see §5.4): `segment_skip_blocked` (403)
   and `segment_rate_exceeded` (429) bubble up via `Hls.Events.ERROR` with
   `data.response.code`. They generally mean the user did something the
   custom UI should have prevented — log it. `segment_rate_exceeded` is
   transient and the player will recover by waiting; `segment_skip_blocked`
   means the manifest is out of sync (force a manifest reload).

Admins, course owners, and free-preview viewers see the full VOD manifest
and none of these constraints — write your player so it can fall back to
native `controls` for those callers based on a "is this user the
instructor/admin" flag.

### 5.2 Course preview videos (direct MP4)

Marketing videos on the course detail page are intentionally watchable —
non-enrolled users need to evaluate the course.

1. `GET /api/v1/courses/{slug}/preview-playback` (Bearer auth)
   → `{course_id, expires_at, stream_url}`
2. Set `<video src={stream_url} controls />`. The browser handles byte-range
   automatically. The backend honors `Range` and serves 206 partial content.

Same IP-binding caveat applies — refresh the token if the user's network
changes.

### 5.3 DRM (Widevine / FairPlay / PlayReady)

If `LessonPlaybackResponse.drm` is non-null:

```json
{ "provider": "ezdrm", "license_url": "/api/v1/lessons/.../drm/license" }
```

Configure the player's EME callback to `POST` the binary challenge to
`license_url` with the user's bearer token; the response body is the binary
license. Today the backend is wired with a stub provider — once `DRM_PROVIDER`
is a real one, it just works.

### 5.4 Streaming-related errors

| code | Meaning | UI response |
| ---- | ------- | ----------- |
| `lesson_video_missing` | Instructor hasn't uploaded yet | "Coming soon" |
| `hls_not_ready` | Packaging in flight or failed | Poll, then error |
| `lesson_key_missing` | Internal — packager didn't persist | Hard error |
| `not_enrolled` | Show "Enroll" CTA | |
| `missing_playback_token` / `invalid_playback_token` / `playback_token_expired` | Re-mint via `/playback` | |
| `playback_ip_mismatch` | Network changed | Re-mint |
| `playback_resource_mismatch` / `playback_scope_mismatch` | Bug — token reused for wrong lesson | Log + re-mint |
| `segment_skip_blocked` (403) | User tried to seek past the look-ahead window | Force a manifest reload; if it persists, the custom UI failed to clamp seeks |
| `segment_rate_exceeded` (429) | Player consumed segments faster than `STREAM_MAX_RATE_MULTIPLIER` allows | Transient — wait and the player retries; verify rate is clamped to ≤ 2× |
| `course_preview_missing` | Instructor hasn't uploaded preview | Hide preview UI |
| `course_not_published` | Preview only available on published courses | Show "Coming soon" |

---

## 6. File uploads

All upload endpoints accept `multipart/form-data` with a `file` field.

```js
const fd = new FormData();
fd.append("file", fileInput.files[0]);
// optional fields go alongside, e.g.:
fd.append("duration_seconds", "240");

await fetch(`/api/v1/instructor/lessons/${id}/video`, {
  method: "POST",
  headers: { Authorization: `Bearer ${access}` },  // do NOT set Content-Type
  body: fd,
});
```

Don't set `Content-Type` manually — the browser will add the boundary.

Response is either `UploadResponse {url, size_bytes}` (avatars, thumbnails,
icons) or the parent resource updated with the new key (lesson video, lesson
resource).

---

## 7. Suggested client architecture

A minimal opinionated layout:

```
src/
  api/
    client.ts          // fetch wrapper: base URL, JSON, error normalization
    auth.ts            // login/logout/refresh, token store, refresh queue
    types.ts           // generated from openapi.json (recommended)
    courses.ts, ...    // one module per backend section
  player/
    useLessonPlayer.ts // mint token, drive hls.js, IP/expiry refresh loop
```

### Recommended: generate types from OpenAPI

```bash
npx openapi-typescript http://localhost:8000/api/v1/openapi.json \
  -o src/api/types.ts
```

Re-run when the backend changes. The OpenAPI spec is committed at
`bruno/openapi.json` — you can also point the generator at the file.

### Fetch wrapper sketch

```ts
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });
  if (res.status === 401) {
    if (await tryRefresh()) return api<T>(path, init);  // retry once
    throw new ApiError(401, "unauthorized", "Session expired");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body?.error?.code, body?.error?.message, body?.error?.details);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
```

### Refresh queue (single-flight)

```ts
let refreshing: Promise<boolean> | null = null;
async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch(`${BASE_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!r.ok) { wipeAuth(); return false; }
        const t = await r.json();
        setTokens(t.access_token, t.refresh_token);
        return true;
      } finally { refreshing = null; }
    })();
  }
  return refreshing;
}
```

---

## 8. Local-dev quickstart for the frontend

```bash
# Backend up
docker compose up -d
docker compose exec api alembic upgrade head

# Backend runs at http://localhost:8000
# OpenAPI: http://localhost:8000/api/v1/openapi.json
# Swagger UI: http://localhost:8000/docs

# Add your frontend origin to BACKEND_CORS_ORIGINS in .env, then re-up:
docker compose up -d --force-recreate api
```

Register an account through `POST /auth/register`, verify the email, then
promote it to admin if you need elevated access:

```bash
docker compose exec db psql -U satzone -d satzone -c \
  "UPDATE users SET role='admin', is_verified=true WHERE email='you@example.com';"
```

---

## 9. Things that will trip you up

- **Refresh rotates.** Every successful `/auth/refresh` returns a new refresh
  token; the old one is revoked. Storing the original forever and re-using it
  triggers `token_reuse` and revokes everything.
- **Email gate.** A freshly-registered user can't `POST /auth/login` until
  they verify. Don't auto-redirect to login after register.
- **`exclude_unset` semantics.** All `PATCH` endpoints only touch the fields
  you send. Don't send `null` to clear a field unless the schema explicitly
  permits it — `null` *will* set the column to NULL.
- **Slugs vs IDs.** Detail endpoints take slugs (`/courses/{slug}`); filters
  take IDs (`?category_id=...`). Query parameters whose name ends in `_id` want
  UUIDs.
- **Media URLs are short-lived in S3 mode.** Don't bake them into emails or
  cache for hours. Re-fetch the parent resource.
- **Lesson videos are never direct URLs.** `GET /lessons/{id}/playback` is the
  only way to get a playable URL, and it's IP-bound + expires.
- **HLS packaging is async.** A lesson video shows up as `hls_status=pending`
  immediately after upload. Poll until `ready` before exposing the player.
- **Reviews require enrollment.** `POST /courses/{slug}/reviews` returns
  `409 not_enrolled` otherwise. Hide the review form until the user is enrolled.
- **Rate limits per IP.** When testing under a shared IP (office NAT,
  corporate VPN), bump `RATE_LIMIT_*` in `.env` for dev or you'll see
  spurious 429s.
- **422 validation errors carry per-field detail.** Render them inline; don't
  show the raw `details` array to users.
- **`X-Forwarded-For` matters.** If your frontend dev server proxies API
  calls, make sure it forwards the client IP — both rate-limit buckets and
  playback token IP-binding rely on it.
