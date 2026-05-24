"""OpenAI-backed stock analysis (uses pre-fetched EODHD REST data)."""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import httpx
from openai import OpenAI

from eodhd_fetch import fetch_eodhd_bundle
from run_log import open_run_log, write_log

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent / ".claude" / "skills" / "stock-analysis"


def _read_skill_file(name: str) -> str:
    path = SKILL_DIR / name
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :].lstrip()
    return text


def _build_system_prompt() -> str:
    schema = (SKILL_DIR / "output-schema.json").read_text(encoding="utf-8")
    parts = [
        _read_skill_file("SKILL.md"),
        _read_skill_file("hard-rules.md"),
        _read_skill_file("scoring-methodology.md"),
        "Output JSON must conform to this schema:\n" + schema,
        (
            "You are a JSON-only API. Your entire reply must be one JSON object: "
            "first character '{', last character '}'. No markdown or code fences."
        ),
    ]
    return "\n\n---\n\n".join(p for p in parts if p.strip())


def _parse_json_report(text: str) -> dict:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        stripped = stripped[start : end + 1]
    return json.loads(stripped)


def _post_report(ticker_exchange: str, report: dict, log_fh) -> None:
    base_url = os.environ["ANALYSIS_API_BASE_URL"].rstrip("/")
    url = f"{base_url}/api/analysis/{ticker_exchange}"
    payload = {"jsonReport": json.dumps(report)}
    headers: dict[str, str] = {}
    api_key = (os.environ.get("ANALYZER_API_KEY") or "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    write_log(log_fh, {"type": "post_result", "url": url, "status_code": resp.status_code, "provider": "openai"})


def run_analysis_openai(ticker_exchange: str) -> None:
    ticker, exchange = ticker_exchange.split(".", 1)
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when ANALYZER_LLM_PROVIDER=openai")

    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o").strip()
    symbol = f"{ticker}.{exchange}"

    prompt = (
        "Analyze this US equity using ONLY the attached EODHD data. "
        "Apply the stock-analysis skill, hard rules, and scoring methodology.\n\n"
        f'Input: {{ "ticker": "{ticker}", "exchange": "{exchange}" }}\n'
        f"analysis_date should be {date.today().isoformat()}.\n"
        f"time_horizon must be long_term_1y_plus.\n"
    )

    log_fh = open_run_log(ticker_exchange, prompt + f"\n[provider=openai model={model}]")
    final_text = ""
    try:
        try:
            bundle = fetch_eodhd_bundle(symbol)
            write_log(log_fh, {"type": "eodhd_fetch", "symbol": symbol, "keys": list(bundle.keys())})

            user_content = (
                prompt
                + "\n\nEODHD_DATA:\n"
                + json.dumps(bundle, default=str)
            )

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            final_text = response.choices[0].message.content or ""
            write_log(log_fh, {"type": "openai_response", "model": model, "chars": len(final_text)})
            report = _parse_json_report(final_text)
            report.setdefault("ticker", ticker)
            report.setdefault("exchange", exchange)
        except Exception as exc:
            write_log(
                log_fh,
                {
                    "type": "error",
                    "stage": "openai_query_or_parse",
                    "error": repr(exc),
                    "final_text_preview": final_text[:500],
                },
            )
            logger.exception("OpenAI run failed for %s", ticker_exchange)
            return

        _post_report(ticker_exchange, report, log_fh)
    except Exception as exc:
        write_log(log_fh, {"type": "error", "stage": "post", "error": repr(exc)})
        logger.exception("Failed to POST OpenAI analysis for %s", ticker_exchange)
    finally:
        log_fh.close()
