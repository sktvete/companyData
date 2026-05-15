"""Chat tool execution (web search, URL fetch, safe math, EODHD). Mirrors gptWebsiteIntegration/tools.js."""

from __future__ import annotations

import ast
import html as html_module
import ipaddress
import json
import operator as op
import re
import socket
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests

_ALLOWED_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}
_ALLOWED_UNARYOPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}


def evaluate_math_expression(expression: str, *, max_len: int = 512) -> dict[str, Any]:
    """
    Evaluate a single arithmetic expression (+ - * / // % **, parentheses, unary +/-).
    No names, calls, imports, or comparisons — only numeric literals.
    """
    raw = (expression or "").strip()
    if not raw:
        return {"ok": False, "error": "expression is empty"}
    if len(raw) > max_len:
        return {"ok": False, "error": f"expression too long (max {max_len} chars)"}
    try:
        tree = ast.parse(raw, mode="eval")
    except SyntaxError as e:
        return {"ok": False, "error": f"syntax error: {e}"}

    def _eval(node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                raise ValueError("booleans are not allowed")
            if isinstance(v, (int, float)):
                if isinstance(v, float) and (v != v or abs(v) == float("inf")):
                    raise ValueError("non-finite numbers are not allowed")
                return v
            raise ValueError("only numeric literals allowed")
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
            return _ALLOWED_UNARYOPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError("unsupported syntax (only arithmetic on numbers)")

    try:
        assert isinstance(tree, ast.Expression)
        value = _eval(tree.body)
    except ZeroDivisionError:
        return {"ok": False, "error": "division by zero"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        disp: int | float = int(value)
    else:
        disp = value
    return {
        "ok": True,
        "result": disp,
        "result_text": str(disp),
    }


def _map_ddgs_row(r: dict) -> dict[str, str]:
    return {
        "title": str(r.get("title") or ""),
        "url": str(r.get("url") or r.get("href") or ""),
        "snippet": str(r.get("body") or r.get("description") or ""),
        "date": str(r.get("date") or ""),
        "source": str(r.get("source") or ""),
    }


def web_search(query: str, *, max_results: int = 8) -> list[dict[str, str]]:
    """DuckDuckGo search — news API first (~0.6s), then text fallback (same data as gptWebsiteIntegration)."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return [{"error": "Install ddgs: pip install ddgs"}]

    out: list[dict[str, str]] = []
    try:
        with DDGS() as ddgs:
            # Fast path: news index (best for stock / current-events queries)
            try:
                news_fn = getattr(ddgs, "news", None)
                if news_fn:
                    for r in news_fn(q, max_results=max_results):
                        if isinstance(r, dict):
                            out.append(_map_ddgs_row(r))
                        if len(out) >= max_results:
                            return out
            except Exception:
                out = []

            for r in ddgs.text(q, max_results=max_results):
                if isinstance(r, dict):
                    row = _map_ddgs_row(r)
                    if row.get("url") or row.get("title"):
                        out.append(row)
                if len(out) >= max_results:
                    break
    except Exception as e:
        return [{"error": str(e)}]
    return out


def _is_public_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _hostname_blocked(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h == "localhost" or h.endswith(".localhost"):
        return True
    if h in ("0.0.0.0", "169.254.169.254"):
        return True
    if ".." in h:
        return True
    if h.endswith(".local") or h.endswith(".internal"):
        return True
    if h.startswith("metadata") or h.endswith(".metadata.google.internal"):
        return True
    return False


def _host_addresses_safe(hostname: str) -> tuple[bool, str]:
    """Reject SSRF: loopback, RFC1918, link-local, metadata, etc."""
    try:
        ip = ipaddress.ip_address(hostname)
        if not _is_public_ip(str(ip)):
            return False, "non-public address"
        return True, ""
    except ValueError:
        pass
    if _hostname_blocked(hostname):
        return False, "host not allowed"
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"dns error: {e}"
    if not infos:
        return False, "no addresses"
    for info in infos:
        ip_str = info[4][0]
        if not _is_public_ip(ip_str):
            return False, "non-public address"
    return True, ""


def _validate_fetch_url(url: str) -> tuple[bool, str, str]:
    """Return (ok, error, normalized_url)."""
    raw = (url or "").strip()
    if not raw:
        return False, "url is empty", ""
    if len(raw) > 2048:
        return False, "url too long", ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return False, "only http/https URLs are allowed", ""
    host = parsed.hostname
    if not host:
        return False, "missing host", ""
    ok, err = _host_addresses_safe(host)
    if not ok:
        return False, err, ""
    return True, "", raw


def _content_type_is_textual(ctype: str) -> bool:
    base = (ctype or "").split(";")[0].strip().lower()
    if not base:
        return True
    return base in (
        "text/html",
        "text/plain",
        "application/json",
        "application/xhtml+xml",
    ) or base.startswith("text/")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "template", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "template", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        t = data.strip()
        if t:
            self._chunks.append(t)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>([^<]{0,500})</title>", html, re.I | re.S)
    if not m:
        return ""
    return html_module.unescape(re.sub(r"\s+", " ", m.group(1)).strip())[:240]


def _html_to_plain(html: str) -> str:
    ex = _HTMLTextExtractor()
    try:
        ex.feed(html)
        ex.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return ex.text()


def fetch_web_page(
    url: str,
    *,
    max_bytes: int = 750_000,
    max_text_chars: int = 14_000,
    timeout: float = 18.0,
    max_redirects: int = 5,
) -> dict[str, Any]:
    """
    HTTP GET a single public http(s) URL; return extracted text (HTML stripped) or error.
    No browser — server-side fetch only, with basic SSRF protection.
    """
    current = (url or "").strip()
    seen_norm: set[str] = set()
    headers = {
        "User-Agent": (
            "companyData-chat-fetch/1.0 (stock dashboard reader; +https://github.com/)"
        ),
        "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.5",
    }

    for _hop in range(max_redirects + 1):
        ok, err, norm = _validate_fetch_url(current)
        if not ok:
            return {"ok": False, "error": err, "url": (current or None)}
        key = norm.rstrip("/").lower()
        if key in seen_norm:
            return {"ok": False, "error": "redirect loop", "url": norm}
        seen_norm.add(key)

        try:
            r = requests.get(norm, timeout=timeout, headers=headers, stream=True, allow_redirects=False)
        except requests.RequestException as e:
            return {"ok": False, "error": str(e), "url": norm}
        try:
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                if not loc:
                    return {"ok": False, "error": "redirect without Location", "url": norm}
                current = urljoin(norm, loc.strip())
                continue

            if r.status_code >= 400:
                return {"ok": False, "error": f"HTTP {r.status_code}", "url": norm}

            ctype = r.headers.get("Content-Type") or ""
            parts: list[bytes] = []
            total = 0
            for piece in r.iter_content(chunk_size=65536):
                if not piece:
                    continue
                total += len(piece)
                if total > max_bytes:
                    return {"ok": False, "error": "response too large", "url": norm}
                parts.append(piece)
            raw_body = b"".join(parts)
        finally:
            r.close()

        if not _content_type_is_textual(ctype):
            return {
                "ok": False,
                "error": f"non-text content ({ctype or 'unknown'}); try web_search or another URL",
                "url": norm,
            }

        enc = r.encoding or "utf-8"
        try:
            body = raw_body.decode(enc, errors="replace")
        except LookupError:
            body = raw_body.decode("utf-8", errors="replace")

        title = _extract_title(body) if "html" in ctype.lower() else ""
        if "json" in ctype.lower():
            plain = body.strip()
        else:
            plain = _html_to_plain(body) if "html" in ctype.lower() else body.strip()

        if len(plain) > max_text_chars:
            plain = plain[:max_text_chars] + "\n…[truncated]"

        out: dict[str, Any] = {
            "ok": True,
            "url": norm,
            "title": title or None,
            "content_type": ctype.split(";")[0].strip() or None,
            "text": plain,
        }
        return out

    return {"ok": False, "error": "too many redirects", "url": current}


def execute_chat_tool(
    name: str,
    args: dict[str, Any],
    *,
    eodhd_snapshot: Callable[[str, str], str],
    default_symbol: str = "",
) -> str:
    """Run a chat tool; returns JSON string for the model."""
    try:
        if name == "web_search":
            query = str(args.get("query") or "").strip()
            if not query and default_symbol:
                query = f"{default_symbol} stock news"
            data = web_search(query)
            return json.dumps(data, ensure_ascii=False)[:12000]

        if name == "eodhd_fundamentals_snapshot":
            detail = args.get("detail_level") or "summary"
            if detail not in ("summary", "financials"):
                detail = "summary"
            sym = default_symbol or str(args.get("symbol") or "")
            return eodhd_snapshot(sym, detail)

        if name == "evaluate_math":
            expr = str(args.get("expression") or "")
            data = evaluate_math_expression(expr)
            return json.dumps(data, ensure_ascii=False)

        if name == "fetch_web_page":
            u = str(args.get("url") or "").strip()
            data = fetch_web_page(u)
            return json.dumps(data, ensure_ascii=False)[:14000]

        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})
