"""One-shot helper that injects a 'Video Streaming' folder into the Postman
collection. Idempotent: re-running it replaces the existing folder.

Run:
    python scripts/add_streaming_postman.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECTION = ROOT / "postman" / "edure.postman_collection.json"
ENV = ROOT / "postman" / "edure.postman_environment.json"


def request(name: str, method: str, path: str, *, body: str | None = None, exec_lines: list[str] | None = None, query: list[dict] | None = None) -> dict:
    url_obj: dict = {
        "raw": "{{base_url}}" + path,
        "host": ["{{base_url}}"],
        "path": [p for p in path.lstrip("/").split("/") if p],
    }
    if query:
        url_obj["query"] = query
    req: dict = {
        "name": name,
        "request": {
            "method": method,
            "header": [{"key": "Content-Type", "value": "application/json"}] if body else [],
            "url": url_obj,
        },
        "response": [],
    }
    if body is not None:
        req["request"]["body"] = {"mode": "raw", "raw": body}
    if exec_lines:
        req["event"] = [
            {
                "listen": "test",
                "script": {"type": "text/javascript", "exec": exec_lines},
            }
        ]
    return req


STREAMING_FOLDER = {
    "name": "Video Streaming",
    "description": "Auth-gated video playback. Lessons are HLS-only — there is no direct-MP4 endpoint, because plain MP4 over HTTP is downloadable. Tokens are bound to the requester's IP (cip claim); the same token replayed from a different network returns 401.",
    "item": [
        request(
            "Lesson playback (capture HLS URL + token)",
            "GET",
            "/lessons/{{lesson_id}}/playback",
            exec_lines=[
                "const j = pm.response.json();",
                "if (j.hls_url) {",
                "  pm.environment.set('lesson_hls_url', j.hls_url);",
                "  const t = (j.hls_url.split('t=')[1] || '');",
                "  pm.environment.set('playback_token', t);",
                "}",
                "pm.test('playback issued', () => pm.expect(j).to.have.property('expires_at'));",
                "pm.test('hls is the only path', () => pm.expect(j).to.not.have.property('stream_url'));",
            ],
        ),
        request(
            "Lesson HLS — master playlist",
            "GET",
            "/lessons/{{lesson_id}}/hls/master.m3u8",
            query=[{"key": "t", "value": "{{playback_token}}"}],
        ),
        request(
            "Lesson HLS — content key (raw 16 bytes)",
            "GET",
            "/lessons/{{lesson_id}}/hls/key",
            query=[{"key": "t", "value": "{{playback_token}}"}],
        ),
        request(
            "Lesson HLS — first segment (encrypted .ts)",
            "GET",
            "/lessons/{{lesson_id}}/hls/seg/seg_0000.ts",
            query=[{"key": "t", "value": "{{playback_token}}"}],
        ),
        request(
            "Course preview playback (marketing video — direct MP4 OK)",
            "GET",
            "/courses/{{course_slug}}/preview-playback",
            exec_lines=[
                "const j = pm.response.json();",
                "if (j.stream_url) {",
                "  const t = (j.stream_url.split('t=')[1] || '');",
                "  pm.environment.set('preview_token', t);",
                "  pm.environment.set('preview_stream_url', j.stream_url);",
                "}",
            ],
        ),
        request(
            "DRM license proxy (raw binary challenge)",
            "POST",
            "/lessons/{{lesson_id}}/drm/license",
            body="<binary EME challenge bytes>",
        ),
    ],
}


def upsert_folder(collection: dict, folder: dict) -> None:
    items = collection.setdefault("item", [])
    for i, existing in enumerate(items):
        if existing.get("name") == folder["name"]:
            items[i] = folder
            return
    # Insert right after 'My Learnings' so it sits with the other media-flow folders.
    for i, existing in enumerate(items):
        if existing.get("name") == "My Learnings":
            items.insert(i + 1, folder)
            return
    items.append(folder)


def ensure_env_vars(env: dict, keys: list[tuple[str, str]]) -> None:
    existing = {v["key"] for v in env.get("values", [])}
    for key, default in keys:
        if key not in existing:
            env["values"].append(
                {"key": key, "value": default, "type": "default", "enabled": True}
            )


def main() -> None:
    coll = json.loads(COLLECTION.read_text(encoding="utf-8"))
    upsert_folder(coll, STREAMING_FOLDER)
    COLLECTION.write_text(json.dumps(coll, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    env = json.loads(ENV.read_text(encoding="utf-8"))
    ensure_env_vars(env, [
        ("playback_token", ""),
        ("preview_token", ""),
        ("lesson_stream_url", ""),
        ("lesson_hls_url", ""),
        ("preview_stream_url", ""),
    ])
    ENV.write_text(json.dumps(env, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("postman: Video Streaming folder + env vars synced")


if __name__ == "__main__":
    main()
