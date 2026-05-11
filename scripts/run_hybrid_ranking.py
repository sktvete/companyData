from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.pipeline import build_hybrid_us_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--snapshot-name", default="hybrid_us_v1")
    parser.add_argument("--exchange", action="append", dest="exchanges")
    parser.add_argument("--source-date", default=None)
    args = parser.parse_args()

    settings = load_settings()
    outputs = build_hybrid_us_snapshot(settings, args.as_of_date, snapshot_name=args.snapshot_name, exchange_codes=args.exchanges or ["US"], source_date=args.source_date)
    print(outputs["jsonl"])


if __name__ == "__main__":
    main()
