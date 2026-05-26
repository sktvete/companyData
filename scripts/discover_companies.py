#!/usr/bin/env python3
"""
discover_companies.py
---------------------
Download the full US exchange symbol list from EODHD and build a curated
company universe for large-scale analysis.

Usage:
    python scripts/discover_companies.py [--limit 2000] [--min-price 5]
    python scripts/discover_companies.py --sector Energy --limit 500
    python scripts/discover_companies.py --sector "Consumer Cyclical" --sector-op match --limit 300

Then analyze that list:
    python scripts/scale_analysis_1000.py --target 500 \\
        --symbols-file outputs/symbol_list_sector_energy.txt

Output:
    outputs/company_universe.json (default) or
    outputs/company_universe_sector_<slug>.json + symbol_list_sector_<slug>.txt
"""
from __future__ import annotations

import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / ".env")

from equity_sorter.config import load_settings
import requests


def fetch_exchange_list(api_key: str, exchange: str = "US") -> list[dict]:
    """Download raw exchange symbol list (used as a major-exchange whitelist)."""
    r = requests.get(
        f"https://eodhd.com/api/exchange-symbol-list/{exchange}",
        params={"api_token": api_key, "fmt": "json"},
        timeout=90,
    )
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def fetch_screener_page(
    api_key: str,
    exchange: str,
    limit: int,
    min_mcap_b: float,
    min_price: float,
    upper_mcap: float | None = None,
    sector: str | None = None,
    sector_op: str = "=",
    sort: str = "market_capitalization.desc",
) -> list[dict]:
    """Fetch one screener page (market-cap sorted)."""
    filters = [
        ["exchange", "=", exchange],
        ["market_capitalization", ">", int(min_mcap_b * 1e9)],
    ]
    if sector and str(sector).strip():
        op = sector_op if sector_op in ("=", "match") else "="
        filters.append(["sector", op, str(sector).strip()])
    if min_price > 0:
        filters.append(["adjusted_close", ">", float(min_price)])
    if upper_mcap is not None and upper_mcap > 0:
        filters.append(["market_capitalization", "<", int(upper_mcap)])
    r = requests.get(
        "https://eodhd.com/api/screener",
        params={
            "api_token": api_key,
            "sort": sort,
            "filters": json.dumps(filters, separators=(",", ":")),
            "limit": limit,
            "offset": 0,
        },
        timeout=90,
    )
    r.raise_for_status()
    payload = r.json()
    return payload.get("data", []) if isinstance(payload, dict) else []


MAJOR_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "NYSE MKT"}


def _sector_slug(sector: str | None) -> str:
    if not sector or not str(sector).strip():
        return ""
    s = str(sector).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "sector"


def build_universe(
    api_key: str,
    min_price: float = 5.0,
    min_mcap_b: float = 0.5,
    limit: int = 3000,
    workers: int = 20,  # kept for compat; screener pagination is sequential
    exchange: str = "US",
    sector: str | None = None,
    sector_op: str = "=",
) -> list[dict]:
    """
    Build largest-company universe directly from EODHD Screener API:
      - exchange = US
      - sorted by market capitalization descending
      - optional minimum market cap and price filters
      - paginated until `limit` is reached
    """
    print(f"📥  Building top-{limit} universe from Screener ({exchange})…")
    if sector and str(sector).strip():
        print(f"    Sector filter: {sector_op} {sector.strip()!r}")
    print(f"    Filters: market_cap > ${min_mcap_b:.2f}B, adjusted_close > ${min_price:.2f}")
    raw_list = fetch_exchange_list(api_key, exchange)
    major_codes = {
        (r.get("Code") or "").strip().upper()
        for r in raw_list
        if r.get("Type") == "Common Stock"
        and r.get("Currency") == "USD"
        and r.get("Exchange") in MAJOR_EXCHANGES
    }
    print(f"    Major-exchange common-stock whitelist: {len(major_codes)} symbols")

    seen: set[str] = set()
    universe: list[dict] = []
    page_size = 100
    upper_mcap: float | None = None
    while len(universe) < limit:
        rows = fetch_screener_page(
            api_key,
            exchange,
            page_size,
            min_mcap_b,
            min_price,
            upper_mcap=upper_mcap,
            sector=sector,
            sector_op=sector_op,
        )
        if not rows:
            break
        before = len(universe)
        _append_screener_rows(universe, seen, rows, major_codes, limit)
        if len(universe) == before:
            break
        last_mcap = min(
            float(s.get("market_capitalization") or 0.0)
            for s in rows
            if s.get("code")
        )
        if last_mcap is None:
            break
        # cursor pagination: fetch next block below this market-cap frontier.
        upper_mcap = max(last_mcap - 1.0, 1.0)
        if len(universe) % 500 == 0:
            print(f"    kept {len(universe)} (next upper_mcap={upper_mcap/1e9:.2f}B)")

    print(f"\n✅  Universe built: {len(universe)} symbols (largest first)")
    return universe


def _append_screener_rows(
    universe: list[dict],
    seen: set[str],
    rows: list[dict],
    major_codes: set[str],
    limit: int,
) -> None:
    for s in rows:
        if len(universe) >= limit:
            return
        code = (s.get("code") or "").strip().upper()
        if not code or code in seen:
            continue
        if code not in major_codes:
            continue
        if len(code) == 5 and code.endswith(("Y", "F")):
            continue
        seen.add(code)
        mcap = float(s.get("market_capitalization") or 0.0)
        universe.append({
            "symbol": code,
            "name": s.get("name", code),
            "exchange": s.get("exchange", "US"),
            "isin": s.get("isin"),
            "sector": s.get("sector"),
            "market_cap": mcap,
            "market_cap_b": round(mcap / 1e9, 3),
            "adjusted_close": float(s.get("adjusted_close") or 0.0),
        })


def build_small_mid_cap_slice(
    api_key: str,
    *,
    min_price: float = 1.5,
    min_mcap_b: float = 0.03,
    max_mcap_b: float = 3.0,
    limit: int = 2500,
    exchange: str = "US",
) -> list[dict]:
    """Smaller names ($30M–$3B) via ascending market-cap screener (complements large-cap pass)."""
    print(f"📥  Small/mid slice: ${min_mcap_b:.2f}B–${max_mcap_b:.1f}B, up to {limit} symbols…")
    raw_list = fetch_exchange_list(api_key, exchange)
    major_codes = {
        (r.get("Code") or "").strip().upper()
        for r in raw_list
        if r.get("Type") == "Common Stock"
        and r.get("Currency") == "USD"
        and r.get("Exchange") in MAJOR_EXCHANGES
    }
    seen: set[str] = set()
    universe: list[dict] = []
    page_size = 100
    floor_b = min_mcap_b
    max_mcap = int(max_mcap_b * 1e9)
    while len(universe) < limit:
        rows = fetch_screener_page(
            api_key,
            exchange,
            page_size,
            floor_b,
            min_price,
            upper_mcap=max_mcap,
            sort="market_capitalization.asc",
        )
        if not rows:
            break
        before = len(universe)
        _append_screener_rows(universe, seen, rows, major_codes, limit)
        if len(universe) == before:
            break
        hi_mcap = max(
            float(s.get("market_capitalization") or 0.0) for s in rows if s.get("code")
        )
        floor_b = max(min_mcap_b, hi_mcap / 1e9 + 1e-6)
        if hi_mcap >= max_mcap - 1:
            break
        if len(universe) % 500 == 0:
            print(f"    small/mid kept {len(universe)} (floor ${floor_b:.3f}B)")
    print(f"✅  Small/mid slice: {len(universe)} symbols")
    return universe


def merge_universe_slices(*slices: list[dict]) -> list[dict]:
    """Dedupe by symbol; keep row with larger market cap when duplicated."""
    by_sym: dict[str, dict] = {}
    for rows in slices:
        for row in rows:
            sym = (row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            prev = by_sym.get(sym)
            if prev is None or float(row.get("market_cap") or 0) >= float(prev.get("market_cap") or 0):
                by_sym[sym] = row
    merged = list(by_sym.values())
    merged.sort(key=lambda r: float(r.get("market_cap") or 0), reverse=True)
    return merged


def main():
    parser = argparse.ArgumentParser(description="Build EODHD company universe")
    parser.add_argument("--limit",     type=int,   default=7000, help="Max large-cap pass (default 7000)")
    parser.add_argument("--min-price", type=float, default=1.5,  help="Min stock price filter")
    parser.add_argument("--min-mcap",  type=float, default=0.03, help="Min market cap in $B (default $30M)")
    parser.add_argument(
        "--include-small-mid",
        type=int,
        default=2500,
        metavar="N",
        help="Also add N small/mid names ($30M–$3B) via ascending screener (0=off, default 2500)",
    )
    parser.add_argument("--workers",   type=int,   default=20,   help="Parallel threads")
    parser.add_argument(
        "--sector",
        type=str,
        default="",
        help='EODHD screener sector, e.g. Energy, Technology, "Financial Services". Empty = all sectors.',
    )
    parser.add_argument(
        "--sector-op",
        choices=("=", "match"),
        default="=",
        help='Sector filter operator: "=" exact (default) or "match" for multi-word sectors (EODHD).',
    )
    args = parser.parse_args()

    settings = load_settings()
    api_key  = settings.eodhd_api_key
    if not api_key:
        print("❌ EODHD_API_KEY not set in .env"); sys.exit(1)

    sec = (args.sector or "").strip() or None
    large = build_universe(
        api_key    = api_key,
        min_price  = args.min_price,
        min_mcap_b = args.min_mcap,
        limit      = args.limit,
        workers    = args.workers,
        sector     = sec,
        sector_op  = args.sector_op,
    )
    slices = [large]
    if args.include_small_mid > 0 and not sec:
        slices.append(
            build_small_mid_cap_slice(
                api_key,
                min_price=args.min_price,
                min_mcap_b=args.min_mcap,
                max_mcap_b=3.0,
                limit=args.include_small_mid,
            )
        )
    universe = merge_universe_slices(*slices)
    print(f"\n✅  Combined universe: {len(universe)} symbols (large + small/mid)")

    out_dir = PROJECT_ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    slug = _sector_slug(sec) if sec else ""
    if slug:
        out_file = out_dir / f"company_universe_sector_{slug}.json"
        sym_file = out_dir / f"symbol_list_sector_{slug}.txt"
    else:
        out_file = out_dir / "company_universe.json"
        sym_file = out_dir / "symbol_list.txt"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total":        len(universe),
        "filters":      {
            "min_price": args.min_price,
            "min_mcap_b": args.min_mcap,
            "sector": sec,
            "sector_op": args.sector_op if sec else None,
        },
        "companies":    universe,
        "symbols":      [c["symbol"] for c in universe],
    }
    out_file.write_text(json.dumps(payload, indent=2))
    print(f"\n💾  Saved to {out_file}")

    sym_file.write_text("\n".join(c["symbol"] for c in universe))
    print(f"📋  Symbol list: {sym_file}")
    if slug:
        print(f"\n▶  Next: python scripts/scale_analysis_1000.py --target {len(universe)} --symbols-file {sym_file}")


if __name__ == "__main__":
    main()
