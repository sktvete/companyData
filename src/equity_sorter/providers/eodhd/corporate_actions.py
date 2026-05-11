from __future__ import annotations

from typing import Any

from .client import EODHDRequest


def splits_request(symbol: str, exchange_code: str) -> EODHDRequest:
    return EODHDRequest(endpoint=f"splits/{symbol}.{exchange_code}", params={})


def dividends_request(symbol: str, exchange_code: str) -> EODHDRequest:
    return EODHDRequest(endpoint=f"div/{symbol}.{exchange_code}", params={})


def parse_splits_payload(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        values = payload.get("splits")
        if isinstance(values, list):
            return values
        return list(payload.values()) if payload else []
    return []


def parse_dividends_payload(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        values = payload.get("dividends")
        if isinstance(values, list):
            return values
        return list(payload.values()) if payload else []
    return []
