from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl
from equity_sorter.pipeline import ingest_exchange_symbols, ingest_security_payloads, normalize_exchange_symbols, normalize_security_payloads


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--bronze-date", default=date.today().isoformat())
    parser.add_argument("--max-count", type=int, default=None)
    parser.add_argument("--country", default=None)
    args = parser.parse_args()

    settings = load_settings()
    bronze_date = args.bronze_date
    ingest_exchange_symbols(settings, args.exchange, bronze_date)
    normalize_exchange_symbols(settings, args.exchange, bronze_date)
    listings_path = settings.data_dir / "silver" / "listings" / f"exchange={args.exchange}" / f"date={bronze_date}" / "rows.jsonl"
    listings = read_jsonl(listings_path)
    eligible = [row for row in listings if row.get("ticker") and row.get("currency")]
    if args.country:
        eligible = [row for row in eligible if row.get("country") in {args.country, args.country.upper(), args.country.title()}]
    max_count = args.max_count or settings.pilot_us_limit
    ingest_security_payloads(settings, eligible, bronze_date, max_count=max_count)
    normalize_security_payloads(settings, args.exchange, bronze_date)


if __name__ == "__main__":
    main()
