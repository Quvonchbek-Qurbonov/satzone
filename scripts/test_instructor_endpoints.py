"""End-to-end smoke test for instructor + student endpoints.

Exercises: profile upsert, course CRUD, sections/lessons, video & thumbnail
uploads, publish gating, assessment authoring, student enrollment, assessment
attempt + grading. Uses a freshly-registered instructor and student for each
run (random emails) so it can be re-run idempotently.

Run with:
    docker exec satzone-api-1 python scripts/test_instructor_endpoints.py
"""

from __future__ import annotations

import io
import os
import secrets
import sys
import uuid

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:8000/api/v1")
CATEGORY_ID = os.environ.get(
    "CATEGORY_ID", "c2342b06-bb53-49c1-af14-243c0ab031d9"  # Development
)
PROMOTE_HOOK = os.environ.get("PROMOTE_HOOK")  # optional


def _ok(label: str, resp: httpx.Response, *, expect: int = 200) -> dict | list | None:
    body: object
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    if resp.status_code != expect:
        print(f"FAIL  {label}  [{resp.status_code} != {expect}]  {body}")
        sys.exit(1)
    print(f"PASS  {label}  [{resp.status_code}]")
    return body if isinstance(body, (dict, list)) else None


def _promote_to_instructor(email: str) -> None:
    """Flip a freshly-registered user to instructor via direct SQL.

    The auth API only mints USER-role accounts, so for this test we promote
    out of band — equivalent to an admin action.
    """
    import subprocess

    sql = (
        "UPDATE users SET role='instructor', is_verified=true, "
        f"email_verified_at=now() WHERE email='{email}';"
    )
    res = subprocess.run(
        ["docker", "exec", "satzone-db-1", "psql", "-U", "satzone", "-d", "satzone", "-c", sql],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print("FAIL  promote_user  ", res.stderr)
        sys.exit(1)
    print(f"PASS  promote_user  -> instructor  ({email})")


def main() -> None:
    suffix = secrets.token_hex(4)
    inst_email = f"inst+{suffix}@example.com"
    student_email = f"student+{suffix}@example.com"
    password = "StrongPass!123"

    with httpx.Client(base_url=BASE, timeout=30) as c:
        # ---- Register & promote instructor ----
        r = c.post(
            "/auth/register",
            json={"email": inst_email, "full_name": "Inst Tester", "password": password},
        )
        _ok("register instructor user", r, expect=201)
        _promote_to_instructor(inst_email)

        # Login instructor
        r = c.post("/auth/login", json={"email": inst_email, "password": password})
        tokens = _ok("login instructor", r, expect=200) or {}
        ih = {"Authorization": f"Bearer {tokens['access_token']}"}

        # ---- Profile upsert ----
        r = c.put(
            "/instructor/me/profile",
            headers=ih,
            json={
                "name": "Inst Tester",
                "title": "Senior Engineer",
                "bio": "Tests things.",
                "expertise": ["python", "fastapi"],
            },
        )
        prof = _ok("upsert instructor profile", r, expect=200) or {}
        assert prof["slug"], "profile missing slug"

        r = c.get("/instructor/me/profile", headers=ih)
        _ok("get instructor profile", r, expect=200)

        # ---- Course CRUD ----
        r = c.post(
            "/instructor/courses",
            headers=ih,
            json={
                "title": f"Test Course {suffix}",
                "subtitle": "smoke",
                "description": "A reasonably long description for publish gating.",
                "category_id": CATEGORY_ID,
                "level": "beginner",
                "price_cents": 4999,
                "tags": ["api", "smoke"],
            },
        )
        course = _ok("create course", r, expect=201) or {}
        course_id = course["id"]
        assert course["status"] == "draft"

        r = c.patch(
            f"/instructor/courses/{course_id}",
            headers=ih,
            json={"subtitle": "updated subtitle", "discount_price_cents": 2999},
        )
        course = _ok("patch course", r, expect=200) or {}
        assert course["discount_price_cents"] == 2999

        # Reject discount > price
        r = c.patch(
            f"/instructor/courses/{course_id}",
            headers=ih,
            json={"price_cents": 100, "discount_price_cents": 200},
        )
        _ok("reject discount > price", r, expect=422)

        # ---- Sections ----
        r = c.post(
            f"/instructor/courses/{course_id}/sections",
            headers=ih,
            json={"title": "Intro"},
        )
        section1 = _ok("create section 1", r, expect=201) or {}

        r = c.post(
            f"/instructor/courses/{course_id}/sections",
            headers=ih,
            json={"title": "Advanced"},
        )
        section2 = _ok("create section 2", r, expect=201) or {}

        # Reorder
        r = c.post(
            f"/instructor/courses/{course_id}/sections/reorder",
            headers=ih,
            json={
                "items": [
                    {"id": section2["id"], "order": 0},
                    {"id": section1["id"], "order": 1},
                ]
            },
        )
        reordered = _ok("reorder sections", r, expect=200) or []
        assert reordered[0]["id"] == section2["id"]

        r = c.patch(
            f"/instructor/sections/{section1['id']}",
            headers=ih,
            json={"title": "Intro (renamed)"},
        )
        _ok("update section", r, expect=200)

        # ---- Lessons ----
        r = c.post(
            f"/instructor/sections/{section1['id']}/lessons",
            headers=ih,
            json={
                "title": "Welcome",
                "type": "video",
                "duration_seconds": 120,
                "is_free_preview": True,
            },
        )
        lesson1 = _ok("create lesson 1", r, expect=201) or {}

        r = c.post(
            f"/instructor/sections/{section1['id']}/lessons",
            headers=ih,
            json={"title": "Setup", "type": "article", "article_content": "Install python."},
        )
        lesson2 = _ok("create lesson 2", r, expect=201) or {}

        r = c.patch(
            f"/instructor/lessons/{lesson2['id']}",
            headers=ih,
            json={"description": "Local env steps."},
        )
        _ok("update lesson", r, expect=200)

        # ---- Uploads ----
        # Course thumbnail (tiny PNG bytes)
        png_bytes = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
            "890000000D49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
        )
        files = {"file": ("thumb.png", io.BytesIO(png_bytes), "image/png")}
        r = c.post(
            f"/instructor/courses/{course_id}/thumbnail", headers=ih, files=files
        )
        thumb = _ok("upload course thumbnail", r, expect=200) or {}
        assert thumb["url"].endswith(".png")

        # Lesson video (tiny mp4-ish bytes — extension is what matters here)
        files = {"file": ("clip.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64), "video/mp4")}
        r = c.post(
            f"/instructor/lessons/{lesson1['id']}/video",
            headers=ih,
            files=files,
            data={"duration_seconds": "180"},
        )
        lesson1_full = _ok("upload lesson video", r, expect=200) or {}
        assert lesson1_full["video_url"]

        # Reject bad extension
        files = {"file": ("bad.exe", io.BytesIO(b"x"), "application/octet-stream")}
        r = c.post(f"/instructor/lessons/{lesson1['id']}/video", headers=ih, files=files)
        _ok("reject non-video upload", r, expect=422)

        # ---- Publish gating ----
        r = c.post(f"/instructor/courses/{course_id}/publish", headers=ih)
        course = _ok("publish course", r, expect=200) or {}
        assert course["status"] == "published"

        # ---- Assessments ----
        r = c.post(
            f"/instructor/courses/{course_id}/assessments",
            headers=ih,
            json={
                "title": "Quiz 1",
                "description": "Basic check",
                "pass_percent": 50,
                "max_attempts": 3,
            },
        )
        assessment = _ok("create assessment", r, expect=201) or {}
        a_id = assessment["id"]

        # Single-choice question
        r = c.post(
            f"/instructor/assessments/{a_id}/questions",
            headers=ih,
            json={
                "type": "single_choice",
                "prompt": "What is 2 + 2?",
                "points": 1,
                "options": [
                    {"text": "3", "is_correct": False},
                    {"text": "4", "is_correct": True},
                    {"text": "5", "is_correct": False},
                ],
            },
        )
        q1 = _ok("add single_choice question", r, expect=201) or {}
        correct_q1 = next(o["id"] for o in q1["options"] if o["is_correct"])

        # Short-answer question
        r = c.post(
            f"/instructor/assessments/{a_id}/questions",
            headers=ih,
            json={
                "type": "short_answer",
                "prompt": "Capital of France?",
                "points": 1,
                "expected_answers": ["Paris"],
            },
        )
        q2 = _ok("add short_answer question", r, expect=201) or {}

        # Reject malformed single_choice (no correct option)
        r = c.post(
            f"/instructor/assessments/{a_id}/questions",
            headers=ih,
            json={
                "type": "single_choice",
                "prompt": "Bad",
                "options": [
                    {"text": "a", "is_correct": False},
                    {"text": "b", "is_correct": False},
                ],
            },
        )
        _ok("reject single_choice with no correct", r, expect=422)

        # Publish assessment so a student can take it
        r = c.patch(
            f"/instructor/assessments/{a_id}", headers=ih, json={"status": "published"}
        )
        _ok("publish assessment", r, expect=200)

        # ---- Students view + enrollment + submission ----
        r = c.post(
            "/auth/register",
            json={"email": student_email, "full_name": "Stu Student", "password": password},
        )
        _ok("register student", r, expect=201)
        r = c.post("/auth/login", json={"email": student_email, "password": password})
        sh = {"Authorization": f"Bearer {(_ok('login student', r, expect=200) or {})['access_token']}"}

        r = c.post("/me/enrollments", headers=sh, json={"course_id": course_id})
        _ok("student enrolls", r, expect=201)

        # Student gets assessment (no is_correct flag on options)
        r = c.get(f"/assessments/{a_id}", headers=sh)
        student_view = _ok("student fetches assessment", r, expect=200) or {}
        assert "is_correct" not in student_view["questions"][0]["options"][0]

        # Student submits — picks correct option for q1, correct text for q2
        r = c.post(
            f"/assessments/{a_id}/submissions",
            headers=sh,
            json={
                "answers": [
                    {"question_id": q1["id"], "selected_option_ids": [correct_q1]},
                    {"question_id": q2["id"], "text": "paris"},
                ]
            },
        )
        sub = _ok("submit assessment (full marks)", r, expect=201) or {}
        assert sub["score_percent"] == 100, sub
        assert sub["passed"] is True

        # Wrong submission — both wrong
        wrong_opt = next(o["id"] for o in q1["options"] if not o["is_correct"])
        r = c.post(
            f"/assessments/{a_id}/submissions",
            headers=sh,
            json={
                "answers": [
                    {"question_id": q1["id"], "selected_option_ids": [wrong_opt]},
                    {"question_id": q2["id"], "text": "London"},
                ]
            },
        )
        sub2 = _ok("submit assessment (zero)", r, expect=201) or {}
        assert sub2["score_percent"] == 0, sub2
        assert sub2["passed"] is False

        # ---- Instructor analytics + students ----
        r = c.get(f"/instructor/courses/{course_id}/students", headers=ih)
        students = _ok("list course students", r, expect=200) or {}
        assert students["total"] == 1

        r = c.get(f"/instructor/courses/{course_id}/analytics", headers=ih)
        analytics = _ok("course analytics", r, expect=200) or {}
        assert analytics["enrollments_count"] == 1

        r = c.get(f"/instructor/assessments/{a_id}/submissions", headers=ih)
        subs = _ok("instructor lists submissions", r, expect=200) or {}
        assert subs["total"] == 2

        # ---- Ownership enforcement ----
        # Student tries to update instructor's course → forbidden (403)
        r = c.patch(
            f"/instructor/courses/{course_id}", headers=sh, json={"title": "hijack"}
        )
        _ok("non-instructor blocked from /instructor", r, expect=403)

        # ---- Cleanup-friendly delete on a fresh course ----
        r = c.post(
            "/instructor/courses",
            headers=ih,
            json={
                "title": f"Disposable {suffix}",
                "category_id": CATEGORY_ID,
                "level": "beginner",
            },
        )
        disp = _ok("create disposable course", r, expect=201) or {}
        r = c.delete(f"/instructor/courses/{disp['id']}", headers=ih)
        _ok("delete disposable course", r, expect=204)

        # Course with enrollments cannot be deleted
        r = c.delete(f"/instructor/courses/{course_id}", headers=ih)
        _ok("reject delete enrolled course", r, expect=409)

    print()
    print("All instructor endpoint smoke tests passed.")


if __name__ == "__main__":
    main()
