"""Generate Bruno .bru files from satzone.collection.json.

The collection JSON (Postman v2.1 shape) stays the canonical source: it imports
cleanly into Postman/Insomnia, and FastAPI's openapi.json + this script keep it
in sync with the Bruno tree the desktop app shows.

Layout:
  bruno/<folder-slug>/<NN>-<request-slug>.bru

Regeneration is idempotent. A manifest at bruno/.gen-manifest records every
generated path; on re-run the script deletes only those paths before writing
new ones, so hand-edited .bru files added elsewhere survive.

Usage:
  python bruno/scripts/generate_bru.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "satzone.collection.json"
MANIFEST = ROOT / ".gen-manifest"


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "untitled"


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def render_method_block(method: str, url: str, body_kind: str | None, auth_kind: str | None) -> str:
    lines = [f"{method.lower()} {{", f"  url: {url}"]
    if body_kind:
        lines.append(f"  body: {body_kind}")
    if auth_kind:
        lines.append(f"  auth: {auth_kind}")
    lines.append("}")
    return "\n".join(lines)


def parse_url(url):
    """Return (raw_url_no_query, [(key, value, disabled), ...])."""
    if isinstance(url, str):
        if "?" in url:
            base, qs = url.split("?", 1)
            params = []
            for piece in qs.split("&"):
                if not piece:
                    continue
                k, _, v = piece.partition("=")
                params.append((k, v, False))
            return base, params
        return url, []
    if isinstance(url, dict):
        raw = url.get("raw") or ""
        base = raw.split("?", 1)[0] if "?" in raw else raw
        params = []
        for q in url.get("query") or []:
            params.append((q.get("key", ""), q.get("value", "") or "", bool(q.get("disabled"))))
        return base, params
    return "", []


def render_query(params) -> str:
    if not params:
        return ""
    lines = ["query {"]
    for key, value, disabled in params:
        prefix = "~" if disabled else ""
        lines.append(f"  {prefix}{key}: {value}")
    lines.append("}")
    return "\n".join(lines)


def render_headers(headers) -> str:
    if not headers:
        return ""
    lines = ["headers {"]
    for h in headers:
        prefix = "~" if h.get("disabled") else ""
        lines.append(f"  {prefix}{h.get('key','')}: {h.get('value','')}")
    lines.append("}")
    return "\n".join(lines)


def render_body(body) -> tuple[str | None, str]:
    """Return (body_kind_for_method_block, body_block_text)."""
    if not body:
        return None, ""
    mode = body.get("mode")
    if mode == "raw":
        raw = body.get("raw", "")
        return "json", f"body:json {{\n{indent(raw)}\n}}"
    if mode == "formdata":
        lines = ["body:multipart-form {"]
        for f in body.get("formdata") or []:
            prefix = "~" if f.get("disabled") else ""
            key = f.get("key", "")
            if f.get("type") == "file":
                lines.append(f"  {prefix}{key}: @file()")
            else:
                lines.append(f"  {prefix}{key}: {f.get('value', '')}")
        lines.append("}")
        return "multipart-form", "\n".join(lines)
    return None, ""


def render_auth(auth) -> tuple[str | None, str]:
    """Return (auth_kind_for_method_block, auth_block_text). None = inherit."""
    if not isinstance(auth, dict):
        return None, ""
    kind = auth.get("type")
    if kind == "noauth":
        return "none", ""
    if kind == "basic":
        creds = {item["key"]: item.get("value", "") for item in auth.get("basic") or []}
        block = "auth:basic {\n" + f"  username: {creds.get('username','')}\n" + f"  password: {creds.get('password','')}\n" + "}"
        return "basic", block
    if kind == "bearer":
        creds = {item["key"]: item.get("value", "") for item in auth.get("bearer") or []}
        token = creds.get("token", "{{access_token}}")
        block = "auth:bearer {\n" + f"  token: {token}\n" + "}"
        return "bearer", block
    return None, ""


_PM_STATUS = re.compile(r"pm\.response\.to\.have\.status\((\d+)\)")
_PM_TEST_OPEN = re.compile(r"pm\.test\(\s*['\"]([^'\"]+)['\"]\s*,\s*\(?\)?\s*=>\s*")
_PM_SET_ENV = re.compile(r"pm\.environment\.set\(\s*['\"]([^'\"]+)['\"]\s*,\s*([^)]+)\)")


def translate_script(src: str) -> tuple[str, str]:
    """Split a Postman script into (tests_block_body, post_response_body) Bruno text.

    Best-effort: handles the common `pm.test('...', () => pm.response.to.have.status(N))`
    one-liners and `pm.environment.set('k', v)` calls used in this collection. Anything
    else is passed through verbatim into post-response so the user can adapt it.
    """
    tests_lines = []
    post_lines = []
    for raw_line in src.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        m_test = _PM_TEST_OPEN.search(stripped)
        m_status = _PM_STATUS.search(stripped)
        if m_test and m_status:
            label, code = m_test.group(1), m_status.group(1)
            tests_lines.append(f'  test("{label}", function() {{')
            tests_lines.append(f"    expect(res.getStatus()).to.equal({code});")
            tests_lines.append("  });")
            continue
        new_line = _PM_SET_ENV.sub(lambda m: f"bru.setEnvVar('{m.group(1)}', {m.group(2).strip()})", stripped)
        new_line = new_line.replace("pm.response.json()", "res.getBody()")
        post_lines.append("  " + new_line)
    tests = "tests {\n" + "\n".join(tests_lines) + "\n}" if tests_lines else ""
    post = "script:post-response {\n" + "\n".join(post_lines) + "\n}" if post_lines else ""
    return tests, post


def render_docs(description: str) -> str:
    if not description:
        return ""
    return "docs {\n" + indent(description) + "\n}"


def render_request(item: dict, seq: int, default_auth: dict | None = None) -> str:
    req = item.get("request", {})
    method = req.get("method", "GET")
    url_value, query_params = parse_url(req.get("url"))
    body_kind, body_block = render_body(req.get("body"))
    # Per-request auth wins; otherwise inherit the collection-level default.
    # This mirrors Postman's inheritance — root collection auth applies to
    # every request unless the request opts out (``noauth``) or overrides.
    request_auth = req.get("auth") if isinstance(req.get("auth"), dict) else None
    auth_kind, auth_block = render_auth(request_auth or default_auth)

    blocks = [
        f"meta {{\n  name: {item.get('name','Request')}\n  type: http\n  seq: {seq}\n}}",
        render_method_block(method, url_value, body_kind, auth_kind),
    ]
    for block in (render_query(query_params), render_headers(req.get("header")), auth_block, body_block):
        if block:
            blocks.append(block)

    for event in item.get("event") or []:
        if event.get("listen") != "test":
            continue
        src = "\n".join(event.get("script", {}).get("exec") or [])
        tests, post = translate_script(src)
        if tests:
            blocks.append(tests)
        if post:
            blocks.append(post)

    docs = render_docs(req.get("description", ""))
    if docs:
        blocks.append(docs)

    return "\n\n".join(blocks) + "\n"


def main() -> int:
    if not COLLECTION.exists():
        print(f"missing {COLLECTION}", file=sys.stderr)
        return 1
    data = json.loads(COLLECTION.read_text(encoding="utf-8"))
    default_auth = data.get("auth") if isinstance(data.get("auth"), dict) else None

    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            target = ROOT / line
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            except OSError as err:
                print(f"warn: could not remove {target}: {err}", file=sys.stderr)

    generated: list[str] = []

    for folder in data.get("item", []):
        folder_name = folder.get("name", "untitled")
        folder_dir = ROOT / slugify(folder_name)
        folder_dir.mkdir(parents=True, exist_ok=True)
        generated.append(folder_dir.name)

        used: dict[str, int] = {}
        for seq, item in enumerate(folder.get("item", []), start=1):
            name = item.get("name", f"request-{seq}")
            slug = slugify(name)
            used[slug] = used.get(slug, 0) + 1
            if used[slug] > 1:
                slug = f"{slug}-{used[slug]}"
            filename = f"{seq:02d}-{slug}.bru"
            path = folder_dir / filename
            path.write_text(
                render_request(item, seq, default_auth=default_auth),
                encoding="utf-8",
            )

    MANIFEST.write_text("\n".join(sorted(set(generated))) + "\n", encoding="utf-8")
    total = sum(len(f.get("item", [])) for f in data.get("item", []))
    print(f"Wrote {total} .bru files across {len(generated)} folders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
