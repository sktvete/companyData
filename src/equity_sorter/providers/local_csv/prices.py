from __future__ import annotations

import csv
from io import StringIO
from typing import Any


DEFAULT_PRICE_COLUMN_MAP = {
    "ticker": ["ticker", "symbol", "code"],
    "date": ["date", "trading_date"],
    "open": ["open"],
    "high": ["high"],
    "low": ["low"],
    "close": ["close"],
    "adjusted_close": ["adjusted_close", "adj_close"],
    "volume": ["volume"],
    "currency": ["currency"],
    "adjustment_method": ["adjustment_method", "provider_adjustment_method"],
    "source_record_id": ["source_record_id"],
}


def parse_local_price_csv(text: str, column_map: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    column_map = column_map or DEFAULT_PRICE_COLUMN_MAP
    reader = csv.DictReader(StringIO(text))
    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row = {(_normalize_key(key)): value for key, value in raw_row.items()}
        ticker = _mapped_value(row, column_map, "ticker")
        date_value = _mapped_value(row, column_map, "date")
        if not ticker or not date_value:
            continue
        rows.append(
            {
                "ticker": str(ticker).upper(),
                "date": str(date_value),
                "open": _to_float(_mapped_value(row, column_map, "open")),
                "high": _to_float(_mapped_value(row, column_map, "high")),
                "low": _to_float(_mapped_value(row, column_map, "low")),
                "close": _to_float(_mapped_value(row, column_map, "close")),
                "adjusted_close": _to_float(_mapped_value(row, column_map, "adjusted_close")),
                "volume": _to_float(_mapped_value(row, column_map, "volume")),
                "currency": _mapped_value(row, column_map, "currency"),
                "adjustment_method": _mapped_value(row, column_map, "adjustment_method"),
                "source_record_id": _mapped_value(row, column_map, "source_record_id"),
            }
        )
    return rows


def _normalize_key(value: str | None) -> str:
    return str(value or "").strip().lower()


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _mapped_value(row: dict[str, Any], column_map: dict[str, list[str]], logical_name: str) -> Any:
    return _first_present(row, column_map.get(logical_name, [logical_name]))


def _to_float(value: Any) -> float | None:
    if value in (None, "", "NA", "N/A"):
        return None
    return float(value)
