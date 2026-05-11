from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.public_downloads import download_commonstock_sec_sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--with-prices", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    summary = download_commonstock_sec_sample(settings, args.bronze_date, args.limit, download_prices=args.with_prices)
    print(f"Downloaded {summary.cik_count} SEC company sets for {args.limit} common-stock candidates")
    if summary.price_failures:
        print(f"Price failures: {len(summary.price_failures)}")


if __name__ == "__main__":
    main()
