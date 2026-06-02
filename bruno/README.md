# Bruno docs

Five files for [Bruno](https://www.usebruno.com/):

| File | Purpose |
| ---- | ------- |
| `bruno.json` | Bruno collection config — point Bruno → **Open Collection** at this directory and Bruno will treat it as the collection root. |
| `environments/Local.bru` | Bruno-native environment with `base_url`, `access_token`, `refresh_token`, and other slugs/IDs. Selected via Bruno's top-right environment dropdown. |
| `satzone.collection.json` | Postman Collection v2.1 — Auth, Onboarding, Home, Explore, Reviews, My Learnings, Notes, Downloads, Activity, Video Streaming, Instructor, Assessments, Degree, Account & Settings, **Payments**, Admin, **Internal**. Auto-token-capture scripts on key requests. The Video Streaming folder is HLS-only for lessons (direct-MP4 endpoint removed). Import once into Bruno to populate the request tree. |
| `satzone.environment.json` | Postman-format environment kept alongside the collection for one-shot import. The `.bru` file under `environments/` is the source of truth once you're inside Bruno. |
| `openapi.json` | Raw OpenAPI 3 spec exported from the live API (for tools that prefer OpenAPI) — regenerate after adding endpoints with `curl http://localhost:8080/api/v1/openapi.json -o bruno/openapi.json`. Bruno can also import this directly via **Import Collection → OpenAPI**. |

## Open in Bruno

1. Bruno → **Open Collection** → select the `bruno/` directory. Bruno reads `bruno.json` and shows the `Local` environment under `environments/`.
2. Top-right environment dropdown → **Local**. Fill in `user_password` (marked secret) if you want auth tests to run.
3. First time only — bring the requests in: Bruno → **Import Collection** → choose `satzone.collection.json`. Bruno converts the Postman v2.1 file into `.bru` requests under the collection. (`openapi.json` works too if you'd rather start from the spec.)
4. Make sure the stack is up: `docker compose up -d`.
5. Run **Auth → Login (captures tokens)**.
   - Post-response script writes `access_token` and `refresh_token` into the active environment.
6. Every other request inherits Bearer auth from the collection — just hit Send.

Register a user via `POST /auth/register` (and verify the email) before
running auth-gated requests. Set `user_email` / `user_password` in the
`Local` environment to those credentials.

### Postman ↔ Bruno script compatibility

The auto-capture scripts in `satzone.collection.json` use the Postman API (`pm.environment.set(...)`, `pm.test(...)`). Bruno ships a Postman-compat shim so these run unchanged after import; if you ever rewrite them in Bruno-native style, the equivalents are:

| Postman | Bruno |
| ------- | ----- |
| `pm.environment.set("k", v)` | `bru.setEnvVar("k", v)` |
| `pm.environment.get("k")` | `bru.getEnvVar("k")` |
| `pm.response.json()` | `res.getBody()` |
| `pm.test("name", fn)` | `test("name", fn)` (Chai assertions identical) |

## Auto-capture scripts

These requests have post-response scripts that populate environment variables for downstream calls:

| Request | Sets |
| ------- | ---- |
| Auth → Login / Refresh | `access_token`, `refresh_token` |
| Video Streaming → Lesson playback | `playback_token`, `lesson_hls_url` |
| Video Streaming → Course preview playback | `preview_token`, `preview_stream_url` |
| Explore → List categories | `category_id` (first item) |
| Explore → List courses | `course_id`, `course_slug` (first item) |
| Explore → Course curriculum | `lesson_id` (first lesson of first section) |
| My Learnings → Enroll | `enrollment_id` |
| Degree → List programs | `program_id`, `program_slug` |
| Account → List sessions | `session_id` (first session) |
| Instructor → Create course | `instructor_course_id`, `course_slug` |
| Instructor → Create section | `section_id` |
| Instructor → Create lesson | `instructor_lesson_id` |
| Assessments → Create assessment | `assessment_id` |
| Assessments → Add question (single_choice) | `question_id`, `option_id` (first correct option) |
| Admin → Categories → Create | `admin_category_id` |
| Admin → Instructors → Create | `admin_instructor_id` |
| Admin → Programs → Create | `admin_program_id` |
| Notes → Create note | `note_id` |
| Instructor → Upload lesson attachment | `attachment_id` |
| Downloads → List lesson attachments | `attachment_id` |
| Downloads → Save attachment for offline | `download_id` |
| Payments → Save card | `payment_method_id` |
| Payments → Create order | `order_id` |
| Payments → Pay order (Payme hosted checkout) | `payme_checkout_url` |

A clean run order to exercise everything end-to-end:

1. **Auth → Login**
2. **Explore → List categories** (sets `category_id`)
3. **Onboarding → Update onboarding**
4. **Explore → List courses** (sets `course_id`, `course_slug`)
5. **Explore → Course curriculum** (sets `lesson_id`)
6. **My Learnings → Enroll in course** (sets `enrollment_id`)
7. **My Learnings → Update lesson progress** (`completed: true` will issue a certificate when all lessons complete)
8. **Reviews → Create review**
9. **Degree → List programs** (sets `program_id`)
10. **Degree → Enroll in program**
11. **Account & Settings → …**

### Video streaming flow

Lesson playback is HLS-only — there is no direct-MP4 endpoint, because plain MP4 over HTTP is downloadable. Tokens are bound to the requester's IP (`cip` claim); replay from a different network returns 401.

For **enrolled students**, the manifest endpoint serves a *sliding* HLS playlist: only segments up to `max_segment_index + STREAM_LOOKAHEAD_SEGMENTS` are visible, so the player physically cannot seek beyond the watched window. Segment fetches are also rate-limited so accumulated play time can't exceed `STREAM_MAX_RATE_MULTIPLIER` × wall clock — anything faster is rejected with `segment_rate_exceeded` (HTTP 429). Skipping past the look-ahead returns `segment_skip_blocked` (HTTP 403). Lesson completion is derived server-side from the segment watermark; clients can no longer mark a lesson complete by hitting the progress endpoint with `completed:true` if the watermark hasn't reached the final segment.

Admins, course owners, and viewers of `is_free_preview` lessons bypass the gate and see the full VOD manifest.

`/lesson playback` returns `total_segments` and `segment_seconds` so the player can render a static, non-interactive progress bar that matches the server's authoritative duration without trusting `<video>.duration`.

1. **Auth → Login** as a user enrolled in the course (or use a `is_free_preview=true` lesson; admins / course owners can also bypass).
2. **Explore → Course curriculum** to capture `lesson_id`.
3. **Video Streaming → Lesson playback** — captures `playback_token`, `lesson_hls_url`. Returns `hls_url=null` while `hls_status` is still `pending` (background packaging) — poll until `ready`. Also returns `total_segments` + `segment_seconds`.
4. **Video Streaming → Lesson HLS — master playlist** returns the manifest with rewritten signed URIs for both the AES-128 key and every segment — pass it straight to hls.js / Safari.
5. **Video Streaming → Lesson HLS — content key** returns the 16-byte content key. The player fetches this automatically when following the manifest.
6. **Video Streaming → Lesson HLS — first segment** is encrypted bytes; only useful in combination with the key.
7. **Video Streaming → Course preview playback** still serves direct MP4 — preview videos are marketing content meant to be watchable by non-enrolled users.
8. **Video Streaming → DRM license proxy** returns `drm_not_configured` until you set `DRM_PROVIDER` in `.env` to a real provider.

### Admin flow

The **Admin** folder contains 36 requests covering: Users, Categories, Instructors, Courses, Programs (incl. program↔course linking), Reviews, Enrollments, Certificates. All require `role=admin` (caller token must belong to an admin user). Bootstrap your first admin in the DB:

```bash
docker compose exec db psql -U satzone -d satzone -c "UPDATE users SET role='admin', is_verified=true WHERE email='you@example.com';"
```

After that, log in as the admin (Auth → Login) and every Admin request inherits the bearer token.

### Internal API (Telegram bot / S2S)

The **Internal** folder holds server-to-server endpoints that bypass user
auth and use a shared `X-Internal-API-Key` header instead. They're meant
for trusted callers (the Telegram bot, internal jobs) — never expose the
key to the frontend.

1. Generate a key once: `openssl rand -hex 32`, put it in the backend's
   `.env` as `INTERNAL_API_KEY=…`, restart the api container.
2. In Bruno, paste the same value into the `internal_api_key` secret env
   var (top-right environment dropdown → edit).
3. **Internal → Lookup user by phone** — POSTs `{phone_number}` (E.164)
   and returns `{id, email, full_name, is_active, is_phone_verified}`.
   `user_phone` is reused from the auth flow, so a single value drives
   both Verify phone and the bot lookup.
4. **Internal → Issue phone OTP** — POSTs `{phone_number}` (E.164) and
   returns `{otp, expires_in}`. The bot calls this after the user shares
   their contact in chat; show the OTP to the user, then they enter it on
   the frontend which hits **Auth → Verify phone** with `{otp}`. The
   backend reads the phone back out of Redis and binds it to the current
   user. Copy the returned `otp` into the `phone_otp` env var so the
   Verify phone request can pick it up automatically.

Failure modes worth knowing:

| HTTP | code | meaning |
| ---- | ---- | ------- |
| 401  | `internal_not_configured` | `INTERNAL_API_KEY` is empty on the server — fix the `.env` and restart |
| 401  | `invalid_api_key` | Bruno's `internal_api_key` doesn't match the server's |
| 404  | `user_not_found` | Number is unknown — bot should prompt the user to register/verify |
| 409  | `phone_taken` | (issue-otp) The number is already verified on another account — bot should send the user to login instead |

A typical content-management run:

1. **Auth → Login** as admin.
2. **Admin → Categories → Create** → captures `admin_category_id`.
3. **Admin → Instructors → Create** → captures `admin_instructor_id`.
4. **Admin → Programs → Create** → captures `admin_program_id`.
5. **Admin → Programs → Add course** (uses `instructor_course_id` from a published course).
6. **Admin → Programs → Publish**.

### Instructor / Assessments flow

These endpoints require a user with `role=instructor` (or `admin`) — `auth/register` only mints `user`-role accounts. Promote one with **Admin → Promote user to instructor** (caller must already be an admin) or, for the very first admin, directly in the DB: `UPDATE users SET role='admin', is_verified=true WHERE email='…';`.

1. **Auth → Login** as the instructor.
2. **Instructor → Upsert my profile** (creates the `instructors` row tied to your user).
3. **Explore → List categories** to populate `category_id`.
4. **Instructor → Create course** → sets `instructor_course_id`.
5. **Instructor → Create section** → sets `section_id`.
6. **Instructor → Create lesson** → sets `instructor_lesson_id`.
7. **Instructor → Upload course thumbnail / lesson video** (multipart, attach a file).
   - **Upload lesson resource** (multipart `file`) sets `Lesson.resource_url` — one URL per lesson, overwrite-on-upload.
   - **Upload lesson attachment** (multipart `file` + `title`) creates a `LessonAttachment` row — many per lesson, surfaced in the Downloads UI. Captures `attachment_id` for the matching delete request.
8. **Instructor → Publish course** (requires ≥1 lesson and a `description`).
9. **Assessments → Create assessment** → sets `assessment_id`.
10. **Assessments → Add question (single_choice)** → sets `question_id`, `option_id`.
11. **Assessments → Patch assessment** with `{ "status": "published" }` so students can take it. Publishing now rejects assessments with zero questions (`publish_requires_questions`, HTTP 422).
12. Re-login as a student, **My Learnings → Enroll**, then **Assessments → Submit assessment (student)**.
    - Submitting two answers for the same `question_id` returns `duplicate_answer` (HTTP 422) instead of a generic conflict.
    - Pass/fail is computed against the raw percentage — a 69.5% score no longer rounds up past a 70% pass threshold.
    - SHORT_ANSWER comparisons strip whitespace + lowercase on both sides, so accepted answers entered with stray spaces still match.
13. Back as the instructor: **Assessments → List submissions**, **Instructor → Course analytics**.

## Re-export OpenAPI

```bash
curl http://localhost:8080/api/v1/openapi.json -o bruno/openapi.json
```

Bruno can also import the OpenAPI file directly (**Import Collection → OpenAPI**), but you lose the post-response scripts and pre-set environment values that the curated collection provides.
