from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_csv


FIELDS = [
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "cash_and_equivalents",
    "total_assets",
    "total_debt",
    "total_equity",
    "shares_basic",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "filing_date",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--quarter", type=int, required=True)
    args = parser.parse_args()

    settings = load_settings()
    rows = read_jsonl(settings.data_dir / "silver" / "sec_financial_statement_data_sets" / f"year={args.year}" / f"quarter={args.quarter}" / "rows.jsonl")
    counter = Counter()
    for row in rows:
        for field in FIELDS:
            if row.get(field) is not None:
                counter[field] += 1
    output_root = settings.output_dir / "coverage" / "sec_fsd" / f"year={args.year}" / f"quarter={args.quarter}"
    write_csv(output_root / "field_coverage.csv", [{"field_name": field, "non_null_rows": counter[field], "total_rows": len(rows)} for field in FIELDS])
    print(output_root)


if __name__ == "__main__":
    main()
