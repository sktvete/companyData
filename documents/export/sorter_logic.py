import math
import re

# ── Helper functions ──────────────────────────────────────────────────────────────

def _clamp01(v: float) -> float:
    if v <= 0:
        return 0.0
    if v >= 1:
        return 1.0
    return v


def _is_financial_like(c: dict) -> bool:
    sector = (c.get("sector") or "").strip().lower()
    industry = (c.get("industry") or "").strip().lower()
    if sector in {"financial services", "real estate"}:
        return True
    keywords = ("bank", "insurance", "reit", "capital markets", "asset management", "mortgage")
    if any(k in industry for k in keywords):
        return True
    return False


def _cagr_to_unit(cagr: float) -> float:
    """Map a CAGR ratio (e.g. 0.12 = 12%) to 0–1 for screener blending."""
    c = float(cagr or 0.0)
    if c <= 0:
        return 0.0
    if c >= 0.25:
        return 1.0
    if c >= 0.18:
        return 0.88
    if c >= 0.12:
        return 0.74
    if c >= 0.08:
        return 0.58
    if c >= 0.05:
        return 0.42
    if c >= 0.03:
        return 0.28
    return max(0.08, 0.28 * (c / 0.03))


def _blended_revenue_cagr(m: dict) -> float:
    """Headline revenue trend for screening: ~65% 3y / 35% 4y (3y fits a multi-year hold; 4y smooths noise)."""
    rev4 = float(m.get("revenue_cagr_4y") or 0.0)
    rev3 = float(m.get("revenue_cagr_3y") or 0.0)
    return 0.65 * rev3 + 0.35 * rev4


def _long_term_growth_factor(m: dict, s: dict) -> float:
    """0–1: reward sustained multi-year revenue growth; per-share earnings are secondary."""
    rev4 = float(m.get("revenue_cagr_4y") or 0.0)
    rev3 = float(m.get("revenue_cagr_3y") or 0.0)
    oeps = float(m.get("oeps_cagr") or 0.0)
    eps_g = float(m.get("eps_growth") or 0.0)
    rev_long = _blended_revenue_cagr(m)
    earn_long = max(oeps, eps_g)
    if rev_long <= 0 and earn_long <= 0:
        return 0.0
    rev_u = _cagr_to_unit(rev_long)
    earn_u = _cagr_to_unit(earn_long)
    # Buybacks / margin expansion: don't let per-share CAGR dominate weak top-line growth.
    if rev_long < 0.12 and earn_long > 0.25:
        earn_u = min(earn_u, rev_u + 0.12)
    blended = 0.80 * rev_u + 0.20 * earn_u
    # Sustained runway: both 3y and 4y revenue CAGRs solid and not collapsing.
    if rev4 >= 0.06 and rev3 >= 0.05 and rev3 >= rev4 * 0.65:
        blended = min(1.0, blended * 1.10)
    rev1y = float(m.get("revenue_growth_1y") or 0.0)
    if rev1y >= 0.25:
        blended = min(1.0, blended * 1.10)
    elif rev1y >= 0.15:
        blended = min(1.0, blended * 1.06)
    # Penalize revenue shrinking over the long window even if one year bounced.
    if rev4 < 0 or rev3 < 0:
        blended *= 0.55
    elif rev_long < 0.03:
        blended *= 0.75
    return min(1.0, max(0.0, blended))


def _listing_scale_confidence(mcap_b: float, rev_b: float) -> float:
    """Mild size prior: micro-caps stay discounted; mid-cap compounders need not be mega-caps."""
    mcap_f = 0.78 + 0.22 * _clamp01((mcap_b - 0.5) / 20.0)
    rev_f = 0.78 + 0.22 * _clamp01((rev_b - 0.15) / 5.0)
    return math.sqrt(max(mcap_f * rev_f, 1e-9))


def _steady_compounder_confidence_lift(m: dict, s: dict) -> float:
    """Lift consistent multi-year revenue compounders (high growth + stable track)."""
    rc = float(m.get("revenue_growth_consistency") or 0.5)
    rev_long = _blended_revenue_cagr(m)
    g = float(s.get("growth_score", 0) or 0)
    sf = float(s.get("safety_score", 0) or 0)
    ni = float(m.get("net_income", 0) or 0)
    if rc < 0.70 or rev_long < 0.12 or g < 3.0 or sf < 3.5 or ni <= 0:
        return 1.0
    lift = 1.0
    lift += 0.08 * _clamp01((rev_long - 0.12) / 0.28)
    lift += 0.06 * _clamp01((rc - 0.70) / 0.30)
    if g >= 4.0:
        lift += 0.04
    return min(lift, 1.20)


def _per_share_growth_distortion_factor(m: dict) -> float:
    """Down-rank when OEPS/EPS CAGR far exceeds multi-year revenue CAGR (buybacks, margins, base effects)."""
    rev_long = _blended_revenue_cagr(m)
    earn_long = max(
        float(m.get("oeps_cagr") or 0.0),
        float(m.get("eps_growth") or 0.0),
    )
    if rev_long >= 0.12 or earn_long <= 0.25:
        return 1.0
    gap = earn_long - rev_long
    if gap <= 0.12:
        return 0.96
    elif gap <= 0.20:
        return 0.92
    elif gap <= 0.30:
        return 0.85
    else:
        return 0.75


# ── Margin cache (must be loaded from margin_index.json) ─────────────────────────────

_MARGIN_CACHE: dict[str, float] = {}
company_lookup: dict[str, dict] = {}  # Optional: for duplicate share penalties


def load_margin_cache(margin_index_file: str) -> None:
    """Load margin ratios from pre-built index file."""
    global _MARGIN_CACHE
    import json
    with open(margin_index_file) as f:
        _MARGIN_CACHE = json.load(f)


def _margin_cycle_ratio(sym: str) -> float:
    """Return current/median margin ratio for a symbol (0 if unknown)."""
    return _MARGIN_CACHE.get(sym, 0.0)


# ── Main sorting functions ───────────────────────────────────────────────────────────

def _compounder_list_score(c: dict) -> float:
    """Default dashboard rank (0–20): **value + safety** first, **growth** for 3y upside.

    Tuned for "make money over ~3 years, don't blow up": cheap vs fundamentals (PEG/P/E,
    FCF yield in the pipeline's value_score), durable balance sheet (safety_score), and
    still requires real compounding (growth_score + 3y‑weighted revenue track). Quality
    stays in the mix but is slightly less dominant than raw franchise quality alone.
    """
    s = c.get("investment_scores") or {}
    m = c.get("financial_metrics") or {}
    ci = c.get("company_info") or {}
    is_fin = _is_financial_like(c)
    is_biotech = "biotech" in (c.get("industry") or "").lower()

    q = float(s.get("quality_score", 0.0) or 0.0) / 5.0
    g = float(s.get("growth_score", 0.0) or 0.0) / 5.0
    v = float(s.get("value_score", 0.0) or 0.0) / 5.0
    sf = float(s.get("safety_score", 0.0) or 0.0) / 5.0

    # Dampen growth contribution when margins are at cyclical peak.
    sym_for_margin = (c.get("symbol") or "").strip().upper()
    _mcr_early = _margin_cycle_ratio(sym_for_margin)
    sector_early = (c.get("sector") or "").strip().lower()
    industry_early = (c.get("industry") or "").strip().lower()
    _is_cyc_early = sector_early in {"energy", "basic materials"} or (
        sector_early == "technology" and any(
            k in industry_early for k in ("memory", "storage")
        )
    )
    if _is_cyc_early and _mcr_early > 2.0:
        g *= 0.5
    elif _is_cyc_early and _mcr_early > 1.5:
        g *= 0.7

    # Stable growth premium
    _rc = m.get("revenue_growth_consistency")
    rev_consistency = float(_rc) if _rc is not None else 0.5
    if rev_consistency >= 0.75:
        g *= 1.10
    elif rev_consistency < 0.3:
        g *= 0.80

    g_lt = _long_term_growth_factor(m, s)
    if _is_cyc_early and _mcr_early > 1.5:
        g_lt *= 0.55 if _mcr_early > 2.0 else 0.72
    g = min(1.0, 0.34 * g + 0.66 * max(g, g_lt))
    rev_long_for_g = _blended_revenue_cagr(m)
    earn_long_for_g = max(float(m.get("oeps_cagr") or 0.0), float(m.get("eps_growth") or 0.0))
    if rev_long_for_g < 0.12 and earn_long_for_g > 0.25:
        g = min(g, _cagr_to_unit(rev_long_for_g) + 0.10)

    # Weights: growth leads; value/safety are guardrails
    base = (0.14 * q) + (0.36 * g) + (0.25 * sf) + (0.25 * v)
    base = max(base, float(s.get("overall_score", 0.0) or 0.0) / 20.0 * 0.7)

    rev = float(m.get("revenue", 0.0) or 0.0)
    rev_b = rev / 1e9
    mcap = float(ci.get("market_cap", 0.0) or 0.0)
    mcap_b = mcap / 1e9
    rev_mcap_ratio = (rev / mcap) if (mcap > 0 and rev > 0) else 0.0
    gm = float(m.get("gross_margin", 0.0) or 0.0)
    roic = float(m.get("roic", 0.0) or 0.0)
    roe = float(m.get("roe", 0.0) or 0.0)
    net_income = float(m.get("net_income", 0.0) or 0.0)
    fcf = float(m.get("free_cash_flow", 0.0) or 0.0)
    red_flags = int(m.get("red_flag_count", 0) or 0)
    pe = float(ci.get("pe_ratio") or m.get("pe_ratio") or 0.0)
    peg = float(s.get("peg_ratio") or m.get("peg_ratio") or 0.0)
    dte = float(m.get("debt_to_equity", 0.0) or 0.0)
    min_q = int((c.get("data_quality") or {}).get("min_quarters", 0) or 0)
    sector_l = (c.get("sector") or "").strip().lower()
    rev_cagr = float(s.get("revenue_cagr_3y_pct", 0.0) or 0.0) / 100.0

    confidence = 1.0
    if not is_fin and rev_mcap_ratio > 0:
        if rev_mcap_ratio > 80.0:
            confidence *= 0.20
        elif rev_mcap_ratio > 40.0:
            confidence *= 0.42
        elif rev_mcap_ratio > 25.0:
            confidence *= 0.62
        elif rev_mcap_ratio > 18.0:
            confidence *= 0.78
    if roe > 2.0 or roic > 2.0:
        confidence *= 0.35
    elif roe > 1.2 or roic > 1.2:
        confidence *= 0.55
    elif roe > 0.85 or roic > 0.85:
        confidence *= 0.72
    confidence *= _listing_scale_confidence(mcap_b, rev_b)
    confidence *= 0.70 + 0.30 * _clamp01((min_q - 12.0) / 56.0)

    if net_income <= 0:
        confidence *= 0.80
    if fcf <= 0:
        confidence *= 0.83
    fcf_conv = float(m.get("fcf_conversion", 0.0) or 0.0)
    if net_income > 0:
        if fcf_conv < 0.45:
            confidence *= 0.84
        elif fcf_conv < 0.70:
            confidence *= 0.92
    if roe < 0.05 and roic < 0.06:
        confidence *= 0.76
    elif roe < 0.08 and roic < 0.08:
        confidence *= 0.88
    if roic < 0.05:
        confidence *= 0.87
    elif roic < 0.08:
        confidence *= 0.94
    if red_flags >= 3:
        confidence *= 0.88
    if red_flags >= 5:
        confidence *= 0.82

    if pe <= 0:
        confidence *= 0.92
    elif pe < 7:
        confidence *= 0.93
    elif pe > 60:
        confidence *= 0.82
    elif pe > 40:
        confidence *= 0.90
    if pe > 35 and v < 0.25:
        confidence *= 0.88
    if pe > 50 and (roe < 0.10 or roic < 0.08):
        confidence *= 0.70
    if peg > 0:
        if peg > 5:
            confidence *= 0.80
        elif peg > 3:
            confidence *= 0.90

    if not is_fin:
        if gm > 1.0 or gm < 0:
            confidence *= 0.56
        elif gm > 0.85:
            confidence *= 0.78
    if is_fin:
        confidence *= 0.95
        if mcap_b < 10 or rev_b < 1.0:
            confidence *= 0.84
        elif mcap_b < 100:
            confidence *= 0.93
        if dte > 6:
            confidence *= 0.85
    if sector_l in {"energy", "basic materials"}:
        if rev_cagr < 0.08:
            confidence *= 0.86
        if roic < 0.12:
            confidence *= 0.90
        if mcap_b < 120 or rev_b < 8.0:
            confidence *= 0.82
    industry_l = (c.get("industry") or "").strip().lower()
    is_memory_semi = sector_l == "technology" and any(
        k in industry_l for k in ("memory", "storage")
    )
    is_semiconductor = sector_l == "technology" and "semiconductor" in industry_l
    if is_memory_semi:
        if rev_cagr > 0.25:
            confidence *= 0.78
        if g > 0.85:
            confidence *= 0.85
    elif is_semiconductor:
        if rev_cagr > 0.40:
            confidence *= 0.90

    is_cyclical_sector = sector_l in {"energy", "basic materials"} or is_memory_semi
    sym_upper = (c.get("symbol") or "").strip().upper()
    mcr = _margin_cycle_ratio(sym_upper)
    if mcr > 1.0:
        if is_cyclical_sector:
            if mcr > 3.0:
                confidence *= 0.45
            elif mcr > 2.5:
                confidence *= 0.55
            elif mcr > 2.0:
                confidence *= 0.65
            elif mcr > 1.5:
                confidence *= 0.78
        else:
            if mcr > 3.0:
                confidence *= 0.75
            elif mcr > 2.5:
                confidence *= 0.85
    if is_biotech and rev_b < 0.8 and (roe > 0.8 or roic > 0.8):
        confidence *= 0.78
    if rev_b < 0.15 and mcap_b < 0.8:
        confidence *= 0.72

    if v < 0.05:
        confidence *= 0.82
    elif v < 0.20:
        confidence *= 0.90
    elif v < 0.35:
        confidence *= 0.96

    if v >= 0.34 and sf >= 0.34:
        confidence *= 1.035

    sym = (c.get("symbol") or "").strip().upper()
    if "-" in sym:
        sym_base, cls = sym.rsplit("-", 1)
        if cls in {"B", "C"} and f"{sym_base}-A" in company_lookup:
            confidence *= 0.93 if cls == "B" else 0.90
    elif sym.endswith("L") and sym[:-1] in company_lookup:
        confidence *= 0.96

    confidence *= _steady_compounder_confidence_lift(m, s)

    score = 20.0 * base * confidence
    score *= _per_share_growth_distortion_factor(m)
    growth_raw = float(s.get("growth_score", 0.0) or 0.0)
    rev_long = _blended_revenue_cagr(m)
    if growth_raw < 2.0:
        score = min(score, 9.0)
    elif growth_raw < 2.5:
        score = min(score, 10.5)
    elif growth_raw < 3.0 and rev_long < 0.10:
        score = min(score, 11.5)
    elif growth_raw < 3.5 and rev_long < 0.12:
        score = min(score, 13.5)
    if rev_long < 0.08:
        score = min(score, 10.0)
    elif rev_long < 0.10:
        score = min(score, 12.0)
    elif rev_long < 0.12:
        score = min(score, 14.0)
    elif rev_long < 0.15:
        score = min(score, 15.5)
    return round(max(score, 0.0), 4)


def _cached_listing_score(c: dict) -> float:
    """Listing score computed once at load; avoid O(n) recompute."""
    cached = c.get("_listing_score")
    if cached is not None:
        return float(cached)
    val = _compounder_list_score(c)
    c["_listing_score"] = val
    return val


def _listing_sort_key(c: dict) -> tuple[float, str]:
    return (-_cached_listing_score(c), (c.get("symbol") or ""))


# ── Usage example ─────────────────────────────────────────────────────────────────

def sort_companies(companies: list[dict]) -> list[dict]:
    """Sort companies by listing score (highest first)."""
    return sorted(companies, key=_listing_sort_key)
