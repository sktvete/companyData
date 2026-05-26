#!/usr/bin/env python3
"""Fetch EODHD fundamentals for universe symbols missing analyst data (saves to cache)."""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web"))
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / ".env")

from eodhd_analyst import extract_analyst_ratings

CACHE_DIR = PROJECT_ROOT / "outputs" / "fundamentals_cache"


def _latest_universe() -> Path:
    files = list((PROJECT_ROOT / "outputs" / "scaled_analysis").glob("scaled_analysis_*.jsonl"))
    return max(files, key=lambda f: sum(1 for _ in open(f, encoding="utf-8")))


def _needs_analyst(sym: str, row: dict) -> bool:
    ar = row.get("analyst_ratings") or {}
    if ar.get("Rating") or ar.get("rating"):
        return False
    if ar.get("partial") or ar.get("estimate_analysts"):
        return False
    fp = CACHE_DIR / f"{sym}.json"
    if fp.is_file():
        try:
            if extract_analyst_ratings(json.loads(fp.read_text(encoding="utf-8"))):
                return False
        except Exception:
            pass
    return True


def _fetch_one(sym: str, api_key: str) -> tuple[str, bool, str]:
    url = f"https://eodhd.com/api/fundamentals/{sym}.US"
    try:
        r = requests.get(url, params={"api_token": api_key, "fmt": "json"}, timeout=25)
        if r.status_code != 200:
            return sym, False, f"http {r.status_code}"
        data = r.json()
        if not isinstance(data, dict) or not data.get("General"):
            return sym, False, "no General"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{sym}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        ar = extract_analyst_ratings(data)
        return sym, bool(ar), "ok" if ar else "no analyst in payload"
    except Exception as e:
        return sym, False, str(e)[:80]


def main() -> int:
    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    if not api_key:
        print("EODHD_API_KEY missing")
        return 1

    universe = _latest_universe()
    symbols: list[str] = []
    for line in open(universe, encoding="utf-8"):
        row = json.loads(line)
        sym = str(row.get("symbol") or "").upper()
        if sym and _needs_analyst(sym, row):
            symbols.append(sym)

    if not symbols:
        print("No symbols need analyst backfill.")
        return 0

    workers = min(12, max(2, int(os.getenv("ANALYST_BACKFILL_WORKERS", "8"))))
    print(f"Fetching fundamentals for {len(symbols)} symbols ({workers} workers)...")

    gained = 0
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch_one, s, api_key): s for s in symbols}
        for fut in as_completed(futs):
            sym, ok, msg = fut.result()
            done += 1
            if ok:
                gained += 1
            if done % 50 == 0 or done == len(symbols):
                print(f"  [{done}/{len(symbols)}] gained={gained} last={sym} {msg}")
            time.sleep(0.05)

    print(f"Done. New analyst coverage from fetch: {gained}/{len(symbols)}")
    print("Restart the web server to reload injected analyst rows from cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
