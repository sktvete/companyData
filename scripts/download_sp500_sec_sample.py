from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.public_downloads import download_public_us_sample_with_options
from equity_sorter.public_universe import download_sp500_constituents


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--skip-prices", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    constituents = download_sp500_constituents()
    tickers = [row["symbol"] for row in constituents[: args.limit]]
    summary = download_public_us_sample_with_options(settings, args.bronze_date, tickers, download_prices=not args.skip_prices)
    print(f"Downloaded {summary.cik_count} SEC company sets for first {args.limit} S&P 500 constituents")
    if summary.price_failures:
        print(f"Price failures: {len(summary.price_failures)}")


if __name__ == "__main__":
    main()
