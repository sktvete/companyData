from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
from io import TextIOWrapper
from zipfile import ZipFile
import requests


@dataclass(frozen=True)
class FinancialStatementDataSet:
    year: int
    quarter: int


DATASET_CONCEPT_MAP = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_assets": ["Assets"],
    "total_debt": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtCurrent"],
    "total_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic", "EntityCommonStockSharesOutstanding"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}

FLOW_FIELDS = {"revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "capex"}
STOCK_FIELDS = {"cash_and_equivalents", "total_assets", "total_debt", "total_equity", "shares_basic"}


def dataset_url(year: int, quarter: int) -> str:
    return f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{year}q{quarter}.zip"


def download_dataset(year: int, quarter: int, destination: Path, user_agent: str) -> Path:
    response = requests.get(dataset_url(year, quarter), headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=120)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def list_zip_members(zip_path: Path) -> list[str]:
    with ZipFile(zip_path, "r") as archive:
        return sorted(archive.namelist())


def read_tsv_member(zip_path: Path, member_name: str) -> list[dict[str, str]]:
    with ZipFile(zip_path, "r") as archive:
        with archive.open(member_name, "r") as handle:
            reader = csv.DictReader(TextIOWrapper(handle, encoding="utf-8"), delimiter="\t")
            return [dict(row) for row in reader]


def normalize_dataset_quarter(zip_path: Path) -> list[dict[str, object]]:
    submissions = read_tsv_member(zip_path, "sub.txt")
    nums = read_tsv_member(zip_path, "num.txt")
    sub_index = {row["adsh"]: row for row in submissions if row.get("adsh")}
    concept_lookup = {concept: field for field, concepts in DATASET_CONCEPT_MAP.items() for concept in concepts}
    grouped: dict[str, dict[str, object]] = {}

    for num in nums:
        adsh = num.get("adsh")
        tag = num.get("tag")
        if not adsh or not tag or adsh not in sub_index:
            continue
        if num.get("segments"):
            continue
        field_name = concept_lookup.get(tag)
        if not field_name:
            continue
        qtrs = _to_int(num.get("qtrs"))
        if field_name in FLOW_FIELDS and qtrs not in {1, 4}:
            continue
        if field_name in STOCK_FIELDS and qtrs not in {0, 1, 4}:
            continue
        row = grouped.setdefault(adsh, _base_submission_row(sub_index[adsh]))
        current_value = row.get(field_name)
        candidate_value = _to_float(num.get("value"))
        if candidate_value is None:
            continue
        if current_value is None:
            row[field_name] = candidate_value
            continue
        if field_name in FLOW_FIELDS:
            if qtrs == 4:
                row[field_name] = candidate_value
        else:
            row[field_name] = candidate_value

    rows = [row for row in grouped.values()]
    for row in rows:
        ocf = row.get("operating_cash_flow")
        capex = row.get("capex")
        if row.get("free_cash_flow") is None and isinstance(ocf, float) and isinstance(capex, float):
            row["free_cash_flow"] = ocf - abs(capex)
    rows.sort(key=lambda row: (str(row.get("cik") or ""), str(row.get("fiscal_period_end_date") or "")))
    return rows


def _base_submission_row(submission: dict[str, str]) -> dict[str, object]:
    period = submission.get("period")
    return {
        "adsh": submission.get("adsh"),
        "cik": str(submission.get("cik") or "").zfill(10),
        "name": submission.get("name"),
        "form": submission.get("form"),
        "fiscal_period_end_date": period,
        "fiscal_period": period,
        "fiscal_year": _to_int(submission.get("fy")),
        "fiscal_quarter": _quarter_from_fp(submission.get("fp")),
        "report_date": period,
        "filing_date": submission.get("filed"),
        "accepted_timestamp": submission.get("accepted"),
        "revenue": None,
        "gross_profit": None,
        "operating_income": None,
        "net_income": None,
        "cash_and_equivalents": None,
        "total_assets": None,
        "total_debt": None,
        "total_equity": None,
        "shares_basic": None,
        "operating_cash_flow": None,
        "capex": None,
        "free_cash_flow": None,
    }


def _to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _quarter_from_fp(fp: str | None) -> int | None:
    if not fp:
        return None
    if fp.startswith("Q") and len(fp) >= 2 and fp[1].isdigit():
        return int(fp[1])
    return None
