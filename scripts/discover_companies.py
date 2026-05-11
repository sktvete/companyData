#!/usr/bin/env python3
"""
discover_companies.py
---------------------
Download the full US exchange symbol list from EODHD and build a curated
company universe for large-scale analysis.

Usage:
    python scripts/discover_companies.py [--limit 2000] [--min-price 5]

Output:
    outputs/company_universe.json  – sorted list of symbols + metadata
"""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from equity_sorter.config import load_settings
from equity_sorter.providers.eodhd.client import EODHDClient, EODHDRequest


def fetch_exchange_list(api_key: str, exchange: str = "US") -> list[dict]:
    """Download the raw symbol list for an exchange (1 API call)."""
    import requests
    r = requests.get(
        f"https://eodhd.com/api/exchange-symbol-list/{exchange}",
        params={"api_token": api_key, "fmt": "json"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


MAJOR_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "NYSE MKT"}


def build_universe(
    api_key: str,
    min_price: float = 5.0,   # kept for API compat, not used (no price in list)
    min_mcap_b: float = 0.5,  # kept for API compat
    limit: int = 3000,
    workers: int = 20,
    exchange: str = "US",
) -> list[dict]:
    """
    1. Download US exchange symbol list (1 API call).
    2. Filter to Common Stock on major exchanges (NYSE, NASDAQ, AMEX).
    3. Sort and deduplicate, take up to `limit`.
    Market-cap filtering happens later during full analysis (companies with
    insufficient data or tiny market cap are skipped by scale_analysis_1000.py).
    """
    print(f"📥  Downloading {exchange} symbol list…")
    raw = fetch_exchange_list(api_key, exchange)
    print(f"    Total symbols: {len(raw)}")

    # Filter: Common Stock, USD, major exchange only
    candidates = [
        s for s in raw
        if s.get("Type") == "Common Stock"
        and s.get("Currency") == "USD"
        and s.get("Exchange") in MAJOR_EXCHANGES
    ]
    print(f"    Major-exchange USD Common Stocks: {len(candidates)}")

    # Deduplicate by Code, sort alphabetically (no price to sort by)
    seen: set[str] = set()
    universe: list[dict] = []
    for s in candidates:
        code = s["Code"]
        if code not in seen:
            seen.add(code)
            universe.append({
                "symbol":    code,
                "name":      s.get("Name", code),
                "exchange":  s.get("Exchange", ""),
                "isin":      s.get("Isin"),
                "market_cap":   0,
                "market_cap_b": 0,
            })

    # Prefer well-known exchanges first (NASDAQ, NYSE, then AMEX)
    ORDER = {"NASDAQ": 0, "NYSE": 1, "AMEX": 2, "NYSE MKT": 3}
    universe.sort(key=lambda x: ORDER.get(x["exchange"], 9))
    universe = universe[:limit]

    print(f"\n✅  Universe built: {len(universe)} symbols from major exchanges")
    return universe


def main():
    parser = argparse.ArgumentParser(description="Build EODHD company universe")
    parser.add_argument("--limit",     type=int,   default=2000, help="Max companies (default 2000)")
    parser.add_argument("--min-price", type=float, default=5.0,  help="Min stock price filter")
    parser.add_argument("--min-mcap",  type=float, default=0.5,  help="Min market cap in $B")
    parser.add_argument("--workers",   type=int,   default=20,   help="Parallel threads")
    args = parser.parse_args()

    settings = load_settings()
    api_key  = settings.eodhd_api_key
    if not api_key:
        print("❌ EODHD_API_KEY not set in .env"); sys.exit(1)

    universe = build_universe(
        api_key    = api_key,
        min_price  = args.min_price,
        min_mcap_b = args.min_mcap,
        limit      = args.limit,
        workers    = args.workers,
    )

    out_dir = PROJECT_ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "company_universe.json"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total":        len(universe),
        "filters":      {"min_price": args.min_price, "min_mcap_b": args.min_mcap},
        "companies":    universe,
        "symbols":      [c["symbol"] for c in universe],
    }
    out_file.write_text(json.dumps(payload, indent=2))
    print(f"\n💾  Saved to {out_file}")

    # Also save a simple symbol list for easy use
    sym_file = out_dir / "symbol_list.txt"
    sym_file.write_text("\n".join(c["symbol"] for c in universe))
    print(f"📋  Symbol list: {sym_file}")


if __name__ == "__main__":
    main()
