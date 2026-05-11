from __future__ import annotations

from typing import Any


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


def merge_companyfacts_with_fsd(
    companyfacts_rows: list[dict[str, Any]],
    fsd_rows: list[dict[str, Any]],
    company_id_by_cik: dict[str, str],
    security_id_by_company: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched_rows = [dict(row) for row in companyfacts_rows]
    index = {(row["security_id"], row.get("fiscal_period_end_date")): row for row in enriched_rows}
    enrichment_events: list[dict[str, Any]] = []

    for fsd_row in fsd_rows:
        cik = fsd_row.get("cik")
        company_id = company_id_by_cik.get(cik)
        security_id = security_id_by_company.get(company_id) if company_id else None
        fiscal_period_end = fsd_row.get("fiscal_period_end_date")
        if not security_id or not fiscal_period_end:
            continue
        key = (security_id, fiscal_period_end)
        target = index.get(key)
        if target is None:
            appended = _build_fsd_appended_row(fsd_row, company_id, security_id)
            enriched_rows.append(appended)
            index[key] = appended
            enrichment_events.append(
                {
                    "security_id": security_id,
                    "fiscal_period_end_date": fiscal_period_end,
                    "field_name": "row",
                    "source": "sec_fsd",
                    "status": "appended_from_fsd",
                }
            )
            continue
        for field in FIELDS:
            if target.get(field) is None and fsd_row.get(field) is not None:
                target[field] = fsd_row[field]
                enrichment_events.append(
                    {
                        "security_id": security_id,
                        "fiscal_period_end_date": fiscal_period_end,
                        "field_name": field,
                        "source": "sec_fsd",
                        "status": "filled_from_fsd",
                    }
                )

    enriched_rows.sort(key=lambda row: (row["security_id"], row.get("fiscal_period_end_date") or ""))
    return enriched_rows, enrichment_events


def _build_fsd_appended_row(fsd_row: dict[str, Any], company_id: str, security_id: str) -> dict[str, Any]:
    row = {
        "security_id": security_id,
        "company_id": company_id,
        "fiscal_period": fsd_row.get("fiscal_period"),
        "fiscal_period_end_date": fsd_row.get("fiscal_period_end_date"),
        "fiscal_year": fsd_row.get("fiscal_year"),
        "fiscal_quarter": fsd_row.get("fiscal_quarter"),
        "report_date": fsd_row.get("report_date"),
        "filing_date": fsd_row.get("filing_date"),
        "accepted_timestamp": fsd_row.get("accepted_timestamp"),
        "currency": "USD",
        "accounting_standard": "us_gaap",
        "restatement_type": None,
        "provider": "sec_fsd",
        "ebit": fsd_row.get("operating_income"),
        "ebitda": None,
        "eps_basic": None,
    }
    for field in FIELDS:
        row[field] = fsd_row.get(field)
    return row
