from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from equity_sorter.io_utils import write_csv, write_jsonl


COMPARE_FIELDS = [
    "revenue",
    "net_income",
    "operating_income",
    "cash_and_equivalents",
    "total_debt",
    "total_equity",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "shares_basic",
    "filing_date",
    "report_date",
]


def compare_sec_to_normalized(
    raw_rows: list[dict[str, Any]],
    normalized_rows: list[dict[str, Any]],
    output_root: Path,
    tolerance: float = 0.001,
) -> dict[str, Path]:
    raw_index = {(row["security_id"], row["fiscal_period"]): row for row in raw_rows}
    normalized_index = {(row["security_id"], row["fiscal_period"]): row for row in normalized_rows}
    all_keys = sorted(set(raw_index) | set(normalized_index))
    comparisons: list[dict[str, Any]] = []
    summary_counts: dict[str, int] = defaultdict(int)

    for key in all_keys:
        raw = raw_index.get(key)
        normalized = normalized_index.get(key)
        security_id, fiscal_period = key
        for field in COMPARE_FIELDS:
            raw_value = None if raw is None else raw.get(field)
            normalized_value = None if normalized is None else normalized.get(field)
            status = _compare_value(raw_value, normalized_value, tolerance)
            summary_counts[status] += 1
            comparisons.append(
                {
                    "security_id": security_id,
                    "fiscal_period": fiscal_period,
                    "field_name": field,
                    "raw_value": raw_value,
                    "normalized_value": normalized_value,
                    "status": status,
                }
            )

    summary_rows = [{"status": status, "count": count} for status, count in sorted(summary_counts.items())]
    csv_path = output_root / "source_comparison.csv"
    jsonl_path = output_root / "source_comparison.jsonl"
    summary_path = output_root / "source_comparison_summary.csv"
    write_csv(csv_path, comparisons)
    write_jsonl(jsonl_path, comparisons)
    write_csv(summary_path, summary_rows)
    return {"csv": csv_path, "jsonl": jsonl_path, "summary": summary_path}


def _compare_value(raw_value: Any, normalized_value: Any, tolerance: float) -> str:
    if raw_value is None and normalized_value is None:
        return "exact_match"
    if raw_value is None:
        return "missing_in_raw"
    if normalized_value is None:
        return "missing_in_normalized"
    if isinstance(raw_value, (int, float)) and isinstance(normalized_value, (int, float)):
        if raw_value == normalized_value:
            return "exact_match"
        baseline = abs(raw_value) if raw_value != 0 else 1.0
        if abs(raw_value - normalized_value) / baseline <= tolerance:
            return "close_match_within_tolerance"
        return "material_difference"
    if str(raw_value) == str(normalized_value):
        return "exact_match"
    return "material_difference"
