from __future__ import annotations

from typing import Any

from .client import EODHDRequest


def fundamentals_request(symbol: str, exchange_code: str) -> EODHDRequest:
    return EODHDRequest(endpoint=f"fundamentals/{symbol}.{exchange_code}", params={})


def extract_general(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("General") or {})


def extract_highlights(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("Highlights") or {})


def extract_quarterly_financials(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    financials = payload.get("Financials") or {}
    return {
        "income_statement": list((((financials.get("Income_Statement") or {}).get("quarterly") or {}).values())),
        "balance_sheet": list((((financials.get("Balance_Sheet") or {}).get("quarterly") or {}).values())),
        "cash_flow": list((((financials.get("Cash_Flow") or {}).get("quarterly") or {}).values())),
    }


def extract_annual_financials(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    financials = payload.get("Financials") or {}
    return {
        "income_statement": list((((financials.get("Income_Statement") or {}).get("yearly") or {}).values())),
        "balance_sheet": list((((financials.get("Balance_Sheet") or {}).get("yearly") or {}).values())),
        "cash_flow": list((((financials.get("Cash_Flow") or {}).get("yearly") or {}).values())),
    }
