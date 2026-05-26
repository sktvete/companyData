#!/usr/bin/env python3
"""Discover largest Scandinavian listings via EODHD screener (OL, ST, CO, HE)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / ".env")

from equity_sorter.config import load_settings

# EODHD screener exchange codes
NORDIC_EXCHANGES = ("OL", "ST", "CO", "HE")


def fetch_screener_page(
    api_key: str,
    exchange: str,
    limit: int,
    min_mcap: float,
    upper_mcap: float | None = None,
) -> list[dict]:
    filters: list = [["exchange", "=", exchange], ["market_capitalization", ">", int(min_mcap)]]
    if upper_mcap is not None and upper_mcap > 0:
        filters.append(["market_capitalization", "<", int(upper_mcap)])
    r = requests.get(
        "https://eodhd.com/api/screener",
        params={
            "api_token": api_key,
            "sort": "market_capitalization.desc",
            "filters": json.dumps(filters, separators=(",", ":")),
            "limit": limit,
            "offset": 0,
        },
        timeout=90,
    )
    r.raise_for_status()
    payload = r.json()
    return payload.get("data", []) if isinstance(payload, dict) else []


def fetch_exchange_top(
    api_key: str,
    exchange: str,
    per_exchange: int,
    min_mcap: float = 5_000_000,
) -> list[dict]:
    """Largest common stocks on one Nordic exchange."""
    rows: list[dict] = []
    upper: float | None = None
    while len(rows) < per_exchange:
        batch = fetch_screener_page(api_key, exchange, 100, min_mcap, upper_mcap=upper)
        if not batch:
            break
        last_mcap = None
        for s in batch:
            code = (s.get("code") or "").strip().upper()
            if not code:
                continue
            mcap = float(s.get("market_capitalization") or 0.0)
            if mcap <= 0:
                continue
            last_mcap = mcap if last_mcap is None or mcap < last_mcap else last_mcap
            rows.append({
                "symbol": code,
                "name": s.get("name", code),
                "exchange": exchange,
                "eodhd_exchange": exchange,
                "market_cap": mcap,
                "market_cap_b": round(mcap / 1e9, 3),
                "sector": s.get("sector"),
                "country": {"OL": "Norway", "ST": "Sweden", "CO": "Denmark", "HE": "Finland"}.get(exchange, ""),
            })
            if len(rows) >= per_exchange:
                break
        if last_mcap is None:
            break
        upper = max(last_mcap - 1.0, 1.0)
    return rows[:per_exchange]


def _existing_symbols() -> set[str]:
    out: set[str] = set()
    scaled = PROJECT_ROOT / "outputs" / "scaled_analysis"
    if scaled.is_dir():
        files = list(scaled.glob("scaled_analysis_*.jsonl"))
        if files:
            best = max(files, key=lambda f: sum(1 for _ in open(f, encoding="utf-8")))
            for line in open(best, encoding="utf-8"):
                try:
                    out.add(json.loads(line).get("symbol", "").upper())
                except Exception:
                    pass
    for name in ("extra_companies.jsonl", "nordic_companies.jsonl"):
        p = PROJECT_ROOT / "outputs" / name
        if p.is_file():
            for line in open(p, encoding="utf-8"):
                try:
                    out.add(json.loads(line).get("symbol", "").upper())
                except Exception:
                    pass
    return out


def build_nordic_universe(
    api_key: str,
    limit: int = 200,
    per_exchange: int = 120,
    min_mcap: float = 5_000_000,
    exclude_existing: bool = True,
) -> list[dict]:
    existing = _existing_symbols() if exclude_existing else set()
    pool: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for ex in NORDIC_EXCHANGES:
        print(f"  {ex}: fetching up to {per_exchange}…")
        batch = fetch_exchange_top(api_key, ex, per_exchange, min_mcap=min_mcap)
        print(f"       got {len(batch)}")
        for row in batch:
            key = (row["symbol"], row["exchange"])
            if key in seen:
                continue
            seen.add(key)
            pool.append(row)

    pool.sort(key=lambda x: x["market_cap"], reverse=True)
    universe: list[dict] = []
    skipped = 0
    for row in pool:
        if exclude_existing and row["symbol"] in existing:
            skipped += 1
            continue
        universe.append(row)
        if len(universe) >= limit:
            break

    print(f"\nOK Nordic universe: {len(universe)} new symbols ({skipped} skipped, already in app)")
    if universe:
        top = universe[0]
        print(f"    Largest: {top['symbol']} ({top['exchange']}) ${top['market_cap_b']:.1f}B")
    return universe


def main() -> int:
    p = argparse.ArgumentParser(description="Discover top Scandinavian stocks (EODHD)")
    p.add_argument("--limit", type=int, default=200, help="How many new symbols to keep (default 200)")
    p.add_argument("--per-exchange", type=int, default=120, help="Candidates per exchange before global sort")
    p.add_argument("--min-mcap", type=float, default=5e6, help="Min market cap USD (default 5M)")
    p.add_argument("--include-existing", action="store_true", help="Do not skip symbols already in universe")
    args = p.parse_args()

    settings = load_settings()
    api_key = settings.eodhd_api_key
    if not api_key:
        print("EODHD_API_KEY not set"); return 1

    print(f"Nordic discovery (OL, ST, CO, HE) - top {args.limit} new listings")
    universe = build_nordic_universe(
        api_key,
        limit=args.limit,
        per_exchange=args.per_exchange,
        min_mcap=args.min_mcap,
        exclude_existing=not args.include_existing,
    )

    out_dir = PROJECT_ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    sym_file = out_dir / "symbol_list_nordic.txt"
    json_file = out_dir / "company_universe_nordic.json"

    sym_lines = [f"{r['symbol']},{r['exchange']}" for r in universe]
    sym_file.write_text("\n".join(sym_lines) + ("\n" if sym_lines else ""), encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": "scandinavia",
        "exchanges": list(NORDIC_EXCHANGES),
        "count": len(universe),
        "companies": universe,
    }
    json_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {sym_file.name}  ({len(sym_lines)} lines: SYMBOL,EXCHANGE)")
    print(f"Wrote {json_file.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
