from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.fundamentals_enrichment import merge_companyfacts_with_fsd
from equity_sorter.io_utils import read_jsonl, write_csv, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--quarter", type=int, required=True)
    args = parser.parse_args()

    settings = load_settings()
    companyfacts_rows = read_jsonl(settings.data_dir / "silver" / "fundamentals_quarterly" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    fsd_rows = read_jsonl(settings.data_dir / "silver" / "sec_financial_statement_data_sets" / f"year={args.year}" / f"quarter={args.quarter}" / "rows.jsonl")
    companies = read_jsonl(settings.data_dir / "silver" / "companies" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    securities = read_jsonl(settings.data_dir / "silver" / "securities" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    company_id_by_cik = {row.get("cik"): row["company_id"] for row in companies if row.get("cik")}
    security_id_by_company = {row["company_id"]: row["security_id"] for row in securities}
    enriched_rows, events = merge_companyfacts_with_fsd(companyfacts_rows, fsd_rows, company_id_by_cik, security_id_by_company)

    output_root = settings.data_dir / "silver" / "fundamentals_quarterly_enriched" / "exchange=US" / f"date={args.bronze_date}"
    write_jsonl(output_root / "rows.jsonl", enriched_rows)
    write_csv(output_root / "rows.csv", enriched_rows)
    write_jsonl(output_root / "enrichment_events.jsonl", events)
    print(output_root / "rows.jsonl")
    print(f"events={len(events)}")


if __name__ == "__main__":
    main()
