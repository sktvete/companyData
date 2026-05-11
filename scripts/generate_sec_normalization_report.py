from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_json, read_jsonl
from equity_sorter.providers.sec_edgar.companyfacts import extract_quarterly_facts
from equity_sorter.source_comparison import compare_sec_to_normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", required=True)
    args = parser.parse_args()

    settings = load_settings()
    silver_rows = read_jsonl(settings.data_dir / "silver" / "fundamentals_quarterly" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    raw_rows = []
    companies = read_jsonl(settings.data_dir / "silver" / "companies" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    securities = read_jsonl(settings.data_dir / "silver" / "securities" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    company_by_cik = {row.get("cik"): row["company_id"] for row in companies if row.get("cik")}
    security_by_company = {row["company_id"]: row["security_id"] for row in securities}
    sec_root = settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=companyfacts" / f"date={args.bronze_date}"
    for path in sorted(sec_root.glob("*.json")):
        cik = path.stem
        company_id = company_by_cik.get(cik)
        security_id = security_by_company.get(company_id) if company_id else None
        if not security_id:
            continue
        for row in extract_quarterly_facts(read_json(path)):
            raw_rows.append(
                {
                    "security_id": security_id,
                    "fiscal_period": row.get("fiscal_period"),
                    "revenue": row.get("revenue"),
                    "net_income": row.get("net_income"),
                    "operating_income": row.get("operating_income"),
                    "cash_and_equivalents": row.get("cash_and_equivalents"),
                    "total_debt": row.get("total_debt"),
                    "total_equity": row.get("total_equity"),
                    "operating_cash_flow": row.get("operating_cash_flow"),
                    "capex": row.get("capex"),
                    "free_cash_flow": row.get("free_cash_flow"),
                    "shares_basic": row.get("shares_basic"),
                    "filing_date": row.get("filing_date"),
                    "report_date": row.get("report_date"),
                }
            )
    output_root = settings.output_dir / "comparison" / "US" / args.bronze_date
    paths = compare_sec_to_normalized(raw_rows, silver_rows, output_root)
    print(paths["csv"])


if __name__ == "__main__":
    main()
