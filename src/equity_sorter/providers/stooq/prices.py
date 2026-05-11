from __future__ import annotations

import csv
from io import StringIO
from typing import Any


def parse_stooq_csv(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(StringIO(text))
    for row in reader:
        rows.append(
            {
                "date": row.get("Date"),
                "open": _to_float(row.get("Open")),
                "high": _to_float(row.get("High")),
                "low": _to_float(row.get("Low")),
                "close": _to_float(row.get("Close")),
                "volume": _to_float(row.get("Volume")),
            }
        )
    return rows


def _to_float(value: str | None) -> float | None:
    if value in (None, "", "-"):
        return None
    return float(value)
