from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.free_pipeline import build_free_us_quality_report, normalize_free_us_reference, normalize_free_us_security_payloads
from equity_sorter.free_us_demo_data import build_free_us_demo_fixture
from equity_sorter.io_utils import write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", default="2026-05-09")
    args = parser.parse_args()

    settings = load_settings()
    fixture = build_free_us_demo_fixture()
    nasdaq_path = settings.data_dir / "bronze" / "provider=free_us" / "dataset=nasdaq_trader_symbols" / f"date={args.bronze_date}" / "symbols.txt"
    nasdaq_path.parent.mkdir(parents=True, exist_ok=True)
    nasdaq_path.write_text(fixture["nasdaq_trader_symbols"], encoding="utf-8")

    for cik, payload in fixture["sec_submissions"].items():
        write_json(settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=submissions" / f"date={args.bronze_date}" / f"{cik}.json", payload)
    for cik, payload in fixture["sec_companyfacts"].items():
        write_json(settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=companyfacts" / f"date={args.bronze_date}" / f"{cik}.json", payload)
    for symbol, csv_text in fixture["stooq_prices"].items():
        path = settings.data_dir / "bronze" / "provider=stooq" / "dataset=prices_daily" / f"date={args.bronze_date}" / f"{symbol}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(csv_text, encoding="utf-8")

    normalize_free_us_reference(settings, args.bronze_date)
    normalize_free_us_security_payloads(settings, args.bronze_date)
    build_free_us_quality_report(settings, args.bronze_date)


if __name__ == "__main__":
    main()
