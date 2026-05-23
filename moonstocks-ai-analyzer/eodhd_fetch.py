"""Fetch EODHD data via REST for the OpenAI analysis path (no MCP)."""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import httpx

EODHD_BASE = "https://eodhistoricaldata.com/api"


def _api_key() -> str:
    key = (os.environ.get("EODHD_API_KEY") or "").strip()
    if not key:
        raise ValueError("EODHD_API_KEY is required")
    return key


def _get_json(client: httpx.Client, path: str, params: dict | None = None) -> Any:
    p = {"api_token": _api_key(), "fmt": "json", **(params or {})}
    url = f"{EODHD_BASE}/{path.lstrip('/')}"
    resp = client.get(url, params=p, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _trim_financials(fin: dict | None) -> dict | None:
    if not fin:
        return fin

    def _last_n(section: dict | None, n: int = 4) -> dict | None:
        if not section or not isinstance(section, dict):
            return section
        keys = sorted(section.keys(), reverse=True)[:n]
        return {k: section[k] for k in keys}

    out = {}
    for stmt in ("Income_Statement", "Balance_Sheet", "Cash_Flow"):
        block = fin.get(stmt) if isinstance(fin, dict) else None
        if not isinstance(block, dict):
            continue
        out[stmt] = {
            "yearly": _last_n(block.get("yearly"), 3),
            "quarterly": _last_n(block.get("quarterly"), 4),
        }
    return out or fin


def trim_fundamentals_payload(data: dict) -> dict:
    """Reduce token size while keeping fields needed for scoring."""
    if not isinstance(data, dict):
        return data
    keep = (
        "General",
        "Highlights",
        "Valuation",
        "SharesStats",
        "Technicals",
        "AnalystRatings",
        "Earnings",
        "Holders",
        "InsiderTransactions",
        "outstandingShares",
        "ESGScores",
    )
    trimmed = {k: data[k] for k in keep if k in data}
    if "Financials" in data:
        trimmed["Financials"] = _trim_financials(data.get("Financials"))
    return trimmed


def fetch_eodhd_bundle(symbol_exchange: str) -> dict[str, Any]:
    """symbol_exchange e.g. DECK.US"""
    today = date.today()
    year_ago = today - timedelta(days=365)
    with httpx.Client() as client:
        fundamentals = _get_json(client, f"fundamentals/{symbol_exchange}")
        prices = _get_json(
            client,
            f"eod/{symbol_exchange}",
            {
                "from": year_ago.isoformat(),
                "to": today.isoformat(),
                "period": "d",
            },
        )
        try:
            live = _get_json(client, f"real-time/{symbol_exchange}")
        except httpx.HTTPError:
            live = None
        try:
            trends = _get_json(
                client,
                "calendar/earnings",
                {"symbols": symbol_exchange},
            )
        except httpx.HTTPError:
            trends = None

    return {
        "fundamentals": trim_fundamentals_payload(fundamentals),
        "historical_prices_daily": prices[-260:] if isinstance(prices, list) else prices,
        "live_price": live,
        "earnings_trends": trends,
    }
