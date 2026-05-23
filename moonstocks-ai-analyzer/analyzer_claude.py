"""Claude Agent SDK analysis path (MCP + stock-analysis skill)."""
from __future__ import annotations

import json
import logging
import os

import httpx
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

from run_log import open_run_log, serialize_message, write_log

logger = logging.getLogger(__name__)


def _extract_text(message: object) -> str | None:
    if not isinstance(message, AssistantMessage):
        return None
    parts = [b.text for b in message.content if isinstance(b, TextBlock)]
    return "".join(parts) if parts else None


def _parse_json_report(text: str) -> dict:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        stripped = stripped[start : end + 1]
    return json.loads(stripped)


async def run_analysis_claude(ticker_exchange: str) -> None:
    ticker, exchange = ticker_exchange.split(".", 1)

    eodhd_key = os.environ["EODHD_API_KEY"]
    options = ClaudeAgentOptions(
        mcp_servers={
            "eodhd": {
                "type": "http",
                "url": f"https://mcpv2.eodhd.dev/v1/mcp?apikey={eodhd_key}",
            }
        },
        strict_mcp_config=True,
        skills=["stock-analysis"],
        setting_sources=["project"],
        permission_mode="bypassPermissions",
        max_buffer_size=32 * 1024 * 1024,
        system_prompt=(
            "You are a JSON-only API. Your final message must be exactly one "
            "JSON object: first character '{', last character '}'. No prose, "
            "no preamble, no acknowledgement, no markdown, no code fences."
        ),
    )

    prompt = (
        "Use the stock-analysis skill to analyze this input:\n"
        f'{{ "ticker": "{ticker}", "exchange": "{exchange}" }}\n\n'
        "OUTPUT CONTRACT (strict):\n"
        "- Your entire response MUST be a single JSON object.\n"
        "- The first character of your response MUST be '{'.\n"
        "- The last character of your response MUST be '}'.\n"
        "- Do NOT include any prose, preamble, explanation, acknowledgement, "
        "markdown, or code fences (no ```json, no ```).\n"
        "- Do NOT say things like 'Here is the analysis' or "
        "'I have sufficient data'.\n"
        "- If you cannot produce the JSON, still return a JSON object with an "
        "'error' field — never plain text."
    )

    log_fh = open_run_log(ticker_exchange, prompt)
    final_text = ""
    try:
        try:
            async for message in query(prompt=prompt, options=options):
                write_log(log_fh, serialize_message(message))
                text = _extract_text(message)
                if text:
                    final_text = text
            report = _parse_json_report(final_text)
        except Exception as exc:
            write_log(
                log_fh,
                {
                    "type": "error",
                    "stage": "query_or_parse",
                    "error": repr(exc),
                    "final_text_preview": final_text[:500],
                },
            )
            logger.exception(
                "Claude run or JSON parse failed for %s; raw output: %r",
                ticker_exchange,
                final_text[:500],
            )
            return

        base_url = os.environ["ANALYSIS_API_BASE_URL"].rstrip("/")
        url = f"{base_url}/api/analysis/{ticker_exchange}"
        payload = {"jsonReport": json.dumps(report)}

        headers: dict[str, str] = {}
        api_key = (os.environ.get("ANALYZER_API_KEY") or "").strip()
        if api_key:
            headers["X-API-Key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            write_log(
                log_fh,
                {"type": "post_result", "url": url, "status_code": resp.status_code, "provider": "anthropic"},
            )
        except Exception as exc:
            write_log(
                log_fh,
                {"type": "error", "stage": "post", "url": url, "error": repr(exc)},
            )
            logger.exception("Failed to POST analysis for %s to %s", ticker_exchange, url)
    finally:
        log_fh.close()
