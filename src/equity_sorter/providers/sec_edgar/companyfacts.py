from __future__ import annotations

from collections import defaultdict
from typing import Any

from .client import SECRequest


SEC_CONCEPT_MAP = {
    "revenue": ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_assets": ["Assets"],
    "total_debt": ["LongTermDebtAndCapitalLeaseObligations", "LongTermDebt", "LongTermDebtCurrent"],
    "total_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic", "CommonStockSharesOutstanding"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}


def companyfacts_request(cik: str) -> SECRequest:
    return SECRequest(path=f"/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")


def extract_quarterly_facts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    facts = (payload.get("facts") or {}).get("us-gaap") or {}
    observations: dict[str, dict[str, Any]] = defaultdict(dict)
    for target_field, concept_names in SEC_CONCEPT_MAP.items():
        for concept_name in concept_names:
            concept = facts.get(concept_name)
            if not concept:
                continue
            units = concept.get("units") or {}
            for unit_name, entries in units.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    form = entry.get("form") or ""
                    if form not in {"10-Q", "10-K", "10-Q/A", "10-K/A"}:
                        continue
                    end = entry.get("end")
                    if not end:
                        continue
                    current = observations[end]
                    if target_field in current:
                        continue
                    current[target_field] = entry.get("val")
                    current["fiscal_period_end_date"] = end
                    current["fiscal_period"] = end
                    current["fiscal_year"] = entry.get("fy")
                    current["fiscal_quarter"] = _quarter_from_fp(entry.get("fp"))
                    current["filing_date"] = entry.get("filed")
                    current["report_date"] = end
                    current["accepted_timestamp"] = None
                    current["form"] = form
                    current["frame"] = entry.get("frame")
                    current["unit"] = unit_name
                    current["source_record_id"] = entry.get("accn")
                break
            if any(target_field in row for row in observations.values()):
                break
    rows = sorted(observations.values(), key=lambda row: row.get("fiscal_period_end_date") or "")
    for row in rows:
        if row.get("operating_cash_flow") is not None and row.get("capex") is not None and row.get("free_cash_flow") is None:
            row["free_cash_flow"] = row["operating_cash_flow"] - abs(row["capex"])
    return rows


def _quarter_from_fp(fp: str | None) -> int | None:
    if not fp or len(fp) < 2 or not fp.startswith("Q"):
        return None
    try:
        return int(fp[1])
    except ValueError:
        return None
