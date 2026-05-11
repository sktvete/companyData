from __future__ import annotations

from typing import Any

from equity_sorter.canonical.ids import make_quality_event_id
from equity_sorter.canonical.schemas import DataQualityEvent
from equity_sorter.io_utils import utc_now_iso


def validate_prices(prices: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in prices:
        entity_id = f"{row['security_id']}:{row['date']}"
        key = (row["security_id"], row["date"])
        if key in seen:
            events.append(_event("prices_daily", entity_id, "duplicate_price_row", "warning", "Duplicate price row", provider))
        seen.add(key)
        open_ = row.get("open")
        high = row.get("high")
        low = row.get("low")
        close = row.get("close")
        if any(value is not None and value < 0 for value in [open_, high, low, close]):
            events.append(_event("prices_daily", entity_id, "negative_ohlc", "blocking", "Negative OHLC value", provider))
        if high is not None and low is not None and high < low:
            events.append(_event("prices_daily", entity_id, "invalid_ohlc_range", "blocking", "High below low", provider))
    return events


def validate_fundamentals(fundamentals: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in fundamentals:
        entity_id = f"{row['security_id']}:{row['fiscal_period']}"
        key = (row["security_id"], row["fiscal_period"])
        if key in seen:
            events.append(_event("fundamentals_quarterly", entity_id, "duplicate_fiscal_period", "warning", "Duplicate fiscal period", provider))
        seen.add(key)
        if row.get("shares_basic") is not None and row["shares_basic"] < 0:
            events.append(_event("fundamentals_quarterly", entity_id, "negative_shares", "blocking", "Negative shares outstanding", provider))
        if not row.get("filing_date") and not row.get("report_date"):
            events.append(_event("fundamentals_quarterly", entity_id, "missing_timing", "info", "Missing filing/report timing", provider))
    return events


def validate_listings(listings: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in listings:
        entity_id = row["listing_id"]
        key = (row["exchange_code"], row["ticker"])
        if key in seen:
            events.append(_event("listings", entity_id, "duplicate_exchange_ticker", "warning", "Duplicate exchange+ticker", provider))
        seen.add(key)
        if not row.get("currency"):
            events.append(_event("listings", entity_id, "missing_currency", "info", "Missing listing currency", provider))
    return events


def _event(table_name: str, entity_id: str, rule_name: str, severity: str, message: str, provider: str) -> dict[str, Any]:
    event = DataQualityEvent(
        event_id=make_quality_event_id(table_name, entity_id, rule_name, message),
        table_name=table_name,
        entity_id=entity_id,
        rule_name=rule_name,
        severity=severity,
        message=message,
        provider=provider,
        event_timestamp=utc_now_iso(),
    )
    return event.to_dict()
