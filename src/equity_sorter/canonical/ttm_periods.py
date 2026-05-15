"""Select how many EODHD flow periods sum to a true trailing twelve months."""
from __future__ import annotations

from datetime import datetime


def _parse_period_end(key: str) -> datetime | None:
    try:
        return datetime.strptime(str(key)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def ttm_flow_period_count(period_end_dates: list[str]) -> int:
    """Return N periods to sum for ~12 months of flows (4Q, 2H, or 1FY)."""
    if not period_end_dates:
        return 4
    keys = sorted({str(k)[:10] for k in period_end_dates if k}, reverse=True)
    if len(keys) <= 1:
        return max(1, len(keys))

    parsed = [_parse_period_end(k) for k in keys[:4]]
    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return min(4, len(keys))

    months = [p.month for p in parsed]

    # Semi-annual reporters (Nestlé, many Europeans): H1 Jun + H2 Dec only.
    if len(months) >= 2 and all(m in (6, 12) for m in months):
        return 2

    gaps: list[int] = []
    for i in range(min(3, len(parsed) - 1)):
        gaps.append((parsed[i] - parsed[i + 1]).days)

    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        if avg_gap >= 300:
            return 1
        if avg_gap >= 140:
            return 2

    return min(4, len(keys))


def select_ttm_period_keys(
    period_end_dates: list[str],
    trailing_years: int = 1,
) -> list[str]:
    """Most recent period-end keys covering ~12 months (or 24 when trailing_years=2)."""
    keys = sorted({str(k)[:10] for k in period_end_dates if k}, reverse=True)
    n1 = ttm_flow_period_count(keys)
    n = min(len(keys), n1 * max(1, int(trailing_years)))
    return keys[:n]


def ttm_cadence_label(n_periods: int) -> str:
    if n_periods <= 1:
        return "annual"
    if n_periods == 2:
        return "semi_annual"
    return "quarterly"


def ttm_display_label(cadence: str, trailing_years: int = 1) -> str:
    if trailing_years >= 2:
        if cadence == "quarterly":
            return "2Y avg"
        if cadence == "semi_annual":
            return "2Y avg (4H)"
        return "2Y avg (2FY)"
    if cadence == "quarterly":
        return "TTM"
    if cadence == "semi_annual":
        return "TTM (2H)"
    return "TTM (FY)"
