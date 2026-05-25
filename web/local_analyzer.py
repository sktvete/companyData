"""
Local OpenAI-backed stock analyzer.

The AI receives a small context card (ticker, date) and is given EODHD tools
it can call on demand — fundamentals, price history, news — mirroring the tool
usage visible in the chat.  Token costs come from the user's account.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Generator

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill-file helpers
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

    tool_preamble = (
        "You are a senior equity analyst with access to real-time market data tools.\n\n"
        "RESEARCH WORKFLOW — you MUST follow every step before writing the report:\n"
        "1. Call eodhd_fundamentals to get financials, analyst ratings, and earnings history.\n"
        "2. Call eodhd_price_history to get recent price action and technicals.\n"
        "3. Call eodhd_news to scan for recent catalysts, earnings surprises, or risks.\n"
        "4. MANDATORY REFLECTION: After gathering initial data, identify at least ONE area "
        "that deserves a closer look — unusual margin moves, revenue acceleration/deceleration, "
        "high debt, a recent miss/beat, an acquisition, regulatory risk, or any metric that "
        "looks different from the trend. You MUST call at least one tool to investigate this "
        "further before writing. Examples: re-fetch news with a different focus, fetch "
        "fundamentals for a direct competitor, or re-check price history around a key date.\n"
        "5. If the follow-up reveals new concerns or opportunities, do one more round (up to "
        "3 total follow-up rounds). Stop only when you have enough grounded evidence to write "
        "a complete, specific, well-sourced report.\n"
        "6. Only then produce the JSON report — no other text, no commentary outside the JSON.\n\n"
        "IMPORTANT: Skipping step 4 is not allowed. You must always do at least 4 tool calls "
        "(3 initial + at least 1 follow-up) before writing.\n"
    )

    parts = [
        tool_preamble,
        _read_skill("SKILL.md"),
        _read_skill("hard-rules.md"),
        _read_skill("scoring-methodology.md"),
        ("Output JSON must conform to this schema:\n" + schema) if schema else "",
        (
            "Your entire reply must be one JSON object "
            "starting with '{' and ending with '}'.  No markdown, no code fences."
        ),
    ]
    return "\n\n---\n\n".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# EODHD fetchers (server-side key)
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
            "yearly":    _last_n(block.get("yearly"), 4),
            "quarterly": _last_n(block.get("quarterly"), 6),
        }
    return out or fin


# ---------------------------------------------------------------------------
# Tool definitions (Codex / OpenAI Responses format)
# ---------------------------------------------------------------------------

# These are in the Codex top-level format (name at root).
# For OpenAI chat.completions they get wrapped below.
ANALYSIS_TOOLS: list[dict] = [
    {
        "type": "function",
        "name": "eodhd_fundamentals",
        "description": (
            "Fetch full company fundamentals from EODHD: income statement, balance sheet, "
            "cash flow (last 4 years / 6 quarters), analyst ratings, earnings history & trends."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker with exchange suffix, e.g. 'META.US', 'TSM.US'",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "type": "function",
        "name": "eodhd_price_history",
        "description": "Fetch daily OHLCV price history for the past 365 days.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker with exchange suffix",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "type": "function",
        "name": "eodhd_news",
        "description": "Fetch the 15 most recent news articles for the company.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker with exchange suffix",
                }
            },
            "required": ["symbol"],
        },
    },
]

# OpenAI chat.completions wraps each tool in {"type":"function","function":{...}}
_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {k: v for k, v in t.items() if k != "type"},
    }
    for t in ANALYSIS_TOOLS
]


def _make_tool_executor(default_symbol: str) -> Callable[[str, dict], str]:
    """Returns a function(name, args) → JSON-string that calls EODHD."""

    def executor(name: str, args: dict) -> str:
        symbol = args.get("symbol") or default_symbol
        try:
            with httpx.Client() as client:
                if name == "eodhd_fundamentals":
                    data = _eodhd_get(client, f"fundamentals/{symbol}")
                    keep = ("General", "Highlights", "Valuation", "SharesStats",
                            "Technicals", "AnalystRatings", "Earnings")
                    trimmed = {k: data[k] for k in keep if k in data}
                    if "Financials" in data:
                        trimmed["Financials"] = _trim_financials(data["Financials"])
                    earn = trimmed.get("Earnings", {})
                    trend = earn.get("Trend") if isinstance(earn, dict) else None
                    if isinstance(trend, dict):
                        keys = sorted(trend.keys(), reverse=True)[:16]
                        earn["Trend"] = {k: trend[k] for k in keys}
                    raw = json.dumps(trimmed, default=str)
                    return raw[:40_000]  # stay within context budget

                elif name == "eodhd_price_history":
                    today  = date.today()
                    yr_ago = today - timedelta(days=365)
                    data   = _eodhd_get(client, f"eod/{symbol}", {
                        "from": yr_ago.isoformat(), "to": today.isoformat(), "period": "d",
                    })
                    prices = data[-60:] if isinstance(data, list) else data
                    return json.dumps(prices, default=str)[:8_000]

                elif name == "eodhd_news":
                    data = _eodhd_get(client, "news", {"s": symbol, "limit": 15})
                    # Keep key fields; trim 'content' to a short excerpt so we can
                    # pass 10+ articles without hitting token limits.
                    if isinstance(data, list):
                        slim = []
                        for item in (data if isinstance(data, list) else []):
                            slim.append({
                                "date":      item.get("date", ""),
                                "title":     item.get("title", ""),
                                "link":      item.get("link", ""),
                                "sentiment": item.get("sentiment"),
                                "content":   (item.get("content") or "")[:300],
                            })
                        data = slim
                    return json.dumps(data, default=str)

                else:
                    return json.dumps({"error": f"Unknown tool: {name}"})

        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return executor


# ---------------------------------------------------------------------------
# JSON report parser
# ---------------------------------------------------------------------------

def _extract_news_sites(result_json_str: str) -> list[str]:
    """Return up to 5 unique domain names from EODHD news link fields."""
    from urllib.parse import urlparse
    try:
        news = json.loads(result_json_str)
        seen, sites = set(), []
        for item in (news if isinstance(news, list) else []):
            link = (item.get("link") or "").strip()
            if not link:
                continue
            host = urlparse(link).netloc.lower().replace("www.", "")
            if host and host not in seen:
                seen.add(host)
                sites.append(host)
            if len(sites) >= 5:
                break
        return sites
    except Exception:
        return []


def parse_json_report(text: str) -> dict:
    s = text.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


# ---------------------------------------------------------------------------
# Codex (ChatGPT account) streaming analysis
# ---------------------------------------------------------------------------

def analyze_stream_codex(
    ticker_exchange: str,
    project_root,
    model: str | None = None,
) -> Generator[dict, None, None]:
    model = model or os.getenv("OPENAI_MODEL") or "gpt-5.3-codex"
    """
    Yields SSE-compatible dicts. The AI uses EODHD tools on demand —
    visible as {type:"tool"} events — then produces the JSON report.
    """
    import codex_chat  # local import; optional dependency

    yield {"type": "status", "text": "Starting AI analysis via ChatGPT…\n\n"}

    system_prompt = build_system_prompt()
    user_msg = (
        f"Analyze {ticker_exchange}.\n"
        f"analysis_date: {date.today().isoformat()}\n"
        f"time_horizon: long_term_1y_plus\n"
        "Follow the research workflow in the system prompt exactly:\n"
        "1. Call eodhd_fundamentals, eodhd_price_history, and eodhd_news.\n"
        "2. Review what you found. Pick one specific concern or outlier and do a targeted follow-up call.\n"
        "3. Only after at least 4 tool calls total, output the JSON report and nothing else."
    )

    messages = [
        {"role": "system",  "content": system_prompt},
        {"role": "user",    "content": user_msg},
    ]

    tool_executor = _make_tool_executor(ticker_exchange)

    full_text = ""
    try:
        _REFLECTION = (
            "You have completed your initial data gathering. "
            "Before writing the report, take a moment to reflect:\n"
            "1. What do you know with high confidence?\n"
            "2. Is there anything unusual, ambiguous, or incomplete — "
            "a margin move, debt level, earnings miss, guidance cut, acquisition, or valuation outlier "
            "— that you should verify or dig into further?\n"
            "3. If YES: call the relevant tool now to investigate. "
            "If NO: proceed directly to outputting the JSON report."
        )
        for evt in codex_chat.stream_codex_chat(
            project_root,
            model=model,
            messages=messages,
            tools=ANALYSIS_TOOLS,
            tool_executor=tool_executor,
            max_tool_rounds=14,
            min_tool_rounds=0,  # reflection handles this more gracefully now
            reflection_prompt=_REFLECTION,
            reflect_after_n_calls=3,
        ):
            if evt.get("token"):
                full_text += evt["token"]
                yield {"type": "token", "text": evt["token"]}
            elif evt.get("phase") == "tool":
                yield {"type": "tool", "tool": evt.get("tool", ""), "symbol": ticker_exchange}
            elif evt.get("phase") == "reflect":
                yield {"type": "status", "text": "Reflecting on research…"}
            elif evt.get("phase") == "tool_result" and evt.get("tool") == "eodhd_news":
                sites = _extract_news_sites(evt.get("output", "[]"))
                if sites:
                    yield {"type": "tool_sites", "sites": sites}
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
        report["_model"] = model
        yield {"type": "done", "report": report, "raw": full_text}
    except Exception as exc:
        yield {"type": "error", "text": f"JSON parse failed: {exc}\n\nRaw output:\n{full_text[:800]}"}


# ---------------------------------------------------------------------------
# API-key streaming analysis (tool-calling loop)
# ---------------------------------------------------------------------------

def analyze_stream(
    ticker_exchange: str,
    openai_api_key: str,
    model: str = "gpt-4.1-mini",
    reasoning_effort: str | None = None,
) -> Generator[dict, None, None]:
    """
    Generator that yields dicts:
      {"type": "status", "text": "..."}    — progress notes
      {"type": "tool",   "tool": "...", "symbol": "..."}  — tool call
      {"type": "token",  "text": "..."}    — raw output token
      {"type": "done",   "report": {...}}  — final parsed report
      {"type": "error",  "text": "..."}    — on failure
    """
    from openai import OpenAI

    effort_label = f" (reasoning: {reasoning_effort})" if reasoning_effort else ""
    yield {"type": "status", "text": f"Starting AI analysis{effort_label}…\n\n"}

    system_prompt = build_system_prompt()
    user_msg = (
        f"Analyze {ticker_exchange}.\n"
        f"analysis_date: {date.today().isoformat()}\n"
        f"time_horizon: long_term_1y_plus\n"
        "Follow the research workflow in the system prompt exactly:\n"
        "1. Call eodhd_fundamentals, eodhd_price_history, and eodhd_news.\n"
        "2. Review what you found. Pick one specific concern or outlier and do a targeted follow-up call.\n"
        "3. Only after at least 4 tool calls total, output the JSON report and nothing else."
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_msg},
    ]

    tool_executor = _make_tool_executor(ticker_exchange)

    try:
        client = OpenAI(api_key=openai_api_key)
    except Exception as exc:
        yield {"type": "error", "text": f"OpenAI init failed: {exc}"}
        return

    full_text = ""
    MAX_ROUNDS = 14

    _total_tool_calls = 0    # individual tool invocations counted across all rounds
    _reflection_injected = False  # inject exactly once after initial research

    _REFLECTION_PROMPT = (
        "You have completed your initial data gathering. "
        "Before writing the report, take a moment to reflect:\n"
        "1. What do you know with high confidence?\n"
        "2. Is there anything unusual, ambiguous, or incomplete — "
        "a margin move, debt level, earnings miss, guidance cut, acquisition, or valuation outlier "
        "— that you should verify or dig into further?\n"
        "3. If YES: call the relevant tool now to investigate. "
        "If NO: proceed directly to outputting the JSON report."
    )

    for _round in range(MAX_ROUNDS):
        call_kwargs: dict = dict(
            model=model,
            messages=messages,
            tools=_OPENAI_TOOLS,
            stream=True,
        )
        if reasoning_effort:
            call_kwargs["reasoning_effort"] = reasoning_effort
        else:
            call_kwargs["temperature"] = 0.2

        try:
            stream = client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            yield {"type": "error", "text": f"OpenAI call failed: {exc}"}
            return

        # Accumulate streaming response
        delta_text   = ""
        pending_tcs: dict[int, dict] = {}  # index → {id, name, args}
        finish_reason = None

        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta

                if delta.content:
                    delta_text += delta.content
                    full_text  += delta.content
                    yield {"type": "token", "text": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in pending_tcs:
                            pending_tcs[idx] = {
                                "id":   tc.id or "",
                                "name": (tc.function.name if tc.function else "") or "",
                                "args": "",
                            }
                        if tc.id and not pending_tcs[idx]["id"]:
                            pending_tcs[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name and not pending_tcs[idx]["name"]:
                                pending_tcs[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                pending_tcs[idx]["args"] += tc.function.arguments
        except Exception as exc:
            yield {"type": "error", "text": f"Stream interrupted: {exc}"}
            return

        if pending_tcs:
            # Append the assistant message that triggered tool calls
            messages.append({
                "role": "assistant",
                "content": delta_text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    }
                    for _, tc in sorted(pending_tcs.items())
                ],
            })

            # Execute each tool, then emit event (post-execution so we can include sites)
            for _, tc in sorted(pending_tcs.items()):
                try:
                    args = json.loads(tc["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                symbol = args.get("symbol", ticker_exchange)
                result = tool_executor(tc["name"], args)
                evt: dict = {"type": "tool", "tool": tc["name"], "symbol": symbol}
                if tc["name"] == "eodhd_news":
                    sites = _extract_news_sites(result)
                    if sites:
                        evt["sites"] = sites
                yield evt
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "content":      result,
                })
            _total_tool_calls += len(pending_tcs)

            # After initial 3 tool calls, inject reflection exactly once
            if _total_tool_calls >= 3 and not _reflection_injected:
                _reflection_injected = True
                messages.append({"role": "user", "content": _REFLECTION_PROMPT})
                yield {"type": "status", "text": "Reflecting on research…"}

            continue  # next round with tool results

        # No tool calls — the model is done
        break

    yield {"type": "status", "text": "\n\nParsing and saving report…"}
    try:
        report = parse_json_report(full_text)
        report.setdefault("ticker",   ticker_exchange.split(".")[0])
        report.setdefault("exchange", (ticker_exchange.split(".", 1) + ["US"])[1])
        report["_model"] = model
        yield {"type": "done", "report": report, "raw": full_text}
    except Exception as exc:
        yield {"type": "error", "text": f"JSON parse failed: {exc}\n\nRaw output:\n{full_text[:800]}"}
