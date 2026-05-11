from __future__ import annotations

import csv
from io import StringIO


def parse_nasdaq_trader_symbols(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(StringIO(text), delimiter="|")
    for row in reader:
        symbol = row.get("Symbol") or row.get("NASDAQ Symbol")
        if not symbol or symbol.startswith("File Creation Time"):
            continue
        rows.append(
            {
                "ticker": symbol,
                "name": row.get("Security Name") or row.get("Company Name") or symbol,
                "exchange": row.get("Exchange") or row.get("Listing Exchange") or "US",
                "etf": _to_bool(row.get("ETF")),
                "test_issue": _to_bool(row.get("Test Issue")),
                "lot_size": row.get("Round Lot Size"),
            }
        )
    return rows


def _to_bool(value: str | None) -> bool:
    return str(value or "").strip().upper() in {"Y", "YES", "TRUE"}
