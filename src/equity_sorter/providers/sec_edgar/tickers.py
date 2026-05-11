from __future__ import annotations

from typing import Any

from .client import SECRequest, SEC_WWW_BASE


def company_tickers_request() -> SECRequest:
    return SECRequest(path="/files/company_tickers.json", base_url=SEC_WWW_BASE)


def parse_company_tickers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker")
        cik = row.get("cik_str")
        title = row.get("title")
        if ticker and cik:
            rows.append(
                {
                    "ticker": str(ticker).upper(),
                    "cik": str(cik).zfill(10),
                    "name": title,
                }
            )
    return rows
