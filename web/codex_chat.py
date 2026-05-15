"""
ChatGPT subscription chat via OAuth PKCE + Codex Responses API.
Session persisted to outputs/.chatgpt_session.json (refresh token → no re-login).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Generator
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPES = "openid profile email offline_access"
SESSION_FILENAME = ".chatgpt_session.json"

_lock = threading.Lock()
_oauth_lock = threading.Lock()
_pending: dict[str, Any] | None = None


def session_path(project_root: Path) -> Path:
    p = project_root / "outputs" / SESSION_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_session(project_root: Path) -> dict:
    fp = session_path(project_root)
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {
        "accessToken": None,
        "refreshToken": None,
        "expiresAt": 0,
        "accountId": None,
    }


def _save_session(project_root: Path, session: dict) -> None:
    session_path(project_root).write_text(
        json.dumps(session, indent=2), encoding="utf-8"
    )


def _extract_account_id(access_token: str) -> str | None:
    try:
        payload_b64 = access_token.split(".")[1]
        pad = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
        auth = payload.get("https://api.openai.com/auth") or {}
        return auth.get("chatgpt_account_id")
    except Exception:
        return None


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(32)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _build_auth_url(verifier: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _exchange_code(verifier: str, code: str) -> dict:
    res = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=60,
    )
    if not res.ok:
        raise RuntimeError(f"Token exchange failed: {res.status_code} {res.text[:500]}")
    return res.json()


def _refresh_token(session: dict) -> dict:
    res = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": session["refreshToken"],
            "client_id": CLIENT_ID,
        },
        timeout=60,
    )
    if not res.ok:
        raise RuntimeError(f"Token refresh failed: {res.status_code} {res.text[:500]}")
    return res.json()


def ensure_valid_token(project_root: Path) -> dict:
    with _lock:
        session = _load_session(project_root)
        if not session.get("accessToken"):
            raise RuntimeError("Not authenticated. Sign in with ChatGPT.")
        if time.time() > float(session.get("expiresAt") or 0) - 60:
            if not session.get("refreshToken"):
                raise RuntimeError("Session expired. Sign in again.")
            data = _refresh_token(session)
            session["accessToken"] = data["access_token"]
            session["refreshToken"] = data.get("refresh_token") or session["refreshToken"]
            session["expiresAt"] = time.time() + float(data.get("expires_in", 3600))
            session["accountId"] = _extract_account_id(session["accessToken"])
            _save_session(project_root, session)
        return session


def auth_status(project_root: Path) -> dict:
    session = _load_session(project_root)
    ok = bool(session.get("accessToken")) and time.time() < float(session.get("expiresAt") or 0) - 30
    if ok:
        return {"authenticated": True, "accountId": session.get("accountId")}
    if session.get("refreshToken"):
        try:
            ensure_valid_token(project_root)
            session = _load_session(project_root)
            return {"authenticated": True, "accountId": session.get("accountId")}
        except Exception:
            pass
    with _oauth_lock:
        pending = _pending is not None and not _pending.get("done")
    return {"authenticated": False, "loginInProgress": pending}


def logout(project_root: Path) -> None:
    with _lock:
        fp = session_path(project_root)
        if fp.is_file():
            fp.unlink()
    global _pending
    with _oauth_lock:
        _pending = None


def _make_callback_handler(holder: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_error(404)
                return
            qs = parse_qs(parsed.query)
            err = qs.get("error", [None])[0]
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]
            with _oauth_lock:
                if holder.get("state") and state != holder["state"]:
                    holder["error"] = "OAuth state mismatch"
                elif err:
                    holder["error"] = err
                elif code:
                    holder["code"] = code
                else:
                    holder["error"] = "No authorization code"
                holder["event"].set()
            body = (
                "<html><body style='font-family:sans-serif;background:#0b0f19;color:#e2e8f0;"
                "display:flex;align-items:center;justify-content:center;height:100vh'>"
                "<div><h2>Signed in</h2><p>You can close this tab and return to EquityOS.</p></div></body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _run_oauth_server(holder: dict) -> None:
    server = HTTPServer(("127.0.0.1", 1455), _make_callback_handler(holder))
    holder["server"] = server
    server.timeout = 1
    deadline = time.time() + 300
    while time.time() < deadline and not holder["event"].is_set():
        server.handle_request()
    try:
        server.server_close()
    except Exception:
        pass


def _finish_login(project_root: Path, holder: dict) -> None:
    global _pending
    try:
        if holder.get("error"):
            raise RuntimeError(holder["error"])
        code = holder.get("code")
        if not code:
            raise RuntimeError("Login timed out or was cancelled")
        data = _exchange_code(holder["verifier"], code)
        session = {
            "accessToken": data["access_token"],
            "refreshToken": data.get("refresh_token"),
            "expiresAt": time.time() + float(data.get("expires_in", 3600)),
            "accountId": _extract_account_id(data["access_token"]),
        }
        _save_session(project_root, session)
    finally:
        with _oauth_lock:
            if _pending is holder:
                holder["done"] = True


def start_login(project_root: Path) -> str:
    """Start OAuth flow; returns authorization URL. Callback on port 1455."""
    global _pending
    status = auth_status(project_root)
    if status.get("authenticated"):
        raise RuntimeError("Already signed in")

    with _oauth_lock:
        if _pending and not _pending.get("done"):
            return _pending["authUrl"]

        verifier = _pkce_verifier()
        state = secrets.token_hex(16)
        holder: dict[str, Any] = {
            "verifier": verifier,
            "state": state,
            "event": threading.Event(),
            "code": None,
            "error": None,
            "done": False,
            "authUrl": _build_auth_url(verifier, state),
        }
        _pending = holder

    threading.Thread(target=_run_oauth_server, args=(holder,), daemon=True).start()
    threading.Thread(target=lambda: (holder["event"].wait(300), _finish_login(project_root, holder)), daemon=True).start()
    return holder["authUrl"]


def openai_tools_to_codex(tools: list) -> list:
    out = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            fn = t["function"]
            out.append({
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        elif t.get("type") == "function" and t.get("name"):
            out.append(t)
    return out


def _line_str(raw) -> str | None:
    """Normalize iter_lines() output to a stripped string."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace").strip()
    return str(raw).strip()


def _iter_sse_json(resp: requests.Response):
    """Parse SSE data: lines from a Codex/Responses stream."""
    for raw in resp.iter_lines():
        line = _line_str(raw)
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data: "):
            continue
        data = line[6:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


def messages_to_codex(messages: list[dict]) -> tuple[str, list]:
    instructions = ""
    inp: list = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            instructions = str(content)
        elif role == "user":
            inp.append({
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": str(content)}],
            })
        elif role == "assistant":
            inp.append({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": str(content)}],
            })
    return instructions, inp


def _parse_sse_lines(chunk: str, buffer: list[str]) -> list[dict]:
    buffer.append(chunk)
    text = "".join(buffer)
    if not text.endswith("\n"):
        return []
    buffer.clear()
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        data = line[6:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            events.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return events


def _collect_function_calls_from_stream(resp: requests.Response) -> tuple[list[dict], str]:
    """Returns (function_calls, accumulated_text)."""
    buffer: list[str] = []
    pending: dict[int, dict] = {}
    function_calls: list[dict] = []
    text_parts: list[str] = []

    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        if raw.startswith(":"):
            continue
        if not raw.startswith("data: "):
            continue
        data = raw[6:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue

        et = event.get("type", "")
        if et == "response.output_text.delta" and event.get("delta"):
            text_parts.append(event["delta"])
        elif et == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                idx = event.get("output_index", 0)
                pending[idx] = {
                    "name": item.get("name"),
                    "callId": item.get("call_id"),
                    "args": "",
                    "id": item.get("id"),
                }
        elif et == "response.function_call_arguments.delta":
            idx = event.get("output_index", 0)
            if idx not in pending:
                pending[idx] = {"args": ""}
            pending[idx]["args"] = pending[idx].get("args", "") + (event.get("delta") or "")
        elif et == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                function_calls.append({
                    "id": item.get("id") or f"fc_{secrets.token_hex(12)}",
                    "name": item.get("name"),
                    "callId": item.get("call_id"),
                    "arguments": args,
                })

    return function_calls, "".join(text_parts)


def stream_codex_chat(
    project_root: Path,
    *,
    model: str,
    messages: list[dict],
    tools: list,
    tool_executor: Callable[[str, dict], str],
    max_tool_rounds: int = 5,
) -> Generator[dict, None, None]:
    """
    Yields dict events: {token}, {phase: tool}, {error}, {done}, {model}.
    """
    session = ensure_valid_token(project_root)
    instructions, current_input = messages_to_codex(messages)
    codex_tools = openai_tools_to_codex(tools)

    for _round in range(max_tool_rounds):
        body = {
            "model": model,
            "instructions": instructions,
            "stream": True,
            "store": False,
            "tools": codex_tools,
            "input": current_input,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {session['accessToken']}",
        }
        resp = requests.post(
            RESPONSES_URL,
            headers=headers,
            json=body,
            stream=True,
            timeout=300,
        )
        if not resp.ok:
            yield {"error": f"Codex API {resp.status_code}: {resp.text[:800]}", "done": True}
            return

        function_calls: list[dict] = []
        pending: dict[int, dict] = {}

        for event in _iter_sse_json(resp):
            et = event.get("type", "")
            if et == "response.output_text.delta" and event.get("delta"):
                yield {"token": event["delta"]}
            elif et == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    idx = event.get("output_index", 0)
                    pending[idx] = {
                        "name": item.get("name"),
                        "callId": item.get("call_id"),
                        "id": item.get("id"),
                    }
            elif et == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    try:
                        args = json.loads(item.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    function_calls.append({
                        "id": item.get("id") or f"fc_{secrets.token_hex(12)}",
                        "name": item.get("name"),
                        "callId": item.get("call_id"),
                        "arguments": args,
                    })

        if function_calls:
            follow_up: list = []
            for fc in function_calls:
                yield {"phase": "tool", "tool": fc.get("name")}
                follow_up.append({
                    "type": "function_call",
                    "id": fc["id"],
                    "call_id": fc["callId"],
                    "name": fc["name"],
                    "arguments": json.dumps(fc["arguments"]),
                })
            n_workers = min(len(function_calls), 8)

            def _run(fc: dict) -> tuple[dict, str]:
                out = tool_executor(fc["name"], fc["arguments"])
                return fc, out if isinstance(out, str) else json.dumps(out)

            if n_workers <= 1:
                results = [_run(fc) for fc in function_calls]
            else:
                with ThreadPoolExecutor(max_workers=n_workers) as pool:
                    results = list(pool.map(_run, function_calls))

            for fc, result in results:
                follow_up.append({
                    "type": "function_call_output",
                    "call_id": fc["callId"],
                    "output": result,
                })
            current_input = [*current_input, *follow_up]
            continue

        yield {"done": True, "model": model}
        return

    yield {"error": "Too many tool rounds", "done": True}
