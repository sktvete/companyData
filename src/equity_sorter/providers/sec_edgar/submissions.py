from __future__ import annotations

from typing import Any

from .client import SECRequest


def submissions_request(cik: str) -> SECRequest:
    return SECRequest(path=f"/submissions/CIK{cik.zfill(10)}.json")


def extract_company_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "cik": str(payload.get("cik") or "").zfill(10),
        "name": payload.get("name"),
        "tickers": list(payload.get("tickers") or []),
        "exchanges": list(payload.get("exchanges") or []),
        "sic": payload.get("sic"),
        "sic_description": payload.get("sicDescription"),
    }
