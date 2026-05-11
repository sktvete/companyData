from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.io_utils import read_jsonl, write_csv
from equity_sorter.config import load_settings


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
]


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
    company_id_by_cik = {row.get("cik"): row["company_id"] for row in companies if row.get("cik")}
    securities = read_jsonl(settings.data_dir / "silver" / "securities" / "exchange=US" / f"date={args.bronze_date}" / "rows.jsonl")
    security_by_company = {row["company_id"]: row["security_id"] for row in securities}

    cf_index = {(row["security_id"], row["fiscal_period_end_date"]): row for row in companyfacts_rows if row.get("fiscal_period_end_date")}
    fsd_index = {}
    for row in fsd_rows:
        company_id = company_id_by_cik.get(row.get("cik"))
        security_id = security_by_company.get(company_id) if company_id else None
        period = row.get("fiscal_period_end_date")
        if security_id and period:
            fsd_index[(security_id, period)] = row

    reconciliation_rows = []
    for key in sorted(set(cf_index) | set(fsd_index)):
        cf_row = cf_index.get(key)
        fsd_row = fsd_index.get(key)
        security_id, period = key
        for field in FIELDS:
            cf_has = cf_row is not None and cf_row.get(field) is not None
            fsd_has = fsd_row is not None and fsd_row.get(field) is not None
            if cf_has and fsd_has:
                status = "both_present"
            elif cf_has and not fsd_has:
                status = "companyfacts_only"
            elif fsd_has and not cf_has:
                status = "fsd_only"
            else:
                status = "both_missing"
            reconciliation_rows.append({
                "security_id": security_id,
                "fiscal_period_end_date": period,
                "field_name": field,
                "status": status,
            })

    summary: dict[tuple[str, str], int] = {}
    for row in reconciliation_rows:
        key = (row["field_name"], row["status"])
        summary[key] = summary.get(key, 0) + 1
    summary_rows = [{"field_name": field_name, "status": status, "count": count} for (field_name, status), count in sorted(summary.items())]

    output_root = settings.output_dir / "reconciliation" / "sec_sources" / args.bronze_date / f"{args.year}q{args.quarter}"
    write_csv(output_root / "field_reconciliation.csv", reconciliation_rows)
    write_csv(output_root / "field_reconciliation_summary.csv", summary_rows)
    print(output_root)


if __name__ == "__main__":
    main()
