from __future__ import annotations

from typing import Any

from equity_sorter.canonical.schemas import SourceCandidate
from equity_sorter.io_utils import stable_hash


def build_source_candidate(
    table_name: str,
    entity_id: str,
    field_name: str,
    value: Any,
    source: str,
    source_record_id: str | None,
    period: str | None,
    report_date: str | None,
    filing_date: str | None,
    ingestion_timestamp: str,
    confidence: float,
    pit_safe: bool,
    license_class: str,
    method: str,
    selected_flag: bool,
    selection_reason: str,
) -> dict[str, Any]:
    candidate_id = "src_" + stable_hash(f"{table_name}|{entity_id}|{field_name}|{source}|{period}|{value}")[:16]
    return SourceCandidate(
        candidate_id=candidate_id,
        table_name=table_name,
        entity_id=entity_id,
        field_name=field_name,
        value=None if value is None else str(value),
        source=source,
        source_record_id=source_record_id,
        period=period,
        report_date=report_date,
        filing_date=filing_date,
        ingestion_timestamp=ingestion_timestamp,
        confidence=confidence,
        pit_safe=pit_safe,
        license_class=license_class,
        method=method,
        selected_flag=selected_flag,
        selection_reason=selection_reason,
    ).to_dict()


def candidates_from_row(
    table_name: str,
    entity_id: str,
    row: dict[str, Any],
    fields: list[str],
    source: str,
    source_record_id: str | None,
    period: str | None,
    report_date: str | None,
    filing_date: str | None,
    ingestion_timestamp: str,
    confidence: float,
    pit_safe: bool,
    license_class: str,
    method: str,
    selection_reason: str,
) -> list[dict[str, Any]]:
    return [
        build_source_candidate(
            table_name=table_name,
            entity_id=entity_id,
            field_name=field_name,
            value=row.get(field_name),
            source=source,
            source_record_id=source_record_id,
            period=period,
            report_date=report_date,
            filing_date=filing_date,
            ingestion_timestamp=ingestion_timestamp,
            confidence=confidence,
            pit_safe=pit_safe,
            license_class=license_class,
            method=method,
            selected_flag=True,
            selection_reason=selection_reason,
        )
        for field_name in fields
    ]
