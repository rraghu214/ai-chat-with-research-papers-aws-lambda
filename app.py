import os
import uuid
import base64
from typing import Dict, Any
from urllib.parse import parse_qs
from jinja2 import Environment, FileSystemLoader, select_autoescape

from extractors import extract_text_from_url
from llm import summarize_map_reduce, chat_answer

# ---------------- In-memory caches (valid for warm Lambda containers) ----------------
DOC_CACHE: Dict[str, Dict[str, Any]] = {}      # url -> {"text": str, "summaries": {level: html}}
CHAT_HISTORY: Dict[tuple, list] = {}           # (sid, url) -> list[{role,text}]
VALID_LEVELS = {"LOW", "MEDIUM", "HIGH"}

# ---------------- Jinja2 Environment ----------------
_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"])
)
_index_tmpl = _env.get_template("index.html")

# ---------------- Helper Functions ----------------

def _ensure_sid(headers: Dict[str, str]) -> tuple[str, bool]:
    """Return (sid, is_new). Parse from Cookie header or generate."""
    cookie_header = headers.get("cookie") or headers.get("Cookie") or ""
    parts = [p.strip() for p in cookie_header.split(';') if p.strip()]
    for p in parts:
        if p.startswith("sid="):
            return p.split("=", 1)[1], False
    return str(uuid.uuid4()), True


def _render_index(**context) -> str:
    return _index_tmpl.render(**context)


def _form_parse(body: str) -> Dict[str, str]:
    data = {}
    for k, v in parse_qs(body).items():
        if v:
            data[k] = v[0]
    return data


def _static_file_response(path: str) -> Dict[str, Any]:
    full_path = os.path.join("static", path)
    if not os.path.isfile(full_path):
        return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
    with open(full_path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(full_path)[1].lower()
    ctype = "text/plain"
    if ext == ".css":
        ctype = "text/css"
    elif ext == ".js":
        ctype = "application/javascript"
    return {
        "statusCode": 200,
        "headers": {"Content-Type": ctype},
        "body": data.decode("utf-8"),
    }


def _json_response(payload: Dict[str, Any], status: int = 200, set_cookie: str | None = None) -> Dict[str, Any]:
    import json
    headers = {"Content-Type": "application/json"}
    if set_cookie:
        headers["Set-Cookie"] = set_cookie
    return {"statusCode": status, "headers": headers, "body": json.dumps(payload)}


def _html_response(html: str, status: int = 200, set_cookie: str | None = None) -> Dict[str, Any]:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    if set_cookie:
        headers["Set-Cookie"] = set_cookie
    return {"statusCode": status, "headers": headers, "body": html}

# ---------------- Lambda Handler ----------------

def lambda_handler(event, context):  # AWS Lambda entrypoint
    try:
        raw_path = event.get("rawPath") or event.get("path") or "/"
        method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
        headers = event.get("headers") or {}
        sid, is_new_sid = _ensure_sid(headers)
        set_cookie_header = None
        if is_new_sid:
            set_cookie_header = f"sid={sid}; Path=/; HttpOnly; SameSite=Lax"

        # ------------- Static files -------------
        if raw_path.startswith("/static/"):
            rel = raw_path[len("/static/"):]
            resp = _static_file_response(rel)
            if set_cookie_header:
                resp.setdefault("headers", {})["Set-Cookie"] = set_cookie_header
            return resp

        # ------------- GET / -------------
        if raw_path == "/" and method == "GET":
            html = _render_index()
            return _html_response(html, set_cookie=set_cookie_header)

        # Retrieve / parse body
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", errors="ignore")

        # ------------- POST /summarize -------------
        if raw_path == "/summarize" and method == "POST":
            # Form submission (application/x-www-form-urlencoded)
            form = _form_parse(body)
            url = (form.get("paper_url") or "").strip()
            level = (form.get("complexity") or "LOW").strip().upper()
            if level not in VALID_LEVELS:
                level = "LOW"
            if not (url.startswith("http://") or url.startswith("https://")):
                html = _render_index(error="Please enter a valid http(s) URL.")
                return _html_response(html, status=400, set_cookie=set_cookie_header)
            try:
                if url not in DOC_CACHE:
                    text = extract_text_from_url(url)
                    if not text or len(text.strip()) < 200:
                        html = _render_index(error="Could not extract enough text from the provided URL.")
                        return _html_response(html, status=400, set_cookie=set_cookie_header)
                    DOC_CACHE[url] = {"text": text, "summaries": {}}
                text = DOC_CACHE[url]["text"]
                if level not in DOC_CACHE[url]["summaries"]:
                    summary = summarize_map_reduce(text, level=level)
                    DOC_CACHE[url]["summaries"][level] = summary
                else:
                    summary = DOC_CACHE[url]["summaries"][level]
                key = (sid, url)
                CHAT_HISTORY.setdefault(key, [])
                html = _render_index(paper_url=url, level=level, summary=summary)
                return _html_response(html, set_cookie=set_cookie_header)
            except Exception as e:
                html = _render_index(error=f"Error: {e}")
                return _html_response(html, status=500, set_cookie=set_cookie_header)

        # ------------- POST /chat -------------
        if raw_path == "/chat" and method == "POST":
            import json
            try:
                data = json.loads(body or '{}')
            except json.JSONDecodeError:
                return _json_response({"ok": False, "error": "Invalid JSON"}, 400, set_cookie=set_cookie_header)
            url = (data.get("paper_url") or "").strip()
            message = (data.get("message") or "").strip()
            if not url or not message:
                return _json_response({"ok": False, "error": "Missing url or message"}, 400, set_cookie=set_cookie_header)
            if url not in DOC_CACHE:
                return _json_response({"ok": False, "error": "Please summarize the paper first."}, 400, set_cookie=set_cookie_header)
            key = (sid, url)
            history = CHAT_HISTORY.setdefault(key, [])
            history.append({"role": "user", "text": message})
            try:
                answer = chat_answer(DOC_CACHE[url]["text"], history)
                history.append({"role": "model", "text": answer})
                return _json_response({"ok": True, "answer": answer}, 200, set_cookie=set_cookie_header)
            except Exception as e:
                history.pop()  # rollback user append
                return _json_response({"ok": False, "error": str(e)}, 500, set_cookie=set_cookie_header)

        # ------------- Fallback -------------
        return _html_response(_render_index(error="Not Found"), status=404, set_cookie=set_cookie_header)
    except Exception as e:
        return _html_response(f"<h1>Server Error</h1><p>{e}</p>", status=500)

# For local manual testing (optional) you can invoke lambda_handler with a mock event.
if __name__ == "__main__":
    # Simple local test (GET /)
    mock_event = {"rawPath": "/", "requestContext": {"http": {"method": "GET"}}, "headers": {}}
    resp = lambda_handler(mock_event, None)
    print(resp["statusCode"], resp["headers"])