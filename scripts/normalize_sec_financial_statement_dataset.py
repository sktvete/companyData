from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import write_csv, write_jsonl
from equity_sorter.providers.sec_edgar.financial_statement_data_sets import normalize_dataset_quarter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--quarter", type=int, required=True)
    args = parser.parse_args()

    settings = load_settings()
    zip_path = settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=financial_statement_data_sets" / f"year={args.year}" / f"quarter={args.quarter}" / f"{args.year}q{args.quarter}.zip"
    rows = normalize_dataset_quarter(zip_path)
    output_root = settings.data_dir / "silver" / "sec_financial_statement_data_sets" / f"year={args.year}" / f"quarter={args.quarter}"
    jsonl_path = output_root / "rows.jsonl"
    csv_path = output_root / "rows.csv"
    write_jsonl(jsonl_path, rows)
    write_csv(csv_path, rows)
    print(jsonl_path)
    print(f"rows={len(rows)}")


if __name__ == "__main__":
    main()
