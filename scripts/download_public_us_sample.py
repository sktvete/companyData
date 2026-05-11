from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.public_downloads import download_public_us_sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", default=date.today().isoformat())
    parser.add_argument("--tickers", default=None, help="Comma-separated US tickers")
    args = parser.parse_args()

    settings = load_settings()
    tickers = settings.free_us_sample_tickers if args.tickers is None else tuple(value.strip().upper() for value in args.tickers.split(",") if value.strip())
    summary = download_public_us_sample(settings, args.bronze_date, list(tickers))
    print(f"Downloaded {summary.cik_count} SEC company sets for: {', '.join(summary.tickers)}")
    if summary.price_failures:
        print("Price download warnings:")
        for failure in summary.price_failures:
            print(f"- {failure}")


if __name__ == "__main__":
    main()
