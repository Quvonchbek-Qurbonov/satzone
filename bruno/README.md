# Bruno docs

[Bruno](https://www.usebruno.com/) reads this directory as a collection. The request tree is committed as `.bru` files so it shows up the moment you open the folder — no import step.

| File / folder | Purpose |
| ------------- | ------- |
| `bruno.json` | Bruno collection config — point Bruno → **Open Collection** at this directory and it becomes the collection root. |
| `environments/Local.bru` | Bruno-native environment with `base_url`, `access_token`, `refresh_token`, and other slugs/IDs. Selected via Bruno's top-right environment dropdown. |
| `<folder>/*.bru` | One `.bru` file per request, grouped by tag (`auth/`, `explore/`, `payments/`, `admin/`, `internal/`, …). Generated from `satzone.collection.json` by `scripts/generate_bru.py`. |
| `satzone.collection.json` | Postman Collection v2.1 — the **canonical source** for the request tree. Hand-curated: auto-token-capture scripts, env-var captures, pre-set bodies. Edit this when adding/changing requests, then regenerate the `.bru` tree. |
| `satzone.environment.json` | Postman-format environment kept alongside for one-shot Postman import. The `.bru` file under `environments/` is the source of truth in Bruno. |
| `openapi.json` | Raw OpenAPI 3 spec exported from the live API — kept in sync as a reference spec and for tools that prefer OpenAPI. |
| `scripts/generate_bru.py` | Regenerates the `<folder>/*.bru` tree from `satzone.collection.json`. Idempotent; tracks its output via `.gen-manifest`. |
| `.gen-manifest` | List of folders owned by the generator. Don't hand-edit — re-running the script deletes everything listed here before rewriting. |

## Open in Bruno

1. Bruno → **Open Collection** → select the `bruno/` directory. Bruno reads `bruno.json`, shows the request tree from the committed `.bru` files, and lists the `Local` environment.
2. Top-right environment dropdown → **Local**. Fill in `user_password` (marked secret) if you want auth tests to run.
3. Make sure the stack is up: `docker compose up -d`.
4. Run **Auth → Login (captures tokens)**.
   - Post-response script writes `access_token` and `refresh_token` into the active environment.
5. Every other request inherits Bearer auth from the collection — just hit Send.

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
| Practice → Get my practice pack (student) | `practice_pack_id`, `practice_quiz_id` (first quiz) |
| Practice → Get practice quiz (student) | `practice_item_id` (first item) |
| Practice → Submit practice attempt | `practice_attempt_id` |
| Practice → Instructor: get pack | `practice_pack_id` |
| Practice → Instructor: create quiz | `practice_quiz_id` |
| Practice → Instructor: add MCQ item | `practice_item_id` |

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

### Practice (Duolingo-style drills)

The **Practice** folder is a standalone quiz feature, separate from **Assessments**: no pass/fail, no time limit, no attempt cap, no lesson gating. Each course gets one `practice_pack` auto-created the first time the instructor adds a quiz; each pack holds many quizzes (Duolingo "lessons"), each holding up to 50 items of two types: `mcq` (single-correct multiple choice) and `matching` (pair items left ↔ right).

Access is enrollment-gated — only users who bought the course see published quizzes. Matching items have their `lefts` and `rights` shuffled server-side, and MCQ options omit `is_correct` from the student payload, so the answer key never leaves the server.

Authoring (instructor or admin):

1. **Auth → Login** as the instructor (must be the course owner).
2. **Practice → Instructor: get pack** — auto-creates the pack and captures `practice_pack_id`.
3. **Practice → Instructor: create quiz** → sets `practice_quiz_id`.
4. **Practice → Instructor: add MCQ item** → sets `practice_item_id`.
5. **Practice → Instructor: add matching item** for the pair drag-and-drop UX.
6. **Practice → Instructor: publish quiz** (`is_published=true`) — without this students can't see the quiz.

Playing:

1. Re-login as an enrolled student.
2. **Practice → Get my practice pack (student)** — lists every published quiz with the caller's progress (`completed`, `best_score_percent`, `attempts_count`, `last_attempted_at`).
3. **Practice → Get practice quiz (student)** — full item list with sanitized payloads.
4. **Practice → Submit practice attempt** — server grades each item all-or-nothing, returns per-item results plus aggregate `score_percent`. Replay as many times as you like — `best_score_percent` is `MAX()` across attempts.

Failure modes worth knowing:

| HTTP | code | meaning |
| ---- | ---- | ------- |
| 403  | `not_enrolled` | Caller hasn't bought the course |
| 403  | `instructor_role_required` | Authoring routes called without instructor/admin role |
| 422  | `quiz_item_limit` | More than 50 items per quiz |
| 422  | `quiz_has_no_items` | Attempt submitted against an empty quiz |
| 422  | `duplicate_answer` | Same `item_id` answered twice in one attempt |
| 422  | `unknown_item` | `item_id` doesn't belong to the quiz |

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

## Sync workflow when the API changes

`satzone.collection.json` is the canonical source for the request tree; the `<folder>/*.bru` files are generated from it. After any route, schema, or docstring change:

1. **Refresh `openapi.json`** from the running app:
   ```bash
   python -c "from app.main import app; import json; open('bruno/openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), indent=2))"
   ```
   (Or, if the container is up: `curl http://localhost:8080/api/v1/openapi.json -o bruno/openapi.json`.)
2. **Edit `satzone.collection.json`** to add/rename/remove the request — keep the curated bits (auto-token capture scripts, env-var pre-fills, pre-set bodies) that the OpenAPI spec doesn't carry.
3. **Regenerate the `.bru` tree**:
   ```bash
   python bruno/scripts/generate_bru.py
   ```
4. **Update this README** if the new request needs a new env var, a new flow step, or a new failure-mode row.

All four artifacts — `openapi.json`, `satzone.collection.json`, the `.bru` tree, and the README — get committed together so Bruno, Postman, and OpenAPI consumers stay aligned.

> Bruno can also import `openapi.json` directly (**Import Collection → OpenAPI**), but you lose the post-response scripts and pre-set environment values that the curated collection provides — only useful for a quick read-only browse.
