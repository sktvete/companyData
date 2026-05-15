"""Two-layer metric coloring: quality (broad rules) vs valuation (sector-relative).

Used by the dashboard API so the UI does not mix universal thresholds with
peer-relative valuation cues in one function.
"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Literal

Tone = Literal["pos", "neu", "neg", "na"]

# Sectors where balance-sheet leverage norms differ; skip D/E traffic lights.
_LEVERAGE_NA_SECTORS = frozenset(
    {
        "financial services",
        "real estate",
    }
)


def _fin(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def is_leverage_tone_na_sector(sector: str | None) -> bool:
    s = (sector or "").strip().lower()
    if not s:
        return False
    if s in _LEVERAGE_NA_SECTORS:
        return True
    if "reit" in s:
        return True
    return False


def quality_growth_pct_pct(v: float | None) -> Tone:
    """YoY or CAGR % — sign-first; modest emphasis on strong growth."""
    x = _fin(v)
    if x is None:
        return "na"
    if x > 0:
        return "pos"
    if x < 0:
        return "neg"
    return "neu"


def quality_fcf_usd(fcf_usd: float | None) -> Tone:
    x = _fin(fcf_usd)
    if x is None:
        return "na"
    if x > 0:
        return "pos"
    if x < 0:
        return "neg"
    return "neu"


def quality_debt_to_equity(de: float | None, sector: str | None) -> Tone:
    if is_leverage_tone_na_sector(sector):
        return "na"
    x = _fin(de)
    if x is None:
        return "na"
    if x > 2.5:
        return "neg"
    if x > 1.5:
        return "neu"
    return "pos"


def valuation_pe(pe: float | None, sector_median_pe: float | None) -> Tone:
    """Lower P/E vs sector median → more attractive (pos)."""
    x = _fin(pe)
    if x is None or x <= 0 or x > 500:
        return "na"
    med = _fin(sector_median_pe)
    if med is None or med <= 0:
        return "neu"
    if x < med * 0.85:
        return "pos"
    if x > med * 1.25:
        return "neg"
    return "neu"


def valuation_peg(peg: float | None) -> Tone:
    """Weak universal bands — EPS growth estimates can be noisy."""
    x = _fin(peg)
    if x is None or x <= 0 or x > 20:
        return "na"
    if x <= 1.0:
        return "pos"
    if x >= 2.5:
        return "neg"
    return "neu"


def valuation_roe_pct(roe_pct: float | None, sector_median_roe_pct: float | None) -> Tone:
    """ROE vs sector median (not vs one global %)."""
    x = _fin(roe_pct)
    if x is None:
        return "na"
    med = _fin(sector_median_roe_pct)
    if med is None or abs(med) < 1e-6:
        if x >= 15:
            return "pos"
        if x >= 5:
            return "neu"
        return "neg"
    ratio = x / med
    if ratio > 1.15:
        return "pos"
    if ratio < 0.85:
        return "neg"
    return "neu"


def valuation_fcf_yield(
    fcf_yield_ratio: float | None, sector_median_yield_ratio: float | None
) -> Tone:
    """FCF / market cap vs sector — higher yield → pos."""
    x = _fin(fcf_yield_ratio)
    if x is None:
        return "na"
    med = _fin(sector_median_yield_ratio)
    if med is None or med <= 0:
        if x > 0.05:
            return "pos"
        if x < 0:
            return "neg"
        return "neu"
    if x > med * 1.25:
        return "pos"
    if x < med * 0.75:
        return "neg"
    return "neu"


def build_sector_valuation_medians(companies: list[dict]) -> dict[str, dict[str, float]]:
    """Median P/E, PEG, ROE%, gross margin%, D/E, FCF yield (ratio) per sector."""
    raw: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for c in companies:
        sec = (c.get("sector") or "Unknown").strip() or "Unknown"
        m = c.get("financial_metrics") or {}
        ci = c.get("company_info") or {}
        s = c.get("investment_scores") or {}

        pe = _fin(ci.get("pe_ratio")) or _fin(m.get("pe_ratio"))
        if pe is not None and 0 < pe < 500:
            raw[sec]["pe_ratio"].append(pe)

        peg = _fin(s.get("peg_ratio")) or _fin(m.get("peg_ratio"))
        if peg is not None and 0 < peg < 15:
            raw[sec]["peg_ratio"].append(peg)

        gm = _fin(s.get("gross_margin_pct"))
        if gm is None:
            gmr = _fin(m.get("gross_margin"))
            if gmr is not None:
                gm = gmr * 100.0
        if gm is not None and -30 < gm < 95:
            raw[sec]["gross_margin_pct"].append(gm)

        roe = _fin(m.get("roe"))
        if roe is not None:
            roe_pct = roe * 100.0 if abs(roe) <= 2 else roe
            if -80 < roe_pct < 120:
                raw[sec]["roe_pct"].append(roe_pct)

        de = _fin(m.get("debt_to_equity"))
        if de is not None and 0 <= de < 30:
            raw[sec]["debt_to_equity"].append(de)

        fy = _fin(m.get("fcf_yield"))
        if fy is not None and -0.2 < fy < 0.4:
            raw[sec]["fcf_yield"].append(fy)

    out: dict[str, dict[str, float]] = {}
    for sec, buckets in raw.items():
        med: dict[str, float] = {}
        for key, vals in buckets.items():
            if len(vals) >= 3:
                med[key] = float(median(vals))
        if med:
            out[sec] = med
    return out


def row_tones(raw_company: dict, sector_meds: dict[str, dict[str, float]]) -> dict[str, Tone]:
    """All dashboard tone keys for one company row (API contract)."""
    sector = (raw_company.get("sector") or "Unknown").strip() or "Unknown"
    m = raw_company.get("financial_metrics") or {}
    ci = raw_company.get("company_info") or {}
    s = raw_company.get("investment_scores") or {}
    med = sector_meds.get(sector, {})

    pe = _fin(ci.get("pe_ratio")) or _fin(m.get("pe_ratio"))
    peg = _fin(s.get("peg_ratio")) or _fin(m.get("peg_ratio"))
    roe_raw = _fin(m.get("roe"))
    roe_pct = roe_raw * 100.0 if roe_raw is not None and abs(roe_raw) <= 2 else roe_raw
    rg1 = _fin(m.get("revenue_growth_1y"))
    rg1_pct = rg1 * 100.0 if rg1 is not None and abs(rg1) <= 2 else rg1
    eg1 = _fin(m.get("eps_growth"))
    eg1_pct = eg1 * 100.0 if eg1 is not None and abs(eg1) <= 2 else eg1
    rg5 = _fin(m.get("revenue_cagr_4y"))
    rg5_pct = rg5 * 100.0 if rg5 is not None and abs(rg5) <= 2 else rg5
    de = _fin(m.get("debt_to_equity"))

    return {
        "rev_growth_1y": quality_growth_pct_pct(rg1_pct),
        "eps_growth_1y": quality_growth_pct_pct(eg1_pct),
        "rev_growth_5y": quality_growth_pct_pct(rg5_pct),
        "roe": valuation_roe_pct(roe_pct, med.get("roe_pct")),
        "debt_equity": quality_debt_to_equity(de, sector),
        "fcf": quality_fcf_usd(m.get("free_cash_flow")),
        "pe": valuation_pe(pe, med.get("pe_ratio")),
        "peg": valuation_peg(peg),
        "fcf_yield": valuation_fcf_yield(m.get("fcf_yield"), med.get("fcf_yield")),
    }
