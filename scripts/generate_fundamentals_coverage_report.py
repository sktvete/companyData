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
    parser.add_argument("--bronze-date", required=True)
    args = parser.parse_args()

    settings = load_settings()
    rows = read_jsonl(settings.data_dir / "silver" / "fundamentals_quarterly" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    field_counts = Counter()
    security_counts = Counter()
    for row in rows:
        security_counts[row["security_id"]] += 1
        for field in FIELDS:
            if row.get(field) is not None:
                field_counts[field] += 1
    coverage_rows = [{"field_name": field, "non_null_rows": field_counts[field], "total_rows": len(rows)} for field in FIELDS]
    security_rows = [{"security_id": security_id, "quarter_rows": count} for security_id, count in security_counts.items()]
    output_root = settings.output_dir / "coverage" / "US" / args.bronze_date
    write_csv(output_root / "field_coverage.csv", coverage_rows)
    write_csv(output_root / "security_quarter_counts.csv", security_rows)
    print(output_root)


if __name__ == "__main__":
    main()
