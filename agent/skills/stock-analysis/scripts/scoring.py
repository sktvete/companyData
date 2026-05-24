"""Deterministic scoring engine matching scoring-methodology.md.

Every score is 0-100. Weights and thresholds are hardcoded to match
the documented rubric exactly.
"""

from __future__ import annotations

from typing import Any


def _clamp(value: float, lo: float = 0, hi: float = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def _range_score(value: float | None, ranges: list[tuple[float, float, int, int]], null_score: int = 40) -> int:
    """Score a value against a list of (min_val, max_val, min_score, max_score) ranges.

    Ranges are checked in order; first match wins.
    Convention: use math.inf for open-ended ranges.
    For open-ended ranges, returns the midpoint of score_lo and score_hi.
    """
    if value is None:
        return null_score
    import math as _math
    if _math.isnan(value) or _math.isinf(value):
        return null_score
    for lo, hi, score_lo, score_hi in ranges:
        if lo <= value < hi:
            if score_lo == score_hi:
                return score_lo
            finite_lo = lo if _math.isfinite(lo) else value
            finite_hi = hi if _math.isfinite(hi) else value
            span = finite_hi - finite_lo
            if span <= 0:
                return (score_lo + score_hi) // 2
            frac = (value - finite_lo) / span
            frac = max(0.0, min(1.0, frac))
            return _clamp(score_lo + frac * (score_hi - score_lo))
    return null_score


INF = float("inf")


# ---------------------------------------------------------------------------
# Growth Score (20% weight)
# ---------------------------------------------------------------------------

def score_growth(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    """Score growth category. Returns (score, penalties_applied)."""
    penalties: list[str] = []

    rev_yoy = metrics.get("revenue_growth_yoy")
    rev_yoy_pct = rev_yoy * 100 if rev_yoy is not None else None
    s_rev_yoy = _range_score(rev_yoy_pct, [
        (30, INF, 90, 100), (15, 30, 70, 89), (5, 15, 50, 69),
        (0, 5, 30, 49), (-INF, 0, 0, 29),
    ])

    rev_cagr = metrics.get("revenue_cagr_3y")
    rev_cagr_pct = rev_cagr * 100 if rev_cagr is not None else None
    s_rev_cagr = _range_score(rev_cagr_pct, [
        (25, INF, 90, 100), (12, 25, 70, 89), (5, 12, 50, 69),
        (0, 5, 30, 49), (-INF, 0, 0, 29),
    ])

    accel = metrics.get("revenue_acceleration")
    if accel is not None and accel > 0:
        s_accel_bonus = 15
    elif accel is not None:
        s_accel_bonus = -10
    else:
        s_accel_bonus = 0

    eps_yoy = metrics.get("eps_growth_yoy")
    eps_yoy_pct = eps_yoy * 100 if eps_yoy is not None else None
    s_eps = _range_score(eps_yoy_pct, [
        (25, INF, 90, 100), (10, 25, 70, 89), (0, 10, 50, 69),
        (-INF, 0, 0, 29),
    ])

    fcf_yoy = metrics.get("fcf_growth_yoy")
    fcf_yoy_pct = fcf_yoy * 100 if fcf_yoy is not None else None
    s_fcf = _range_score(fcf_yoy_pct, [
        (25, INF, 90, 100), (10, 25, 70, 89), (0, 10, 50, 69),
        (-INF, 0, 0, 29),
    ])

    fcf_ps = metrics.get("fcf_per_share_growth")
    fcf_ps_pct = fcf_ps * 100 if fcf_ps is not None else None
    s_fcf_ps = _range_score(fcf_ps_pct, [
        (20, INF, 90, 100), (10, 20, 70, 89), (0, 10, 50, 69),
        (-INF, 0, 0, 29),
    ])

    base = (
        s_rev_yoy * 0.30
        + s_rev_cagr * 0.20
        + s_eps * 0.20
        + s_fcf * 0.10
        + s_fcf_ps * 0.10
    )
    # Acceleration is a direct bonus/penalty to the growth score (10% slot)
    weighted = base + s_accel_bonus

    # EPS vs FCF disconnect penalty
    if eps_yoy_pct is not None and eps_yoy_pct > 15:
        if fcf_yoy_pct is not None and fcf_yoy_pct <= 0:
            weighted -= 15
            penalties.append("EPS grows >15% but FCF flat/negative")

    return _clamp(weighted), penalties


# ---------------------------------------------------------------------------
# Quality Score (20% weight)
# ---------------------------------------------------------------------------

def score_quality(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    penalties: list[str] = []

    gm = metrics.get("gross_margin")
    gm_pct = gm * 100 if gm is not None else None
    s_gm = _range_score(gm_pct, [
        (60, INF, 90, 100), (40, 60, 70, 89), (25, 40, 50, 69),
        (15, 25, 30, 49), (-INF, 15, 0, 29),
    ])

    om = metrics.get("operating_margin")
    om_pct = om * 100 if om is not None else None
    s_om = _range_score(om_pct, [
        (25, INF, 90, 100), (15, 25, 70, 89), (8, 15, 50, 69),
        (0, 8, 30, 49), (-INF, 0, 0, 29),
    ])

    nm = metrics.get("net_margin")
    nm_pct = nm * 100 if nm is not None else None
    s_nm = _range_score(nm_pct, [
        (20, INF, 90, 100), (10, 20, 70, 89), (5, 10, 50, 69),
        (0, 5, 30, 49), (-INF, 0, 0, 29),
    ])

    margin_trend = metrics.get("margin_trend")
    if margin_trend is not None:
        mt_bps = margin_trend * 10000
        if mt_bps > 50:
            s_mt = 90
        elif mt_bps > 0:
            s_mt = 70
        elif mt_bps > -50:
            s_mt = 50
        else:
            s_mt = 20
    else:
        s_mt = 40

    roic = metrics.get("roic")
    # ROIC is now normalized to decimal form by metrics.py (0.25 = 25%)
    roic_pct = roic * 100 if roic is not None else None
    s_roic = _range_score(roic_pct, [
        (25, INF, 90, 100), (15, 25, 70, 89), (8, 15, 50, 69),
        (0, 8, 30, 49), (-INF, 0, 0, 29),
    ])

    base = s_gm * 0.25 + s_om * 0.25 + s_nm * 0.15 + s_mt * 0.15 + s_roic * 0.20

    rev_yoy = metrics.get("revenue_growth_yoy")
    if rev_yoy is not None and rev_yoy > 0.10 and margin_trend is not None and margin_trend < -0.02:
        base -= 10
        penalties.append("Revenue grows >10% but operating margin contracts >200bps")

    return _clamp(base), penalties


# ---------------------------------------------------------------------------
# Valuation Score (20% weight)
# ---------------------------------------------------------------------------

def score_valuation(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    penalties: list[str] = []

    peg = metrics.get("peg_ratio")
    s_peg = _range_score(peg, [
        (-INF, 1, 90, 100), (1, 1.5, 70, 89), (1.5, 2.5, 50, 69),
        (2.5, 3.5, 30, 49), (3.5, INF, 0, 29),
    ])

    ev_ebitda = metrics.get("ev_to_ebitda")
    s_ev = _range_score(ev_ebitda, [
        (-INF, 10, 90, 100), (10, 15, 70, 89), (15, 25, 50, 69),
        (25, 40, 30, 49), (40, INF, 0, 29),
    ])

    fcf_yield = metrics.get("fcf_yield")
    fcf_yield_pct = fcf_yield * 100 if fcf_yield is not None else None
    s_fcf = _range_score(fcf_yield_pct, [
        (6, INF, 90, 100), (4, 6, 70, 89), (2, 4, 50, 69),
        (0, 2, 30, 49), (-INF, 0, 0, 29),
    ])

    ps = metrics.get("price_to_sales")
    rev_growth = metrics.get("revenue_growth_yoy")
    if ps is not None and rev_growth is not None and rev_growth > 0:
        ps_growth_ratio = ps / (rev_growth * 100) if rev_growth * 100 > 0 else None
    else:
        ps_growth_ratio = None
    s_ps = _range_score(ps_growth_ratio, [
        (-INF, 0.5, 90, 100), (0.5, 1, 70, 89), (1, 2, 50, 69),
        (2, INF, 30, 49),
    ])

    # Trailing P/E context (simplified: compare forward vs trailing)
    trailing_pe = metrics.get("pe_ratio")
    forward_pe = metrics.get("forward_pe")
    if trailing_pe is not None and forward_pe is not None and forward_pe > 0:
        if forward_pe < trailing_pe * 0.8:
            s_pe_ctx = 70
        elif forward_pe < trailing_pe:
            s_pe_ctx = 60
        else:
            s_pe_ctx = 40
    else:
        s_pe_ctx = 40

    base = s_peg * 0.30 + s_ev * 0.20 + s_fcf * 0.20 + s_ps * 0.15 + s_pe_ctx * 0.15

    if forward_pe is None and metrics.get("eps_estimate_current_year") is None:
        base = min(base, 50)
        penalties.append("Forward P/E unavailable — valuation capped at 50")

    return _clamp(base), penalties


# ---------------------------------------------------------------------------
# Balance Sheet Score (15% weight)
# ---------------------------------------------------------------------------

def score_balance_sheet(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    penalties: list[str] = []

    dte = metrics.get("debt_to_equity")
    nd_ebitda = metrics.get("net_debt_to_ebitda")
    ic = metrics.get("interest_coverage")
    dilution_1y = metrics.get("dilution_1y")

    is_net_cash = nd_ebitda is not None and nd_ebitda < 0

    # Count how many core BS metrics are missing
    bs_nulls = sum(1 for v in [dte, nd_ebitda, ic] if v is None)

    if is_net_cash:
        s_dte = 95
        s_nd = 95
    else:
        s_dte = _range_score(dte, [
            (-INF, 0.3, 90, 100), (0.3, 0.8, 70, 89), (0.8, 1.5, 50, 69),
            (1.5, 3, 30, 49), (3, INF, 0, 29),
        ], null_score=35)
        s_nd = _range_score(nd_ebitda, [
            (-INF, 1, 90, 100), (1, 2, 70, 89), (2, 3, 50, 69),
            (3, 5, 30, 49), (5, INF, 0, 29),
        ], null_score=35)

    s_ic = _range_score(ic, [
        (15, INF, 90, 100), (8, 15, 70, 89), (4, 8, 50, 69),
        (2, 4, 30, 49), (-INF, 2, 0, 29),
    ], null_score=35)

    dilution_pct = dilution_1y * 100 if dilution_1y is not None else None
    s_dil = _range_score(dilution_pct, [
        (-INF, -1, 90, 100), (-1, 1, 70, 80), (1, 3, 40, 60),
        (3, INF, 0, 30),
    ])

    base = s_dte * 0.25 + s_nd * 0.25 + s_ic * 0.20 + s_dil * 0.30

    if bs_nulls >= 3:
        penalties.append("All core balance sheet metrics unavailable — score reduced")
        base = min(base, 35)

    return _clamp(base), penalties


# ---------------------------------------------------------------------------
# Earnings Quality Score (10% weight)
# ---------------------------------------------------------------------------

def score_earnings_quality(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    penalties: list[str] = []

    fcf_ni = metrics.get("fcf_to_net_income")
    s_fcf_ni = _range_score(fcf_ni, [
        (1.0, INF, 90, 100), (0.8, 1.0, 70, 89), (0.5, 0.8, 50, 69),
        (0.2, 0.5, 30, 49), (-INF, 0.2, 0, 29),
    ])

    fcf_ps_trend = metrics.get("fcf_per_share_growth")
    if fcf_ps_trend is not None:
        if fcf_ps_trend > 0.10:
            s_fcf_trend = 90
        elif fcf_ps_trend > 0:
            s_fcf_trend = 70
        elif fcf_ps_trend > -0.10:
            s_fcf_trend = 50
        else:
            s_fcf_trend = 20
    else:
        s_fcf_trend = 40

    accruals = metrics.get("accruals_ratio")
    accruals_pct = abs(accruals * 100) if accruals is not None else None
    s_accruals = _range_score(accruals_pct, [
        (-INF, 5, 80, 100), (5, 10, 50, 79), (10, INF, 0, 49),
    ])

    # One-time items: hard to detect purely from EODHD, score neutral
    s_onetime = 60

    base = s_fcf_ni * 0.40 + s_fcf_trend * 0.30 + s_accruals * 0.15 + s_onetime * 0.15

    eps_yoy = metrics.get("eps_growth_yoy")
    fcf_yoy = metrics.get("fcf_growth_yoy")
    if eps_yoy is not None and fcf_yoy is not None:
        eps_pct = eps_yoy * 100
        fcf_pct = fcf_yoy * 100
        if eps_pct - fcf_pct > 20:
            base -= 10
            penalties.append("EPS growth exceeds FCF growth by >20pp")

    return _clamp(base), penalties


# ---------------------------------------------------------------------------
# Catalyst Score (10% weight)
# ---------------------------------------------------------------------------

def score_catalyst(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    penalties: list[str] = []

    analyst_target = metrics.get("analyst_target_price")
    current_price = metrics.get("current_price")
    if analyst_target and current_price and current_price > 0:
        upside = (analyst_target / current_price - 1) * 100
        if upside > 20:
            s_analyst = 90
        elif upside > 10:
            s_analyst = 70
        elif upside > 0:
            s_analyst = 55
        else:
            s_analyst = 30
    else:
        s_analyst = 40

    # Insider/institutional signals
    insider_net = metrics.get("insider_net_buys", 0)
    if insider_net > 3:
        s_insider = 85
    elif insider_net > 0:
        s_insider = 65
    elif insider_net == 0:
        s_insider = 50
    else:
        s_insider = 30

    # Sector/macro and product catalysts are hard to score deterministically
    s_sector = 50
    s_product = 50

    base = s_analyst * 0.30 + s_product * 0.25 + s_sector * 0.25 + s_insider * 0.20
    return _clamp(base), penalties


# ---------------------------------------------------------------------------
# Sentiment Score (informational, not weighted)
# ---------------------------------------------------------------------------

def score_sentiment(metrics: dict[str, Any]) -> int:
    insider_pct = metrics.get("percent_insiders")
    inst_pct = metrics.get("percent_institutions")
    insider_net = metrics.get("insider_net_buys", 0)

    score = 50
    if insider_pct is not None and insider_pct > 10:
        score += 10
    if inst_pct is not None and inst_pct > 70:
        score += 10
    if insider_net > 0:
        score += 15
    elif insider_net < -3:
        score -= 15

    return _clamp(score)


# ---------------------------------------------------------------------------
# Technical Score (5% weight)
# ---------------------------------------------------------------------------

def score_technical(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    penalties: list[str] = []

    pv200 = metrics.get("price_vs_200dma")
    if pv200 is not None:
        if pv200 > 100:
            s_200 = 15  # extreme overbought / bubble territory
        elif pv200 > 50:
            s_200 = 35  # very extended
        elif pv200 > 20:
            s_200 = 65  # healthy uptrend but extended
        elif pv200 > 5:
            s_200 = 85  # above and trending up
        elif pv200 > 0:
            s_200 = 70  # above, flat
        elif pv200 > -10:
            s_200 = 45
        elif pv200 > -20:
            s_200 = 30
        else:
            s_200 = 15
    else:
        s_200 = 40

    pv50 = metrics.get("price_vs_50dma")
    if pv50 is not None:
        if pv50 > 30:
            s_50 = 40  # extremely extended above 50DMA
        elif pv50 > 10:
            s_50 = 65  # somewhat extended
        elif pv50 > 0:
            s_50 = 80  # healthy above
        elif pv50 > -5:
            s_50 = 55
        else:
            s_50 = 35
    else:
        s_50 = 40

    rsi = metrics.get("rsi")
    if rsi is not None:
        if 40 <= rsi <= 60:
            s_rsi = 75
        elif 30 <= rsi < 40:
            s_rsi = 85
        elif 60 < rsi <= 70:
            s_rsi = 60
        elif rsi > 70:
            s_rsi = 45
        elif rsi < 30:
            s_rsi = 40
        else:
            s_rsi = 50
    else:
        s_rsi = 40

    dd = metrics.get("drawdown_from_52w_high")
    if dd is not None:
        dd_abs = abs(dd)
        if dd_abs < 10:
            s_dd = 75
        elif dd_abs < 20:
            s_dd = 65
        elif dd_abs < 40:
            s_dd = 55
        else:
            s_dd = 35
    else:
        s_dd = 40

    base = s_200 * 0.35 + s_50 * 0.25 + s_rsi * 0.20 + s_dd * 0.20
    return _clamp(base), penalties


# ---------------------------------------------------------------------------
# Risk / Red Flag Score (penalty, 0 to -40)
# ---------------------------------------------------------------------------

def score_red_flags(metrics: dict[str, Any]) -> tuple[int, list[dict[str, str]]]:
    """Returns (penalty, list_of_red_flag_objects).

    Penalty is 0 or negative. Each flag has type, severity, description.
    """
    total_penalty = 0
    flags: list[dict[str, str]] = []

    dilution_1y = metrics.get("dilution_1y")
    if dilution_1y is not None and dilution_1y > 0.05:
        total_penalty -= 10
        flags.append({"type": "severe_dilution", "severity": "high",
                       "description": f"Shares growing {dilution_1y*100:.1f}% YoY"})
    elif dilution_1y is not None and dilution_1y > 0.03:
        total_penalty -= 5
        flags.append({"type": "dilution", "severity": "medium",
                       "description": f"Shares growing {dilution_1y*100:.1f}% YoY"})

    # Negative FCF multi-year
    fcf_data = metrics.get("_cash_flow_data", [])
    neg_fcf_years = sum(1 for d in fcf_data[:3] if d.get("free_cash_flow") is not None and d["free_cash_flow"] < 0)
    if neg_fcf_years >= 2:
        total_penalty -= 10
        flags.append({"type": "negative_fcf", "severity": "high",
                       "description": f"Negative FCF for {neg_fcf_years} of last 3 years"})

    # Declining revenue
    rev_data = metrics.get("_income_data", [])
    if len(rev_data) >= 3:
        revs = [d["total_revenue"] for d in rev_data[:3] if d.get("total_revenue") is not None]
        if len(revs) >= 3 and revs[0] < revs[1] < revs[2]:
            total_penalty -= 8
            flags.append({"type": "declining_revenue", "severity": "high",
                           "description": "Revenue declining for 2+ consecutive years"})

    # Operating margin contracting 3+ years
    if len(rev_data) >= 4:
        margins = []
        for d in rev_data[:4]:
            r = d.get("total_revenue")
            oi = d.get("operating_income")
            if r and r > 0 and oi is not None:
                margins.append(oi / r)
        if len(margins) >= 4 and margins[0] < margins[1] < margins[2] < margins[3]:
            total_penalty -= 8
            flags.append({"type": "margin_contraction", "severity": "high",
                           "description": "Operating margin contracting for 3+ years"})

    # High leverage
    nd_ebitda = metrics.get("net_debt_to_ebitda")
    if nd_ebitda is not None and nd_ebitda > 5:
        total_penalty -= 8
        flags.append({"type": "high_leverage", "severity": "high",
                       "description": f"Net debt/EBITDA = {nd_ebitda:.1f}"})

    ic = metrics.get("interest_coverage")
    if ic is not None and ic < 2:
        total_penalty -= 7
        flags.append({"type": "weak_interest_coverage", "severity": "high",
                       "description": f"Interest coverage = {ic:.1f}x"})

    # Revenue growth but negative FCF
    rev_yoy = metrics.get("revenue_growth_yoy")
    fcf = metrics.get("_latest_fcf")
    if rev_yoy is not None and rev_yoy > 0 and fcf is not None and fcf < 0:
        total_penalty -= 5
        flags.append({"type": "growth_no_cash", "severity": "medium",
                       "description": "Revenue growing but FCF is negative"})

    # Bubble territory
    pv200 = metrics.get("price_vs_200dma")
    if pv200 is not None and pv200 > 100:
        total_penalty -= 5
        flags.append({"type": "potential_bubble", "severity": "medium",
                       "description": f"Price {pv200:.0f}% above 200 DMA"})

    total_penalty = max(total_penalty, -40)
    return total_penalty, flags


# ---------------------------------------------------------------------------
# Overall Score Assembly
# ---------------------------------------------------------------------------

WEIGHTS = {
    "growth": 0.20,
    "quality": 0.20,
    "valuation": 0.20,
    "balance_sheet": 0.15,
    "earnings_quality": 0.10,
    "catalyst": 0.10,
    "technical": 0.05,
}


def compute_all_scores(all_metrics: dict[str, Any]) -> dict[str, Any]:
    """Compute all category scores and overall score.

    Args:
        all_metrics: output from metrics.compute_all_metrics(), potentially
            augmented with extra context (analyst_target_price, insider_net_buys, etc.)

    Returns:
        dict with scores, penalties, red_flags, and overall_score.
    """
    flat = {**all_metrics.get("key_metrics", {})}
    flat["revenue_acceleration"] = all_metrics.get("growth", {}).get("revenue_acceleration")
    flat["margin_trend"] = all_metrics.get("quality", {}).get("margin_trend")
    flat["fcf_to_net_income"] = all_metrics.get("earnings_quality", {}).get("fcf_to_net_income")
    flat["accruals_ratio"] = all_metrics.get("earnings_quality", {}).get("accruals_ratio")
    flat["dilution_1y"] = all_metrics.get("dilution", {}).get("dilution_1y")
    flat["current_price"] = all_metrics.get("current_price")
    flat["percent_insiders"] = all_metrics.get("shares_stats", {}).get("percent_insiders")
    flat["percent_institutions"] = all_metrics.get("shares_stats", {}).get("percent_institutions")
    flat["drawdown_from_52w_high"] = all_metrics.get("technicals", {}).get("drawdown_from_52w_high")
    flat["eps_estimate_current_year"] = all_metrics.get("highlights", {}).get("eps_estimate_current_year")

    flat["analyst_target_price"] = all_metrics.get("analyst_target_price")
    flat["insider_net_buys"] = all_metrics.get("insider_net_buys", 0)

    flat["_cash_flow_data"] = all_metrics.get("cash_flow_data", [])
    flat["_income_data"] = all_metrics.get("income_data", [])
    flat["_latest_fcf"] = (
        all_metrics["cash_flow_data"][0]["free_cash_flow"]
        if all_metrics.get("cash_flow_data")
        else None
    )

    growth_score, growth_penalties = score_growth(flat)
    quality_score, quality_penalties = score_quality(flat)
    valuation_score, valuation_penalties = score_valuation(flat)
    bs_score, bs_penalties = score_balance_sheet(flat)
    eq_score, eq_penalties = score_earnings_quality(flat)
    cat_score, cat_penalties = score_catalyst(flat)
    tech_score, tech_penalties = score_technical(flat)
    sentiment = score_sentiment(flat)
    risk_penalty, red_flags = score_red_flags(flat)

    weighted = (
        growth_score * WEIGHTS["growth"]
        + quality_score * WEIGHTS["quality"]
        + valuation_score * WEIGHTS["valuation"]
        + bs_score * WEIGHTS["balance_sheet"]
        + eq_score * WEIGHTS["earnings_quality"]
        + cat_score * WEIGHTS["catalyst"]
        + tech_score * WEIGHTS["technical"]
    )
    overall = _clamp(weighted + risk_penalty)

    all_penalties = (
        growth_penalties + quality_penalties + valuation_penalties
        + bs_penalties + eq_penalties + cat_penalties + tech_penalties
    )

    return {
        "scores": {
            "growth_score": growth_score,
            "quality_score": quality_score,
            "valuation_score": valuation_score,
            "balance_sheet_score": bs_score,
            "earnings_quality_score": eq_score,
            "catalyst_score": cat_score,
            "sentiment_score": sentiment,
            "technical_score": tech_score,
            "risk_red_flag_score": risk_penalty,
        },
        "overall_score": overall,
        "red_flags": red_flags,
        "penalties_applied": all_penalties,
    }


# ---------------------------------------------------------------------------
# Hard Rules
# ---------------------------------------------------------------------------

def apply_hard_rules(
    scores: dict[str, int],
    overall_score: int,
    metrics: dict[str, Any],
    red_flags: list[dict[str, str]],
) -> tuple[str, str, list[str]]:
    """Apply hard decision rules from hard-rules.md.

    Returns (recommendation, confidence, hard_rule_notes).
    """
    notes: list[str] = []
    missing = metrics.get("missing_fields", [])

    # Data confidence
    stale_count = 0
    missing_count = len(missing)
    if missing_count > 5:
        confidence = "low"
    elif missing_count > 2:
        confidence = "medium"
    else:
        confidence = "high"

    # --- Buy blockers ---
    buy_blocked = False

    forward_pe = metrics.get("key_metrics", {}).get("forward_pe")
    ev_ebitda = metrics.get("key_metrics", {}).get("ev_to_ebitda")
    eps_est = metrics.get("highlights", {}).get("eps_estimate_current_year")
    if forward_pe is None and ev_ebitda is None and eps_est is None:
        buy_blocked = True
        notes.append("Buy blocked: missing valuation data (forward PE, EV/EBITDA, EPS estimates)")

    income_data = metrics.get("income_data", [])
    cash_flow_data = metrics.get("cash_flow_data", [])
    if len(income_data) < 2:
        buy_blocked = True
        notes.append("Buy blocked: fewer than 2 years of financial data")

    dilution_1y = metrics.get("dilution", {}).get("dilution_1y")
    if dilution_1y is not None and dilution_1y > 0.05:
        buy_blocked = True
        notes.append(f"Buy blocked: severe dilution ({dilution_1y*100:.1f}% YoY)")

    nd_ebitda = metrics.get("balance_sheet_metrics", {}).get("net_debt_to_ebitda")
    ic = metrics.get("balance_sheet_metrics", {}).get("interest_coverage")
    if nd_ebitda is not None and nd_ebitda > 4 and ic is not None and ic < 3:
        buy_blocked = True
        notes.append(f"Buy blocked: weak balance sheet (ND/EBITDA={nd_ebitda:.1f}, IC={ic:.1f})")

    if confidence == "low":
        buy_blocked = True
        notes.append("Buy blocked: low data confidence")

    # --- Classification ---
    gs = scores.get("growth_score", 0)
    qs = scores.get("quality_score", 0)
    vs = scores.get("valuation_score", 0)
    total_penalty = sum(-abs(f.get("penalty", 0)) for f in red_flags) if False else scores.get("risk_red_flag_score", 0)

    total_risk_penalty = scores.get("risk_red_flag_score", 0)

    # "Broken business": both quality and growth are weak, or heavy red flags
    if (qs < 30 and gs < 30) or total_risk_penalty <= -20:
        recommendation = "no_buy"
        notes.append("Broken business: weak quality and growth fundamentals")
    elif vs >= 70 and (qs < 40 or gs < 30):
        recommendation = "no_buy"
        notes.append("Cheap for a real reason — declining business quality")
    elif qs >= 70 and gs >= 60 and vs < 40:
        recommendation = "watchlist"
        notes.append("Great company but valuation is stretched")
    elif overall_score >= 70 and not buy_blocked:
        recommendation = "buy"
    elif overall_score >= 50 or (overall_score >= 70 and buy_blocked):
        recommendation = "watchlist"
    else:
        recommendation = "no_buy"

    if buy_blocked and recommendation == "buy":
        recommendation = "watchlist"

    return recommendation, confidence, notes
