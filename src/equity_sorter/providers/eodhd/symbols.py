from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import EODHDRequest


@dataclass(frozen=True)
class SymbolRecord:
    code: str
    exchange: str
    name: str | None
    country: str | None
    currency: str | None
    type: str | None
    isin: str | None
    delisted: bool


def list_exchange_symbols_request(exchange_code: str, delisted: int = 1) -> EODHDRequest:
    return EODHDRequest(
        endpoint=f"exchange-symbol-list/{exchange_code}",
        params={"delisted": delisted},
    )


def parse_symbol_payload(payload: list[dict[str, Any]], exchange_code: str) -> list[SymbolRecord]:
    rows: list[SymbolRecord] = []
    for row in payload:
        rows.append(
            SymbolRecord(
                code=str(row.get("Code") or "").strip(),
                exchange=exchange_code,
                name=row.get("Name"),
                country=row.get("Country"),
                currency=row.get("Currency"),
                type=row.get("Type"),
                isin=row.get("ISIN"),
                delisted=bool(row.get("Delisted")),
            )
        )
    return rows
