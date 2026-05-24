"""
Local OpenAI-backed stock analyzer.

Used by the /api/moonstocks/<ticker>/analyze-stream endpoint so users can
run an analysis with their own OpenAI API key.  The EODHD data is fetched
server-side using the app's EODHD_API_KEY; OpenAI calls use the *user's*
key, so token costs come from the user's account.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Generator

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill-file helpers (reuse from moonstocks-ai-analyzer or agent/skills)
# ---------------------------------------------------------------------------

_SKILL_DIRS = [
    Path(__file__).resolve().parent.parent / "moonstocks-ai-analyzer" / ".claude" / "skills" / "stock-analysis",
    Path(__file__).resolve().parent.parent / "agent" / "skills" / "stock-analysis",
]


def _skill_dir() -> Path | None:
    for d in _SKILL_DIRS:
        if d.is_dir():
            return d
    return None


def _read_skill(name: str) -> str:
    d = _skill_dir()
    if not d:
        return ""
    p = d / name
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].lstrip()
    return text


def build_system_prompt() -> str:
    d = _skill_dir()
    schema = ""
    if d and (d / "output-schema.json").is_file():
        schema = (d / "output-schema.json").read_text(encoding="utf-8")

    parts = [
        _read_skill("SKILL.md"),
        _read_skill("hard-rules.md"),
        _read_skill("scoring-methodology.md"),
        ("Output JSON must conform to this schema:\n" + schema) if schema else "",
        (
            "You are a JSON-only API.  Your entire reply must be one JSON object "
            "starting with '{' and ending with '}'.  No markdown, no code fences."
        ),
    ]
    return "\n\n---\n\n".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# EODHD data fetching (server-side, uses EODHD_API_KEY env var)
# ---------------------------------------------------------------------------

EODHD_BASE = "https://eodhistoricaldata.com/api"


def _eodhd_key() -> str:
    key = (os.environ.get("EODHD_API_KEY") or "").strip()
    if not key:
        raise ValueError("EODHD_API_KEY is not configured on the server.")
    return key


def _eodhd_get(client: httpx.Client, path: str, params: dict | None = None):
    p = {"api_token": _eodhd_key(), "fmt": "json", **(params or {})}
    resp = client.get(f"{EODHD_BASE}/{path.lstrip('/')}", params=p, timeout=90)
    resp.raise_for_status()
    return resp.json()


def _trim_financials(fin: dict | None) -> dict | None:
    if not fin or not isinstance(fin, dict):
        return fin
    out: dict = {}
    for stmt in ("Income_Statement", "Balance_Sheet", "Cash_Flow"):
        block = fin.get(stmt)
        if not isinstance(block, dict):
            continue
        def _last_n(sec, n):
            if not isinstance(sec, dict):
                return sec
            keys = sorted(sec.keys(), reverse=True)[:n]
            return {k: sec[k] for k in keys}
        out[stmt] = {
            "yearly":    _last_n(block.get("yearly"), 3),
            "quarterly": _last_n(block.get("quarterly"), 4),
        }
    return out or fin


def fetch_eodhd_bundle(symbol: str) -> dict:
    """Fetch and compact EODHD data for *symbol* (e.g. 'META.US')."""
    today  = date.today()
    yr_ago = today - timedelta(days=365)
    with httpx.Client() as client:
        fund = _eodhd_get(client, f"fundamentals/{symbol}")
        prices = _eodhd_get(client, f"eod/{symbol}", {
            "from": yr_ago.isoformat(), "to": today.isoformat(), "period": "d",
        })
        try:
            live = _eodhd_get(client, f"real-time/{symbol}")
        except httpx.HTTPError:
            live = None
        try:
            trends = _eodhd_get(client, "calendar/earnings", {"symbols": symbol})
        except httpx.HTTPError:
            trends = None

    keep = ("General", "Highlights", "Valuation", "SharesStats", "Technicals",
            "AnalystRatings", "Earnings")
    trimmed_fund = {k: fund[k] for k in keep if k in fund}
    if "Financials" in fund:
        trimmed_fund["Financials"] = _trim_financials(fund.get("Financials"))

    bundle: dict = {
        "fundamentals": trimmed_fund,
        "historical_prices_daily": (prices[-60:] if isinstance(prices, list) else prices),
        "live_price":       live,
        "earnings_trends":  trends,
    }

    # Trim earnings trend to last 16 keys
    earn = bundle["fundamentals"].get("Earnings", {})
    trend = earn.get("Trend") if isinstance(earn, dict) else None
    if isinstance(trend, dict):
        keys = sorted(trend.keys(), reverse=True)[:16]
        earn["Trend"] = {k: trend[k] for k in keys}

    # Compact to stay under ~32 k chars
    MAX_CHARS = 32_000
    while len(json.dumps(bundle, default=str)) > MAX_CHARS:
        p = bundle.get("historical_prices_daily")
        if isinstance(p, list) and len(p) > 30:
            bundle["historical_prices_daily"] = p[-30:]
            continue
        break

    return bundle


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_user_prompt(ticker_exchange: str, bundle: dict) -> str:
    ticker, exchange = (ticker_exchange.split(".", 1) + ["US"])[:2]
    header = (
        f"Analyze this US equity using ONLY the attached EODHD data.\n"
        f"Apply the stock-analysis skill, hard rules, and scoring methodology.\n\n"
        f'Input: {{"ticker": "{ticker}", "exchange": "{exchange}"}}\n'
        f"analysis_date should be {date.today().isoformat()}.\n"
        f"time_horizon must be long_term_1y_plus.\n\n"
        f"EODHD_DATA:\n"
    )
    return header + json.dumps(bundle, default=str)


# ---------------------------------------------------------------------------
# Streaming analysis generator
# ---------------------------------------------------------------------------

def parse_json_report(text: str) -> dict:
    s = text.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


def analyze_stream_codex(
    ticker_exchange: str,
    project_root,
    model: str = "gpt-5.3-codex",
) -> Generator[dict, None, None]:
    """
    Same as analyze_stream but runs through the ChatGPT OAuth session
    (codex/responses API) so the user's ChatGPT subscription pays for it.
    No API key required.
    """
    import codex_chat

    yield {"type": "status", "text": f"Fetching EODHD data for {ticker_exchange}…"}
    try:
        bundle = fetch_eodhd_bundle(ticker_exchange)
    except Exception as exc:
        yield {"type": "error", "text": f"EODHD fetch failed: {exc}"}
        return

    yield {"type": "status", "text": "Data ready.  Starting AI analysis via ChatGPT…\n\n"}

    system_prompt = build_system_prompt()
    user_prompt   = build_user_prompt(ticker_exchange, bundle)

    messages = [
        {"role": "system",    "content": system_prompt},
        {"role": "user",      "content": user_prompt},
    ]

    full_text = ""
    try:
        for evt in codex_chat.stream_codex_chat(
            project_root,
            model=model,
            messages=messages,
            tools=[],
            tool_executor=lambda name, args: "",
        ):
            if evt.get("token"):
                full_text += evt["token"]
                yield {"type": "token", "text": evt["token"]}
            elif evt.get("error"):
                yield {"type": "error", "text": evt["error"]}
                return
            elif evt.get("done"):
                break
    except Exception as exc:
        yield {"type": "error", "text": f"ChatGPT stream failed: {exc}"}
        return

    yield {"type": "status", "text": "\n\nParsing and saving report…"}
    try:
        report = parse_json_report(full_text)
        report.setdefault("ticker",   ticker_exchange.split(".")[0])
        report.setdefault("exchange", (ticker_exchange.split(".", 1) + ["US"])[1])
        yield {"type": "done", "report": report, "raw": full_text}
    except Exception as exc:
        yield {"type": "error", "text": f"JSON parse failed: {exc}\n\nRaw output:\n{full_text[:800]}"}


def analyze_stream(
    ticker_exchange: str,
    openai_api_key: str,
    model: str = "gpt-4.1-mini",
    reasoning_effort: str | None = None,
) -> Generator[dict, None, None]:
    """
    Generator that yields dicts:
      {"type": "status", "text": "..."}   — progress notes
      {"type": "token",  "text": "..."}   — raw OpenAI output token
      {"type": "done",   "report": {...}} — final parsed report
      {"type": "error",  "text": "..."}   — on failure
    """
    from openai import OpenAI  # imported here so it's optional at module load

    yield {"type": "status", "text": f"Fetching EODHD data for {ticker_exchange}…"}
    try:
        bundle = fetch_eodhd_bundle(ticker_exchange)
    except Exception as exc:
        yield {"type": "error", "text": f"EODHD fetch failed: {exc}"}
        return

    effort_label = f" (reasoning: {reasoning_effort})" if reasoning_effort else ""
    yield {"type": "status", "text": f"Data ready.  Starting AI analysis{effort_label}…\n\n"}

    system_prompt = build_system_prompt()
    user_prompt   = build_user_prompt(ticker_exchange, bundle)

    call_kwargs: dict = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        stream=True,
    )
    if reasoning_effort:
        call_kwargs["reasoning_effort"] = reasoning_effort
    else:
        call_kwargs["temperature"] = 0.2

    try:
        client = OpenAI(api_key=openai_api_key)
        stream = client.chat.completions.create(**call_kwargs)
    except Exception as exc:
        yield {"type": "error", "text": f"OpenAI call failed: {exc}"}
        return

    full_text = ""
    try:
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text += delta
                yield {"type": "token", "text": delta}
    except Exception as exc:
        yield {"type": "error", "text": f"Stream interrupted: {exc}"}
        return

    yield {"type": "status", "text": "\n\nParsing and saving report…"}
    try:
        report = parse_json_report(full_text)
        report.setdefault("ticker",   ticker_exchange.split(".")[0])
        report.setdefault("exchange", (ticker_exchange.split(".", 1) + ["US"])[1])
        yield {"type": "done", "report": report, "raw": full_text}
    except Exception as exc:
        yield {"type": "error", "text": f"JSON parse failed: {exc}\n\nRaw output:\n{full_text[:800]}"}
