from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.demo_data import build_demo_fixture
from equity_sorter.io_utils import write_json
from equity_sorter.pipeline import build_quality_report, normalize_exchange_symbols, normalize_security_payloads


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", default="2026-05-09")
    parser.add_argument("--exchange", action="append", dest="exchanges")
    args = parser.parse_args()

    settings = load_settings()
    fixture = build_demo_fixture()
    exchanges = args.exchanges or ["US", "OL"]

    for exchange_code in exchanges:
        symbol_path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=symbols" / f"exchange={exchange_code}" / f"date={args.bronze_date}" / "payload.json"
        write_json(symbol_path, {"request": {"fixture": True}, "payload": fixture["symbols"][exchange_code]})
        normalize_exchange_symbols(settings, exchange_code, args.bronze_date)
        for dataset_name, directory in [
            ("fundamentals", fixture["fundamentals"][exchange_code]),
            ("prices_daily", fixture["prices"][exchange_code]),
            ("corporate_actions_splits", fixture["splits"][exchange_code]),
            ("corporate_actions_dividends", fixture["dividends"][exchange_code]),
        ]:
            for symbol, payload in directory.items():
                path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / f"dataset={dataset_name}" / f"exchange={exchange_code}" / f"date={args.bronze_date}" / f"{symbol}.json"
                write_json(path, payload)
        normalize_security_payloads(settings, exchange_code, args.bronze_date)
        build_quality_report(settings, exchange_code, args.bronze_date)


if __name__ == "__main__":
    main()
