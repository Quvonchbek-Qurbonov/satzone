# Postman docs

Three files for Postman:

| File | Purpose |
| ---- | ------- |
| `edure.postman_collection.json` | Postman Collection v2.1 — 89 requests across 11 folders, with auto-token-capture scripts |
| `edure.postman_environment.json` | Environment with `base_url`, `access_token`, `refresh_token`, and other useful slugs/IDs |
| `openapi.json` | Raw OpenAPI 3 spec exported from the live API (for tools that prefer OpenAPI) |

## Import

1. Postman → **Import** → drop both `edure.postman_collection.json` and `edure.postman_environment.json`.
2. Top-right environment dropdown → **Edure (local)**.
3. Make sure the stack is up: `docker compose up -d`.
4. Run **Auth → Login (captures tokens)**.
   - Test script writes `access_token` and `refresh_token` into the environment.
5. Every other request inherits Bearer auth from the collection — just hit Send.

Default credentials match the seeded demo user: `demo@edure.local` / `DemoPass123!`.

## Auto-capture scripts

These requests have test scripts that populate environment variables for downstream calls:

| Request | Sets |
| ------- | ---- |
| Auth → Login / Refresh | `access_token`, `refresh_token` |
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

### Instructor / Assessments flow

These endpoints require a user with `role=instructor` (or `admin`) — `auth/register` only mints `user`-role accounts. Promote one with **Admin → Promote user to instructor** (caller must already be an admin) or, for the very first admin, directly in the DB: `UPDATE users SET role='admin', is_verified=true WHERE email='…';`.

1. **Auth → Login** as the instructor.
2. **Instructor → Upsert my profile** (creates the `instructors` row tied to your user).
3. **Explore → List categories** to populate `category_id`.
4. **Instructor → Create course** → sets `instructor_course_id`.
5. **Instructor → Create section** → sets `section_id`.
6. **Instructor → Create lesson** → sets `instructor_lesson_id`.
7. **Instructor → Upload course thumbnail / lesson video** (multipart, attach a file).
8. **Instructor → Publish course** (requires ≥1 lesson and a `description`).
9. **Assessments → Create assessment** → sets `assessment_id`.
10. **Assessments → Add question (single_choice)** → sets `question_id`, `option_id`.
11. **Assessments → Patch assessment** with `{ "status": "published" }` so students can take it.
12. Re-login as a student, **My Learnings → Enroll**, then **Assessments → Submit assessment (student)**.
13. Back as the instructor: **Assessments → List submissions**, **Instructor → Course analytics**.

## Re-export OpenAPI

```bash
curl http://localhost:8000/api/v1/openapi.json -o postman/openapi.json
```

Postman can also import the OpenAPI file directly (Import → File → `openapi.json`), but you lose the test scripts and pre-set environment values that the curated collection provides.
