from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import EODHDRequest


@dataclass(frozen=True)
class PriceBar:
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: float | None


def eod_prices_request(symbol: str, exchange_code: str, period: str = "d") -> EODHDRequest:
    return EODHDRequest(
        endpoint=f"eod/{symbol}.{exchange_code}",
        params={"period": period, "order": "a"},
    )


def parse_eod_prices_payload(payload: list[dict[str, Any]]) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for row in payload:
        bars.append(
            PriceBar(
                date=str(row.get("date") or row.get("Date") or ""),
                open=_to_float(row.get("open") or row.get("Open")),
                high=_to_float(row.get("high") or row.get("High")),
                low=_to_float(row.get("low") or row.get("Low")),
                close=_to_float(row.get("close") or row.get("Close")),
                adjusted_close=_to_float(row.get("adjusted_close") or row.get("Adjusted_close") or row.get("adjusted_close")),
                volume=_to_float(row.get("volume") or row.get("Volume")),
            )
        )
    return bars


def _to_float(value: Any) -> float | None:
    if value in (None, "", "NA"):
        return None
    return float(value)
