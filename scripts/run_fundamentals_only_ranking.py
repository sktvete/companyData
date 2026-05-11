from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.pipeline import build_fundamentals_only_us_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--snapshot-name", default="fundamentals_only_us_v1")
    parser.add_argument("--exchange", action="append", dest="exchanges")
    parser.add_argument("--fundamentals-table", default="fundamentals_quarterly")
    parser.add_argument("--source-date", default=None)
    args = parser.parse_args()

    settings = load_settings()
    outputs = build_fundamentals_only_us_snapshot(
        settings,
        args.as_of_date,
        snapshot_name=args.snapshot_name,
        exchange_codes=args.exchanges or ["US"],
        fundamentals_table_name=args.fundamentals_table,
        source_date=args.source_date,
    )
    print(outputs["jsonl"])


if __name__ == "__main__":
    main()
