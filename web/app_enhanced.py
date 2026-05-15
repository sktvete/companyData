#!/usr/bin/env python3
"""
Equity Analysis Web Application
Serves the latest scaled universe with optional rescored score overlay, sector views,
and infinite-scroll API. Rankings come from stored pipeline output + EODHD snapshots,
not from live in-request re-analysis.
"""

import os
import re
import sys
import json
import math
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from datetime import datetime
from dotenv import load_dotenv
import requests as _req

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.io_utils import read_jsonl, read_json
from equity_sorter.cache import PriceStore
from equity_sorter.canonical.ttm_periods import (
    select_ttm_period_keys,
    ttm_cadence_label,
    ttm_display_label,
    ttm_flow_period_count,
)

import codex_chat
import chat_tools
from glossary_data import GLOSSARY
from metric_tones import build_sector_valuation_medians, row_tones

load_dotenv()

app = Flask(__name__)


@app.context_processor
def _inject_glossary():
    return {"G": GLOSSARY}

# ── Global state ──────────────────────────────────────────────────────────────
companies: list[dict] = []
company_lookup: dict[str, dict] = {}
DATA_SOURCE = "none"
DATA_FILE: Path | None = None  # primary universe jsonl (e.g. scaled)
DATA_OVERLAY_FILE: Path | None = None  # rescored jsonl applied on top, if any
sector_valuation_medians: dict[str, dict[str, float]] = {}

def _latest_nonempty(directory: Path, pattern: str) -> Path | None:
    """Return the most-recent non-empty file matching pattern."""
    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        data = read_jsonl(f)
        if data:
            return f
    return None


def _dedupe_rows_best_score(rows: list[dict]) -> list[dict]:
    """De-duplicate by symbol (keep row with highest overall_score)."""
    seen: dict[str, dict] = {}
    for c in rows:
        sym = c["symbol"]
        existing_score = seen.get(sym, {}).get("investment_scores", {}).get("overall_score", -1)
        new_score = c.get("investment_scores", {}).get("overall_score", 0)
        if new_score >= existing_score:
            seen[sym] = c
    return sorted(
        seen.values(),
        key=lambda x: x.get("investment_scores", {}).get("overall_score", 0),
        reverse=True,
    )


def _inject_eps_growth(rows: list[dict]) -> None:
    """Back-fill eps_growth from EODHD Highlights for rows that are missing it."""
    cache_dir = PROJECT_ROOT / "outputs" / "fundamentals_cache"
    if not cache_dir.is_dir():
        return
    patched = 0
    for c in rows:
        m = c.get("financial_metrics") or c.get("metrics") or {}
        if m.get("eps_growth"):
            continue
        sym = c.get("symbol", "")
        fp = cache_dir / f"{sym}.json"
        if not fp.is_file():
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            val = (data.get("Highlights") or {}).get("QuarterlyEarningsGrowthYOY")
            if val is not None and val != "":
                eg = float(val) if isinstance(val, (int, float)) else float(str(val).strip())
                if eg != 0.0:
                    m["eps_growth"] = eg
                    patched += 1
        except Exception:
            pass
    if patched:
        print(f"[OK] Injected eps_growth for {patched} companies from EODHD Highlights")


def load_data() -> bool:
    """Load universe from latest scaled (or final), overlay rescored scores when present.

    Root issue fixed: an older small ``rescored_*.jsonl`` must not replace a larger
    ``scaled_analysis_*.jsonl`` — we always keep the scaled universe and only patch
    ``investment_scores`` / ``name`` from rescored for matching symbols.
    """
    global companies, company_lookup, DATA_SOURCE, DATA_FILE, DATA_OVERLAY_FILE, sector_valuation_medians

    output_dir = PROJECT_ROOT / "outputs"

    scaled_f = _latest_nonempty(output_dir / "scaled_analysis", "scaled_analysis_*.jsonl")
    rescored_f = _latest_nonempty(output_dir / "rescored_analysis", "rescored_*.jsonl")
    final_f = _latest_nonempty(output_dir / "final_working_analysis", "*analysis_*.jsonl")

    scaled_rows = read_jsonl(scaled_f) if scaled_f else []
    rescored_rows = read_jsonl(rescored_f) if rescored_f else []
    final_rows = read_jsonl(final_f) if final_f else []

    base_rows: list[dict] = []
    base_label = ""
    base_file: Path | None = None

    if scaled_rows:
        base_rows, base_label, base_file = scaled_rows, "scaled", scaled_f
    elif final_rows:
        base_rows, base_label, base_file = final_rows, "final", final_f
    elif rescored_rows:
        base_rows, base_label, base_file = rescored_rows, "rescored", rescored_f
    else:
        companies = []
        company_lookup = {}
        sector_valuation_medians = {}
        DATA_SOURCE = "none"
        DATA_FILE = None
        DATA_OVERLAY_FILE = None
        print("[ERR] No analysis data found")
        return False

    base_rows = _dedupe_rows_best_score(base_rows)
    rescored_map = {c["symbol"]: c for c in rescored_rows} if rescored_rows else {}
    overlay_used = False
    # Only apply overlay if it's NEWER than the base data (prevents stale pre-TTM scores)
    if rescored_map and base_label in ("scaled", "final") and rescored_f and base_file:
        overlay_mtime = rescored_f.stat().st_mtime if rescored_f.is_file() else 0
        base_mtime = base_file.stat().st_mtime if base_file.is_file() else 0
        if overlay_mtime > base_mtime:
            for c in base_rows:
                sym = c["symbol"]
                if sym in rescored_map:
                    rc = rescored_map[sym]
                    c["investment_scores"] = dict(rc.get("investment_scores") or c.get("investment_scores", {}))
                    if rc.get("name"):
                        c["name"] = rc["name"]
                    overlay_used = True
        else:
            print(f"[SKIP] Overlay {rescored_f.name} is older than base — not applying")

    companies = sorted(
        base_rows,
        key=lambda x: x.get("investment_scores", {}).get("overall_score", 0),
        reverse=True,
    )
    # Load margin history before scoring (needed by _compounder_list_score)
    if not _MARGIN_CACHE:
        syms_to_load = [c.get("symbol", "").upper() for c in base_rows if c.get("symbol")]
        _load_margin_history(syms_to_load)
    # Inject eps_growth from EODHD Highlights where stored metrics lack it
    _inject_eps_growth(companies)
    # Re-rank for dashboard default order: prefer scale + margin reliability over raw model peak.
    companies = sorted(companies, key=_compounder_list_score, reverse=True)
    company_lookup = {c["symbol"]: c for c in companies}
    sector_valuation_medians = build_sector_valuation_medians(companies)

    if overlay_used and base_label == "scaled":
        DATA_SOURCE = "scaled+rescored_scores"
    elif overlay_used and base_label == "final":
        DATA_SOURCE = "final+rescored_scores"
    else:
        DATA_SOURCE = base_label

    DATA_FILE = base_file
    DATA_OVERLAY_FILE = rescored_f if overlay_used and rescored_f else None

    print(
        f"[OK] Loaded {len(companies)} companies ({DATA_SOURCE}) "
        f"from {base_file.name if base_file else '?'}"
        + (f" + overlay {rescored_f.name}" if DATA_OVERLAY_FILE else "")
    )
    return True

def _score(c: dict) -> float:
    return c.get("investment_scores", {}).get("overall_score", 0.0)


def _clamp01(v: float) -> float:
    if v <= 0:
        return 0.0
    if v >= 1:
        return 1.0
    return v


def _format_usd_compact(usd: float | int | None) -> str:
    """Pretty-print USD with T / B / M / K suffix. Input is dollars (not pre-divided billions)."""
    try:
        x = float(usd if usd is not None else 0.0)
    except (TypeError, ValueError):
        return "$0"
    if not math.isfinite(x) or x == 0.0:
        return "$0"
    neg = x < 0
    a = abs(x)
    sign = "-" if neg else ""

    def pack(mag: float, suffix: str, decimals: int) -> str:
        t = f"{mag:.{decimals}f}"
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return f"{sign}${t}{suffix}"

    if a >= 1e12:
        return pack(a / 1e12, "T", 2)
    if a >= 1e9:
        return pack(a / 1e9, "B", 2)
    if a >= 1e6:
        return pack(a / 1e6, "M", 2)
    if a >= 1e3:
        return pack(a / 1e3, "K", 1)
    return f"{sign}${a:.0f}"


def _is_financial_like(c: dict) -> bool:
    sector = (c.get("sector") or "").strip().lower()
    industry = (c.get("industry") or "").strip().lower()
    if sector in {"financial services", "real estate"}:
        return True
    keywords = ("bank", "insurance", "reit", "capital markets", "asset management", "mortgage")
    return any(k in industry for k in keywords)


# ── Margin normalization (batch-loaded at startup) ────────────────────────────
_MARGIN_CACHE: dict[str, float] = {}  # sym -> ratio (current_margin / median_margin)


def _load_margin_history(symbols: list[str] | None = None) -> None:
    """Load margin ratios from pre-built index file (instant)."""
    global _MARGIN_CACHE
    index_file = PROJECT_ROOT / "outputs" / "margin_index.json"
    if index_file.is_file():
        try:
            _MARGIN_CACHE = json.loads(index_file.read_text(encoding="utf-8"))
            print(f"[OK] Margin index loaded: {len(_MARGIN_CACHE)} symbols")
            return
        except Exception:
            pass
    # Fallback: compute on-the-fly for requested symbols only
    cache_dir = PROJECT_ROOT / "outputs" / "fundamentals_cache"
    if not cache_dir.is_dir():
        return
    targets = symbols or []
    count = 0
    for sym in targets:
        if sym in _MARGIN_CACHE:
            continue
        cache_file = cache_dir / f"{sym}.json"
        if not cache_file.is_file():
            _MARGIN_CACHE[sym] = 0.0
            continue
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            _MARGIN_CACHE[sym] = 0.0
            continue
        annual = (data.get("Financials") or {}).get("Income_Statement", {}).get("yearly") or {}
        if len(annual) < 5:
            _MARGIN_CACHE[sym] = 0.0
            continue
        margins: list[float] = []
        for yr in sorted(annual.keys())[-15:]:
            inc = annual[yr]
            rev = float(inc.get("totalRevenue") or 0)
            ni = float(inc.get("netIncome") or 0)
            if rev > 0:
                margins.append(ni / rev)
        if len(margins) < 5:
            _MARGIN_CACHE[sym] = 0.0
            continue
        sorted_m = sorted(margins)
        median_m = sorted_m[len(sorted_m) // 2]
        current_m = margins[-1]
        if median_m <= 0.01:
            _MARGIN_CACHE[sym] = 0.0
            continue
        _MARGIN_CACHE[sym] = current_m / median_m
        count += 1
    if count:
        print(f"[OK] Margin history computed for {count} symbols (fallback)")


def _margin_cycle_ratio(sym: str) -> float:
    """Return current/median margin ratio for a symbol (0 if unknown)."""
    return _MARGIN_CACHE.get(sym, 0.0)


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
    # Penalize revenue shrinking over the long window even if one year bounced.
    if rev4 < 0 or rev3 < 0:
        blended *= 0.55
    elif rev_long < 0.03:
        blended *= 0.75
    return min(1.0, max(0.0, blended))


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
    if gap <= 0.22:
        return 0.90
    if gap <= 0.32:
        return 0.84
    return 0.78


def _compounder_list_score(c: dict) -> float:
    """Default dashboard rank (0–20): **value + safety** first, **growth** for 3y upside.

    Tuned for \"make money over ~3 years, don't blow up\": cheap vs fundamentals (PEG/P/E,
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
    # The growth score was computed from trailing metrics that are inflated by the cycle.
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

    # Stable growth premium: companies with consistent revenue growth get a growth boost;
    # volatile growers get dampened.
    _rc = m.get("revenue_growth_consistency")
    rev_consistency = float(_rc) if _rc is not None else 0.5
    if rev_consistency >= 0.75:
        g *= 1.10  # up to 10% growth credit for stable compounders
    elif rev_consistency < 0.3:
        g *= 0.80  # 20% haircut for wildly volatile revenue

    g_lt = _long_term_growth_factor(m, s)
    if _is_cyc_early and _mcr_early > 1.5:
        g_lt *= 0.55 if _mcr_early > 2.0 else 0.72
    # Blend rubric growth (0–5 → 0–1) with long-horizon CAGR track (revenue-led, 3y-weighted).
    g = min(1.0, 0.34 * g + 0.66 * max(g, g_lt))
    rev_long_for_g = _blended_revenue_cagr(m)
    earn_long_for_g = max(float(m.get("oeps_cagr") or 0.0), float(m.get("eps_growth") or 0.0))
    if rev_long_for_g < 0.12 and earn_long_for_g > 0.25:
        g = min(g, _cagr_to_unit(rev_long_for_g) + 0.10)

    # Weights: value ↑ safety ↑ for margin of safety; growth still material for 3y upside; quality via blend + confidence.
    base = (0.18 * q) + (0.24 * g) + (0.30 * sf) + (0.28 * v)
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
    # Revenue vs market cap: values far above ~20× are usually currency/unit bugs on ADRs,
    # not real economics — do not let them max out “scale” confidence (e.g. CCU-class rows).
    if not is_fin and rev_mcap_ratio > 0:
        if rev_mcap_ratio > 80.0:
            confidence *= 0.20
        elif rev_mcap_ratio > 40.0:
            confidence *= 0.42
        elif rev_mcap_ratio > 25.0:
            confidence *= 0.62
        elif rev_mcap_ratio > 18.0:
            confidence *= 0.78
    # ROE/ROIC stored as ratios should stay in [0, ~1.5]; higher is almost always a pipeline bug.
    if roe > 2.0 or roic > 2.0:
        confidence *= 0.35
    elif roe > 1.2 or roic > 1.2:
        confidence *= 0.55
    elif roe > 0.85 or roic > 0.85:
        confidence *= 0.72
    # Scale confidence: tiny names can 5x, but probabilities are much noisier.
    confidence *= 0.58 + 0.42 * _clamp01((mcap_b - 1.0) / 60.0)
    confidence *= 0.62 + 0.38 * _clamp01((rev_b - 0.2) / 20.0)
    confidence *= 0.70 + 0.30 * _clamp01((min_q - 12.0) / 56.0)

    # Profit durability.
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

    # Valuation sanity: do not heavily reward "too cheap" distress, avoid extreme expensive.
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

    # Accounting sanity and sector-aware exceptions.
    if not is_fin:
        if gm > 1.0 or gm < 0:
            confidence *= 0.56
        elif gm > 0.85:
            confidence *= 0.78
    if is_fin:
        # Gross margin / Altman are weak discriminators for many financial firms.
        # Keep them in raw metrics, but trim confidence unless the franchise is sizable.
        confidence *= 0.95
        if mcap_b < 10 or rev_b < 1.0:
            confidence *= 0.84
        elif mcap_b < 100:
            confidence *= 0.93
        if dte > 6:
            confidence *= 0.85
    if sector_l in {"energy", "basic materials"}:
        # Cyclical sectors can look stellar near cycle peaks; demand stronger durability.
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
        # Memory/storage is deeply cyclical — treat like energy/materials.
        if rev_cagr > 0.25:
            confidence *= 0.78
        if g > 0.85:
            confidence *= 0.85
    elif is_semiconductor:
        # Broader semis (logic, design): mildly cyclical but structural growth possible.
        if rev_cagr > 0.40:
            confidence *= 0.90

    # ── Margin normalization: detect cyclical peak earnings ──
    # If current net margin is far above the long-term median, the "growth" and
    # "quality" signals are inflated by cycle position, not durable improvement.
    is_cyclical_sector = sector_l in {"energy", "basic materials"} or is_memory_semi
    sym_upper = (c.get("symbol") or "").strip().upper()
    mcr = _margin_cycle_ratio(sym_upper)
    if mcr > 1.0:
        if is_cyclical_sector:
            # Aggressive penalty for known cyclicals at peak margins
            if mcr > 3.0:
                confidence *= 0.45
            elif mcr > 2.5:
                confidence *= 0.55
            elif mcr > 2.0:
                confidence *= 0.65
            elif mcr > 1.5:
                confidence *= 0.78
        else:
            # Mild penalty for non-cyclicals (could be genuine margin expansion)
            if mcr > 3.0:
                confidence *= 0.75
            elif mcr > 2.5:
                confidence *= 0.85
    if is_biotech and rev_b < 0.8 and (roe > 0.8 or roic > 0.8):
        confidence *= 0.78
    if rev_b < 0.15 and mcap_b < 0.8:
        confidence *= 0.72

    # Value penalty: expensive names shouldn't top the list unless quality/safety are exceptional.
    if v < 0.05:
        confidence *= 0.82
    elif v < 0.20:
        confidence *= 0.90
    elif v < 0.35:
        confidence *= 0.96

    # Cheap + calm balance sheet: small lift (matches \"pay less, sleep better\" 3y mandate).
    if v >= 0.34 and sf >= 0.34:
        confidence *= 1.035

    sym = (c.get("symbol") or "").strip().upper()
    if "-" in sym:
        sym_base, cls = sym.rsplit("-", 1)
        if cls in {"B", "C"} and f"{sym_base}-A" in company_lookup:
            confidence *= 0.93 if cls == "B" else 0.90
    elif sym.endswith("L") and sym[:-1] in company_lookup:
        # e.g., GOOGL/GOOG style duplicates: keep one but lower sibling crowding.
        confidence *= 0.96

    score = 20.0 * base * confidence
    score *= _per_share_growth_distortion_factor(m)
    # Growth floor: if growth < 2/5, the name isn't compounding — cap the score so it
    # can't outrank genuine growers purely on safety/scale.
    growth_raw = float(s.get("growth_score", 0.0) or 0.0)
    if growth_raw < 2.0:
        score = min(score, 9.0)
    elif growth_raw < 2.5:
        score = min(score, 10.5)
    return round(max(score, 0.0), 4)


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")


def _parse_symbol(raw: str) -> str | None:
    """Reject path tricks and garbage; allow BRK.B style tickers."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not _SYMBOL_RE.fullmatch(s):
        return None
    return s


def get_company(symbol: str) -> dict | None:
    ps = _parse_symbol(symbol)
    return company_lookup.get(ps) if ps else None


def _lynch_peg(pe_display: float, m: dict) -> dict[str, float | str] | None:
    """Classic PEG: P/E ÷ (earnings growth % as a whole number, e.g. 20 for 20% p.a.).

    Uses the same headline P/E as the rest of the page (highlights when available).
    Growth rate priority: trailing diluted EPS YoY → OEPS CAGR → revenue trend (proxy).
    """
    pe = float(pe_display or 0.0)
    if pe <= 0.0 or not math.isfinite(pe):
        return None

    candidates: list[tuple[str, float]] = []
    eg = float(m.get("eps_growth") or 0.0)
    if eg > 0.0:
        candidates.append(("Trailing EPS YoY", eg * 100.0))
    oc = float(m.get("oeps_cagr") or 0.0)
    if oc > 0.0:
        candidates.append(("OEPS CAGR (4y lookback)", oc * 100.0))
    rev = max(
        float(m.get("revenue_cagr_3y") or 0.0),
        float(m.get("revenue_cagr_4y") or 0.0),
        float(m.get("revenue_growth_1y") or 0.0),
    )
    if rev > 0.0:
        candidates.append(("Revenue growth (PEG proxy)", rev * 100.0))

    for basis, g_pct in candidates:
        if g_pct < 1.0:
            continue
        val = pe / g_pct
        if not math.isfinite(val) or val <= 0.0:
            continue
        return {"value": round(val, 2), "growth_pct": round(g_pct, 1), "basis": basis}
    return None


def _fold_search(s: str) -> str:
    """Lowercase ASCII-ish fold for substring search (handles many accents)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    return s.encode("ascii", "ignore").decode("ascii").lower()


def _fnum(x: object, default: float = 0.0) -> float:
    """Coerce JSON-ish values to float for stable numeric sorts."""
    if x is None:
        return default
    if isinstance(x, bool):
        return float(int(x))
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", ""))
    except (TypeError, ValueError):
        return default


def weighted_blend_score(
    c: dict, wq: int, wv: int, wg: int, ws: int, wa: int
) -> float:
    """Q·V·G·S (+ optional analyst) blend used for custom ranking (same scale as filter_sort)."""
    s = c.get("investment_scores", {})
    tw = wq + wv + wg + ws
    if tw == 0:
        base = 0.0
    else:
        base = (
            float(s.get("quality_score") or 0) * wq
            + float(s.get("value_score") or 0) * wv
            + float(s.get("growth_score") or 0) * wg
            + float(s.get("safety_score") or 0) * ws
        ) / tw * 5.0
    if wa > 0:
        ar = c.get("analyst_ratings") or {}
        r = float(ar.get("Rating") or ar.get("rating") or 0)
        if r > 0:
            base += ((r - 1) / 4) * wa * 0.4
    return float(base)


def filter_sort(sector=None, category=None, min_score=0.0,
                sort_by="listing_score", sort_order="desc",
                search="",
                wq=5, wv=5, wg=5, ws=5, wa=0) -> list[dict]:
    so = (sort_order or "desc").strip().lower()
    if so not in ("asc", "desc"):
        so = "desc"
    result = companies
    if sector:
        result = [c for c in result if (c.get("sector") or "").lower() == sector.lower()]
    if category:
        result = [c for c in result
                  if c.get("investment_scores", {}).get("investment_category", "").lower() == category.lower()]
    if min_score > 0:
        result = [c for c in result if _score(c) >= min_score]
    if search:
        q = _fold_search(search)
        result = [
            c
            for c in result
            if q in _fold_search(c.get("symbol", "")) or q in _fold_search(c.get("name", ""))
        ]

    def _growth_sort_key(c: dict) -> tuple[float, float]:
        """0–5 growth sub-score first, then max headline % drivers (matches table cues)."""
        s = c.get("investment_scores") or {}
        m = c.get("financial_metrics") or {}
        g = _fnum(s.get("growth_score"))
        roic_p = _fnum(s.get("roic_pct"))
        rr = _fnum(m.get("roic"))
        # Prefer fundamentals ROIC as decimal when present: investment_scores.roic_pct is
        # sometimes derived incorrectly from legacy rows (e.g. double ×100).
        if m.get("roic") is not None and abs(rr) > 1e-12:
            if abs(rr) <= 2.0:
                roic_p = rr * 100.0
            else:
                roic_p = rr
        rc = _fnum(s.get("revenue_cagr_3y_pct"))
        oe = _fnum(s.get("oeps_cagr_pct"))
        # Tie-break %s are hints only; uncapped bad rows (double-counted ROIC, FX slips)
        # should not reorder the whole table.
        def _clip_pct(x: float, lo: float = -150.0, hi: float = 120.0) -> float:
            if not math.isfinite(x):
                return 0.0
            return max(lo, min(hi, x))

        return (g, max(_clip_pct(roic_p), _clip_pct(rc), _clip_pct(oe)))

    def _pe_key(c: dict) -> float:
        ci = c.get("company_info") or {}
        m = c.get("financial_metrics") or {}
        raw = ci.get("pe_ratio")
        if raw in (None, ""):
            raw = m.get("pe_ratio")
        if raw in (None, ""):
            return 9999.0
        return _fnum(raw, 9999.0)

    def _peg_key(c: dict) -> float:
        raw = (c.get("investment_scores") or {}).get("peg_ratio")
        if raw in (None, ""):
            return 999.0
        return _fnum(raw, 999.0)

    key_map = {
        "overall_score":  lambda c: _fnum(_score(c)),
        "listing_score":  lambda c: _compounder_list_score(c),
        "custom_score":   lambda c: weighted_blend_score(c, wq, wv, wg, ws, wa),
        "quality_score":  lambda c: _fnum((c.get("investment_scores") or {}).get("quality_score")),
        "value_score":    lambda c: _fnum((c.get("investment_scores") or {}).get("value_score")),
        "growth_score":   _growth_sort_key,
        "safety_score":   lambda c: _fnum((c.get("investment_scores") or {}).get("safety_score")),
        "tenx_score":     lambda c: _fnum((c.get("investment_scores") or {}).get("tenx_score")),
        "revenue":        lambda c: _fnum((c.get("financial_metrics") or {}).get("revenue")),
        "market_cap":     lambda c: _fnum((c.get("company_info") or {}).get("market_cap")),
        "roic":           lambda c: _fnum((c.get("financial_metrics") or {}).get("roic")),
        "roe":            lambda c: _fnum((c.get("financial_metrics") or {}).get("roe")),
        "pe_ratio":       _pe_key,
        "symbol":         lambda c: c.get("symbol", ""),
        "peg_ratio":      _peg_key,
        "oeps_cagr":      lambda c: _fnum((c.get("investment_scores") or {}).get("oeps_cagr_pct")),
        "revenue_cagr":   lambda c: _fnum((c.get("investment_scores") or {}).get("revenue_cagr_3y_pct")),
        "analyst":        lambda c: _fnum(
            (c.get("analyst_ratings") or {}).get("Rating")
            or (c.get("analyst_ratings") or {}).get("rating"),
        ),
    }
    key_fn = key_map.get(sort_by, key_map["listing_score"])
    result = sorted(result, key=key_fn, reverse=(so == "desc"))
    return result

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index_fixed.html')

@app.route('/api/summary')
def api_summary():
    if not companies:
        return jsonify({"error": "No data loaded"}), 503

    cats: dict = {}
    sectors_count: dict = {}
    total_score = total_rev = total_mcap = 0.0
    top_growth_score = 0.0

    for c in companies:
        s = c.get("investment_scores", {})
        cat = s.get("investment_category") or "UNKNOWN"
        cats[cat] = cats.get(cat, 0) + 1
        sec = c.get("sector") or "Unknown"
        sectors_count[sec] = sectors_count.get(sec, 0) + 1
        total_score += s.get("overall_score", 0)
        total_rev   += c.get("financial_metrics", {}).get("revenue", 0)
        total_mcap  += c.get("company_info", {}).get("market_cap", 0)
        top_growth_score = max(top_growth_score, s.get("growth_score", 0))

    n = len(companies)
    # Top company by growth score
    top_growth = max(companies, key=lambda c: c.get("investment_scores", {}).get("growth_score", 0))
    top_overall = companies[0] if companies else {}

    def _iso_mtime(p: Path | None) -> str | None:
        if not p or not p.is_file():
            return None
        try:
            return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            return None

    return jsonify({
        "total_companies": n,
        "data_source": DATA_SOURCE,
        "data_universe_file": DATA_FILE.name if DATA_FILE else None,
        "data_universe_modified": _iso_mtime(DATA_FILE),
        "data_rescored_overlay_file": DATA_OVERLAY_FILE.name if DATA_OVERLAY_FILE else None,
        "data_rescored_overlay_modified": _iso_mtime(DATA_OVERLAY_FILE),
        "average_score": round(total_score / n, 2),
        "total_revenue_b": round(total_rev / 1e9, 1),
        "total_revenue_fmt": _format_usd_compact(total_rev),
        "total_market_cap_t": round(total_mcap / 1e12, 2),
        "total_market_cap_fmt": _format_usd_compact(total_mcap),
        "investment_categories": cats,
        "sectors": sectors_count,
        "top_overall": {
            "symbol": top_overall.get("symbol"),
            "score": _score(top_overall),
            "listing_score": round(_compounder_list_score(top_overall), 2) if top_overall else 0.0,
        },
        "top_growth": {
            "symbol": top_growth.get("symbol"),
            "growth_score": top_growth.get("investment_scores", {}).get("growth_score", 0),
            "oeps_cagr_pct": top_growth.get("investment_scores", {}).get("oeps_cagr_pct", 0),
            "roic_pct": top_growth.get("investment_scores", {}).get("roic_pct", 0),
        },
        "dashboard_refreshed_at": datetime.now().isoformat(timespec="seconds"),
    })

@app.route('/api/companies')
def api_companies():
    sector     = request.args.get('sector')
    category   = request.args.get('category')
    min_score  = float(request.args.get('min_score', 0))
    limit      = min(int(request.args.get('limit', 50)), 200)
    offset     = int(request.args.get('offset', 0))
    sort_by    = request.args.get('sort_by', 'listing_score')
    sort_order = request.args.get('sort_order', 'desc')
    search     = request.args.get('search', '').strip()

    def _wi(name: str, default: int) -> int:
        try:
            return max(0, min(10, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    wq = _wi("wq", 5)
    wv = _wi("wv", 5)
    wg = _wi("wg", 5)
    ws = _wi("ws", 5)
    wa = _wi("wa", 0)
    weight_custom = request.args.get("wc") == "1"
    sliders_nondefault = any([wq != 5, wv != 5, wg != 5, ws != 5, wa != 0])
    use_custom = weight_custom or sliders_nondefault
    # Weighted blend only replaces the two composite "model" sorts; metric columns sort literally.
    blend_sorts = frozenset({"listing_score", "overall_score"})
    effective_sort = "custom_score" if use_custom and sort_by in blend_sorts else sort_by
    filtered = filter_sort(sector, category, min_score, effective_sort, sort_order, search, wq, wv, wg, ws, wa)
    total    = len(filtered)
    page     = filtered[offset: offset + limit]

    def fmt(c):
        s  = c.get("investment_scores", {})
        m  = c.get("financial_metrics", {})
        ci = c.get("company_info", {})
        return {
            "symbol":        c["symbol"],
            "name":          c.get("name", c["symbol"]),
            "sector":        c.get("sector", "Unknown"),
            "overall_score": s.get("overall_score", 0),
            "listing_score": _compounder_list_score(c),
            "custom_score":  round(weighted_blend_score(c, wq, wv, wg, ws, wa), 4),
            "quality_score": s.get("quality_score", 0),
            "value_score":   s.get("value_score", 0),
            "growth_score":  s.get("growth_score", 0),
            "safety_score":  s.get("safety_score", 0),
            "category":      s.get("investment_category", "UNKNOWN"),
            "oeps_cagr_pct": s.get("oeps_cagr_pct", 0),
            "roic_pct":      s.get("roic_pct", m.get("roic", 0) * 100),
            "revenue_cagr_3y_pct": s.get("revenue_cagr_3y_pct", 0),
            "gross_margin_pct": s.get("gross_margin_pct", m.get("gross_margin", 0) * 100),
            "gross_margin_expansion_pp": s.get("gross_margin_expansion_pp", 0),
            "revenue_acceleration_pct":  s.get("revenue_acceleration_pct", 0),
            "peg_ratio":     s.get("peg_ratio", m.get("peg_ratio", 0)),
            "tenx_score":    s.get("tenx_score", 0),
            "piotroski":     m.get("piotroski_score", 0),
            "altman_z":      round(m.get("altman_z_score", 0), 1),
            "current_ratio": round(m.get("current_ratio", 0), 2),
            "debt_to_equity":round(m.get("debt_to_equity", 0), 2),
            "fcf_conversion":round(m.get("fcf_conversion", 0), 2),
            "fcf_yield_pct": round(m.get("fcf_yield", 0) * 100, 1),
            "pb_ratio":      round(m.get("pb_ratio", 0), 2),
            "revenue_b":     round(m.get("revenue", 0) / 1e9, 2),
            "revenue_fmt":   _format_usd_compact(m.get("revenue", 0)),
            "roe_pct":       round(m.get("roe", 0) * 100, 1),
            "pe_ratio":      ci.get("pe_ratio") or m.get("pe_ratio", 0),
            "market_cap_b":  round(ci.get("market_cap", 0) / 1e9, 2),
            "market_cap_fmt": _format_usd_compact(ci.get("market_cap", 0)),
            "data_quality":  c.get("data_quality", {}).get("quality", "N/A"),
            "analyst_ratings": _fmt_analyst(c.get("analyst_ratings", {})),
            # Factor columns
            "rev_growth_1y_pct":  round(m.get("revenue_growth_1y", 0) * 100, 1),
            "earnings_growth_1y_pct": round(m.get("eps_growth", 0) * 100, 1),
            "rev_growth_5y_pct":  round(m.get("revenue_cagr_4y", 0) * 100, 1),
            "fcf_ttm_fmt":        _format_usd_compact(m.get("free_cash_flow", 0)),
        }

    companies_out: list[dict] = []
    for i, c in enumerate(page):
        row = fmt(c)
        row["metric_tones"] = row_tones(c, sector_valuation_medians)
        row["rank"] = offset + i + 1
        companies_out.append(row)

    return jsonify({
        "companies": companies_out,
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "has_more": (offset + limit) < total,
        "effective_sort": effective_sort,
        "sort_by": sort_by,
        "use_custom_weights": use_custom,
    })

def _fmt_analyst(ar: dict) -> dict | None:
    if not ar:
        return None
    r = ar.get("Rating") or ar.get("rating")
    if not r:
        return None
    strong_buy = int(ar.get("StrongBuy") or ar.get("strong_buy") or 0)
    buy = int(ar.get("Buy") or ar.get("buy") or 0)
    hold = int(ar.get("Hold") or ar.get("hold") or 0)
    sell = int(ar.get("Sell") or ar.get("sell") or 0)
    strong_sell = int(ar.get("StrongSell") or ar.get("strong_sell") or 0)
    rr = float(r)
    if rr >= 4.5:
        detail = "Strong Buy"
    elif rr >= 3.5:
        detail = "Buy"
    elif rr >= 2.5:
        detail = "Hold"
    elif rr >= 1.5:
        detail = "Sell"
    else:
        detail = "Strong Sell"
    return {
        "rating":      round(rr, 2),
        "target_price": float(ar.get("TargetPrice") or ar.get("target_price") or 0),
        "strong_buy":  strong_buy,
        "buy":         buy,
        "hold":        hold,
        "sell":        sell,
        "strong_sell": strong_sell,
        "total_analysts": strong_buy + buy + hold + sell + strong_sell,
        "rating_detail": detail,
    }


_CACHE_DIR  = PROJECT_ROOT / "outputs" / "fundamentals_cache"
_CACHE_TTL  = 24 * 3600   # seconds


def _read_fundamentals_cache_file(sym: str) -> dict | None:
    """Load sym.json from disk; None if missing or invalid JSON."""
    cache_file = _CACHE_DIR / f"{sym}.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _safe_float(x, default: float = 0.0) -> float:
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", ""))
    except (TypeError, ValueError):
        return default


# Top-level fields some EODHD envelopes expose instead of nested Highlights.
_HIGHLIGHTS_MERGE_KEYS = (
    "EarningsShare",
    "DilutedEpsTTM",
    "PERatio",
    "PEGRatio",
    "MarketCapitalization",
    "WallStreetTargetPrice",
    "QuarterlyEarningsGrowthYOY",
    "Beta",
    "DividendYield",
)


def _merged_highlights(d: dict) -> dict:
    """Merge flattened EODHD highlight metrics into a Highlights-shaped dict."""
    if not isinstance(d, dict):
        return {}
    base = dict(d.get("Highlights") or {})
    for k in _HIGHLIGHTS_MERGE_KEYS:
        top = d.get(k)
        if top is None or top == "":
            continue
        cur = base.get(k)
        if cur is None or cur == "" or cur == 0:
            base[k] = top
    return base


def _eodhd_adjust_gross_profit(rev: float, gp: float, cor: float) -> float:
    """Fix EODHD rows where grossProfit == revenue but costOfRevenue exists (e.g. DUOL 2021)."""
    if rev > 0 and cor > 0 and gp >= rev * 0.999:
        return rev - cor
    return gp


def _q_period_has_diluted_eps(row: dict) -> bool:
    v = row.get("dilutedEPS")
    if v is None:
        return False
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("", "none", "n/a", "nan"):
            return False
    return True


def _get_fundamentals(symbol: str) -> dict | None:
    """Return fundamentals: fresh cache, else live EODHD, else stale cache."""
    ps = _parse_symbol(symbol)
    if not ps:
        return None
    sym = ps
    cache_file = _CACHE_DIR / f"{sym}.json"
    now = time.time()

    if cache_file.is_file() and (now - cache_file.stat().st_mtime) < _CACHE_TTL:
        hit = _read_fundamentals_cache_file(sym)
        if hit:
            return hit

    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    if api_key:
        try:
            r = _req.get(
                f"https://eodhd.com/api/fundamentals/{sym}.US",
                params={"api_token": api_key, "fmt": "json"}, timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            if data and isinstance(data, dict):
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                try:
                    cache_file.write_text(
                        json.dumps(data, separators=(",", ":")), encoding="utf-8"
                    )
                except Exception:
                    pass
                return data
        except Exception:
            pass

    # Offline / no key / network error: use stale cache if present
    return _read_fundamentals_cache_file(sym)


def _empty_history_payload(message: str) -> dict:
    return {
        "history":         [],
        "analyst_ratings": None,
        "price":           0.0,
        "eps_ttm":         0.0,
        "pe_ttm":          0.0,
        "market_cap_b":    0.0,
        "market_cap_usd":  0.0,
        "market_cap_fmt":  "$0",
        "partial":         True,
        "message":         message,
    }


_price_store = PriceStore(PROJECT_ROOT / "outputs" / "fundamentals.db")


def _parse_eodhd_prices(data: list) -> list:
    """Convert raw EODHD EOD response to split-adjusted OHLCV dicts."""
    prices = []
    for p in data:
        if not isinstance(p, dict) or "close" not in p:
            continue
        raw_c = float(p["close"])
        adj_c = float(p.get("adjusted_close") or raw_c)
        ratio = adj_c / raw_c if raw_c > 0 else 1.0
        prices.append({
            "date": p["date"],
            "close": round(adj_c, 4),
            "open":  round(float(p.get("open", raw_c)) * ratio, 4),
            "high":  round(float(p.get("high", raw_c)) * ratio, 4),
            "low":   round(float(p.get("low", raw_c)) * ratio, 4),
            "volume": p.get("volume", 0),
        })
    return prices


def _fetch_full_price_history(symbol: str) -> list:
    """Get full price history: memory -> SQLite -> EODHD (incremental)."""
    from datetime import timedelta
    existing = _price_store.get(symbol)
    last_date = _price_store.get_last_date(symbol)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if existing and last_date and last_date >= today_str:
        return existing

    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    if not api_key:
        return existing

    try:
        if existing and last_date:
            start_str = last_date
        else:
            start_str = (datetime.now() - timedelta(days=365 * 25)).strftime("%Y-%m-%d")

        resp = _req.get(
            f"https://eodhd.com/api/eod/{symbol}.US",
            params={
                "api_token": api_key, "fmt": "json",
                "from": start_str,
                "to": today_str,
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return existing

        new_prices = _parse_eodhd_prices(resp.json())
        if existing and last_date:
            return _price_store.append(symbol, new_prices)
        else:
            _price_store.put(symbol, new_prices)
            return new_prices
    except Exception:
        return existing


def _slice_and_downsample(prices: list, rng: str) -> list:
    """Slice full history to the requested range, downsample if needed."""
    from datetime import timedelta
    if not prices:
        return []
    now = datetime.now()
    # How many calendar days back each range needs
    range_days = {
        "1d": 7, "1w": 18, "1m": 45, "3m": 100,
        "6m": 190, "1y": 370, "3y": 1100,
        "5y": 1830, "10y": 3660, "max": 999999,
    }
    if rng == "ytd":
        cutoff = datetime(now.year, 1, 1).strftime("%Y-%m-%d")
    elif rng == "max":
        cutoff = "1900-01-01"
    else:
        days = range_days.get(rng, 370)
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    sliced = [p for p in prices if p["date"] >= cutoff]
    if not sliced:
        return []

    # Downsample: keep at most ~500 points for smooth rendering
    max_pts = 500
    if len(sliced) <= max_pts:
        return sliced
    step = len(sliced) / max_pts
    sampled = []
    i = 0.0
    while int(i) < len(sliced) - 1:
        sampled.append(sliced[int(i)])
        i += step
    sampled.append(sliced[-1])  # always include latest
    return sampled


@app.route('/api/company/<symbol>/price-history')
def api_company_price_history(symbol):
    """Serve price history from EODHD EOD endpoint with configurable range."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    rng = request.args.get("range", "1y").lower()
    try:
        all_prices = _fetch_full_price_history(symbol)
        if not all_prices:
            return jsonify({"error": "No price data", "prices": []}), 200
        prices = _slice_and_downsample(all_prices, rng)
        return jsonify({"prices": prices})
    except Exception as ex:
        return jsonify({"error": str(ex)[:200], "prices": []}), 200


def _build_ttm_window(
    q_inc: dict,
    q_cf: dict,
    shares_stats: dict,
    shares_out: float,
    price_data: list,
    *,
    trailing_years: int = 1,
    highlights: dict | None = None,
) -> dict | None:
    """Sum income/cash-flow periods into a trailing 1Y or 2Y window."""
    q_all_inc = sorted(q_inc.keys(), reverse=True)
    n1 = ttm_flow_period_count(q_all_inc)
    n_need = n1 * max(1, int(trailing_years))
    if len(q_all_inc) < n_need:
        return None

    q_keys_inc = select_ttm_period_keys(q_all_inc, trailing_years=trailing_years)
    q_keys_cf = [k for k in q_keys_inc if k in q_cf]
    if len(q_keys_cf) < len(q_keys_inc):
        q_keys_cf = sorted(q_cf.keys(), reverse=True)[: len(q_keys_inc)]

    rev = sum(_safe_float(q_inc[k].get("totalRevenue")) for k in q_keys_inc)
    ni = sum(_safe_float(q_inc[k].get("netIncome")) for k in q_keys_inc)
    gp = sum(
        _eodhd_adjust_gross_profit(
            _safe_float(q_inc[k].get("totalRevenue")),
            _safe_float(q_inc[k].get("grossProfit")),
            _safe_float(q_inc[k].get("costOfRevenue")),
        )
        for k in q_keys_inc
    )
    ocf = (
        sum(_safe_float(q_cf.get(k, {}).get("totalCashFromOperatingActivities")) for k in q_keys_cf)
        if q_keys_cf
        else 0
    )
    capex = (
        sum(abs(_safe_float(q_cf.get(k, {}).get("capitalExpenditures"))) for k in q_keys_cf)
        if q_keys_cf
        else 0
    )
    sbc = (
        sum(_safe_float(q_cf.get(k, {}).get("stockBasedCompensation")) for k in q_keys_cf)
        if q_keys_cf
        else 0
    )
    sh = _safe_float(shares_stats.get("SharesOutstanding")) or shares_out
    ty = max(1, int(trailing_years))
    eps_from_quarters = sum(_safe_float(q_inc[k].get("dilutedEPS")) for k in q_keys_inc)
    n_periods = len(q_keys_inc)
    quarters_with_eps = sum(1 for k in q_keys_inc if _q_period_has_diluted_eps(q_inc[k]))
    eps_complete = quarters_with_eps == n_periods and eps_from_quarters > 0
    hl_eps = 0.0
    if highlights:
        hl_eps = _safe_float(highlights.get("DilutedEpsTTM")) or _safe_float(highlights.get("EarningsShare"))
    if eps_complete:
        eps_cum = eps_from_quarters
    elif ty == 1 and hl_eps > 0:
        eps_cum = hl_eps
        ni = hl_eps * sh
    elif sh:
        eps_cum = ni / sh
    else:
        eps_cum = 0.0
    eps = eps_cum / ty if ty > 1 else eps_cum
    fcf = ocf - capex
    oe = ocf - capex - sbc
    oeps_cum = oe / sh if sh else 0
    oeps = oeps_cum / ty if ty > 1 else oeps_cum
    rev_cmp = rev / ty
    ni_cmp = ni / ty
    ocf_cmp = ocf / ty
    capex_cmp = capex / ty
    fcf_cmp = fcf / ty
    current_price = price_data[-1]["close"] if price_data else 0
    pe = round(current_price / eps, 1) if eps > 0 and current_price > 0 else None
    period_end = q_keys_inc[0] if q_keys_inc else None
    try:
        fiscal_year = int(str(period_end)[:4]) if period_end else None
    except (TypeError, ValueError):
        fiscal_year = None
    cadence = ttm_cadence_label(n1)
    return {
        "year": ttm_display_label(cadence, trailing_years),
        "cadence": cadence,
        "trailing_years": trailing_years,
        "periods_used": len(q_keys_inc),
        "period_ends": q_keys_inc,
        "fiscal_year": fiscal_year,
        "period_end": period_end,
        "revenue_usd": rev_cmp,
        "revenue_b": round(rev_cmp / 1e9, 2),
        "revenue_usd_total": rev,
        "revenue_b_total": round(rev / 1e9, 2),
        "net_income_usd": ni_cmp,
        "net_income_b": round(ni_cmp / 1e9, 2),
        "net_income_usd_total": ni,
        "net_income_b_total": round(ni / 1e9, 2),
        "ocf_usd": ocf_cmp,
        "ocf_b": round(ocf_cmp / 1e9, 2),
        "ocf_usd_total": ocf,
        "ocf_b_total": round(ocf / 1e9, 2),
        "capex_usd": capex_cmp,
        "capex_b": round(capex_cmp / 1e9, 2),
        "capex_usd_total": capex,
        "capex_b_total": round(capex / 1e9, 2),
        "fcf_usd": fcf_cmp,
        "fcf_b": round(fcf_cmp / 1e9, 2),
        "fcf_usd_total": fcf,
        "fcf_b_total": round(fcf / 1e9, 2),
        "owner_earnings_usd": oe / ty if ty > 1 else oe,
        "owner_earnings_b": round((oe / ty if ty > 1 else oe) / 1e9, 2),
        "eps": round(eps, 4),
        "oeps": round(oeps, 4),
        "gross_margin_pct": round(gp / rev * 100, 1) if rev else 0,
        "net_margin_pct": round(ni / rev * 100, 1) if rev else 0,
        "pe_ratio": pe,
        "ye_price": round(current_price, 2) if current_price else None,
    }


@app.route('/api/company/<symbol>/history')
def api_company_history(symbol):
    """Serve historical annual financials + analyst data (cache-first)."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    try:
        d = _get_fundamentals(symbol)
        if not d:
            return jsonify(_empty_history_payload(
                "No fundamentals on disk and EODHD unavailable — charts skipped."
            ))
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    # Annual income
    annual = d.get("Financials", {}).get("Income_Statement", {}).get("yearly", {})
    bs_ann = d.get("Financials", {}).get("Balance_Sheet", {}).get("yearly", {})
    cf_ann = d.get("Financials", {}).get("Cash_Flow", {}).get("yearly", {})
    shares_stats = d.get("SharesStats", {})
    shares_out   = _safe_float(shares_stats.get("SharesOutstanding")) or 1.0

    history = []
    for yr in sorted(annual.keys(), reverse=True)[:15]:
        inc = annual[yr]
        bs  = bs_ann.get(yr, {})
        cf  = cf_ann.get(yr, {})
        rev  = _safe_float(inc.get("totalRevenue"))
        ni   = _safe_float(inc.get("netIncome"))
        op   = _safe_float(inc.get("operatingIncome") or inc.get("ebit"))
        ocf  = _safe_float(cf.get("totalCashFromOperatingActivities"))
        capex = abs(_safe_float(cf.get("capitalExpenditures")))
        sbc  = _safe_float(cf.get("stockBasedCompensation"))
        eq   = _safe_float(bs.get("totalStockholderEquity")) or 1.0
        # Prefer period diluted/weighted shares from statements; fall back to Highlights.
        sh = _safe_float(bs.get("commonStockSharesOutstanding"))
        if not sh:
            sh = _safe_float(
                inc.get("weightedAverageShsOutDil")
                or inc.get("weightedAverageShsOut")
            )
        if not sh:
            sh = shares_out or 1.0
        eps  = ni / sh if sh else 0.0
        fcf  = ocf - capex
        oe   = ocf - capex - sbc
        oeps = oe / sh if sh else 0.0
        cor = _safe_float(inc.get("costOfRevenue"))
        gp = _safe_float(inc.get("grossProfit"))
        # EODHD sometimes sets grossProfit == totalRevenue while costOfRevenue is non-zero (DUOL 2021).
        if rev > 0 and cor > 0 and gp >= rev * 0.999:
            gp = rev - cor
        history.append({
            "year":      yr[:4],
            "revenue_usd":    rev,
            "revenue_b":      round(rev / 1e9, 2),
            "net_income_usd": ni,
            "net_income_b":   round(ni / 1e9, 2),
            "op_income_usd":  op,
            "op_income_b":    round(op / 1e9, 2),
            "ocf_usd":        ocf,
            "ocf_b":          round(ocf / 1e9, 2),
            "capex_usd":      capex,
            "capex_b":        round(capex / 1e9, 2),
            "fcf_usd":        fcf,
            "fcf_b":          round(fcf / 1e9, 2),
            "owner_earnings_usd": oe,
            "owner_earnings_b":   round(oe / 1e9, 2),
            "eps":          round(eps, 4),
            "oeps":         round(oeps, 4),
            "roe_pct":      round(ni / eq * 100, 1) if eq else 0,
            "gross_margin_pct": round(gp / rev * 100, 1) if rev else 0,
            "net_margin_pct": round(ni / rev * 100, 1) if rev else 0,
        })

    # ── Historical P/E: join year-end prices with annual EPS ──
    price_data = _fetch_full_price_history(symbol)
    price_by_date = {p["date"]: p["close"] for p in price_data} if price_data else {}
    for entry in history:
        yr = entry["year"]
        eps_val = entry.get("eps", 0)
        ye_price = None
        # Find closest trading day to fiscal year end (try Dec 31 backwards)
        for d_offset in range(0, 10):
            from datetime import timedelta as _td
            try_date = (datetime(int(yr), 12, 31) - _td(days=d_offset)).strftime("%Y-%m-%d")
            if try_date in price_by_date:
                ye_price = price_by_date[try_date]
                break
        if ye_price and eps_val and eps_val > 0:
            entry["pe_ratio"] = round(ye_price / eps_val, 1)
            entry["ye_price"] = round(ye_price, 2)
        else:
            entry["pe_ratio"] = None
            entry["ye_price"] = ye_price

    q_inc = d.get("Financials", {}).get("Income_Statement", {}).get("quarterly", {})
    q_cf = d.get("Financials", {}).get("Cash_Flow", {}).get("quarterly", {})
    _hl = _merged_highlights(d)
    ttm = _build_ttm_window(
        q_inc, q_cf, shares_stats, shares_out, price_data, trailing_years=1, highlights=_hl
    )
    ttm2 = _build_ttm_window(
        q_inc, q_cf, shares_stats, shares_out, price_data, trailing_years=2, highlights=_hl
    )

    # ── Analyst estimates from Earnings.Trend ──
    estimates = []
    trend = d.get("Earnings", {}).get("Trend", {})
    now_year = datetime.now().year
    seen_est_years = set()
    for date_key in sorted(trend.keys(), reverse=True):
        t = trend[date_key]
        if not isinstance(t, dict):
            continue
        period_type = t.get("period", "")
        if "y" not in period_type:
            continue
        # date_key is like "2027-06-30" — extract the fiscal year
        try:
            fy_year = int(date_key[:4])
        except (ValueError, TypeError):
            continue
        if fy_year < now_year or fy_year in seen_est_years:
            continue
        seen_est_years.add(fy_year)
        eps_est = _safe_float(t.get("earningsEstimateAvg"))
        rev_est = _safe_float(t.get("revenueEstimateAvg"))
        if eps_est or rev_est:
            sh_est = _safe_float(shares_stats.get("SharesOutstanding")) or shares_out
            ni_est = (eps_est * sh_est) if (eps_est and sh_est) else None
            est_entry = {
                "year": f"FY{fy_year}E",
                "fiscal_year": fy_year,
                "eps": round(eps_est, 4) if eps_est else None,
                "revenue_usd": rev_est,
                "revenue_b": round(rev_est / 1e9, 2) if rev_est else None,
                "net_income_usd": ni_est,
                "net_income_b": round(ni_est / 1e9, 2) if ni_est else None,
            }
            if eps_est and eps_est > 0 and price_data:
                est_entry["pe_ratio"] = round(price_data[-1]["close"] / eps_est, 1)
            estimates.append(est_entry)
    estimates.sort(key=lambda e: e["year"])

    analyst = _fmt_analyst(d.get("AnalystRatings", {}))
    h = d.get("Highlights", {})
    if not history:
        return jsonify({
            **_empty_history_payload(
                "Fundamentals file has no annual income statement — charts skipped."
            ),
            "analyst_ratings": analyst,
            "price":           _safe_float(h.get("WallStreetTargetPrice")),
            "eps_ttm":         _safe_float(h.get("EarningsShare")),
            "pe_ttm":          _safe_float(h.get("PERatio")),
            "market_cap_b":    round(_safe_float(h.get("MarketCapitalization")) / 1e9, 2),
            "market_cap_usd":  _safe_float(h.get("MarketCapitalization")),
            "market_cap_fmt":  _format_usd_compact(_safe_float(h.get("MarketCapitalization"))),
        })

    mcap_usd = _safe_float(h.get("MarketCapitalization"))
    return jsonify({
        "history":         history,
        "ttm":             ttm,
        "ttm2":            ttm2,
        "estimates":       estimates,
        "analyst_ratings": analyst,
        "price":           _safe_float(h.get("WallStreetTargetPrice")),
        "eps_ttm":         _safe_float(h.get("EarningsShare")),
        "pe_ttm":          _safe_float(h.get("PERatio")),
        "market_cap_b":    round(mcap_usd / 1e9, 2) if mcap_usd else 0.0,
        "market_cap_usd":  mcap_usd,
        "market_cap_fmt":  _format_usd_compact(mcap_usd),
        "partial":         False,
    })


@app.route('/api/company/<symbol>')
def api_company(symbol):
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    c = get_company(symbol)
    if not c:
        return jsonify({"error": "Company not found"}), 404

    m  = c.get("financial_metrics", {})
    ci = c.get("company_info", {})
    s  = c.get("investment_scores", {})
    pe_disp = float(ci.get("pe_ratio") or m.get("pe_ratio") or 0)
    lynch_peg = _lynch_peg(pe_disp, m)

    return jsonify({
        "symbol":   c["symbol"],
        "name":     c.get("name", c["symbol"]),
        "sector":   c.get("sector", "Unknown"),
        "industry": c.get("industry", "Unknown"),
        "exchange": c.get("exchange", "US"),
        "description": ci.get("description", ""),
        "investment_scores": s,
        "financial_metrics": {
            "revenue_b":        round(m.get("revenue", 0) / 1e9, 2),
            "revenue_fmt":      _format_usd_compact(m.get("revenue", 0)),
            "net_income_b":     round(m.get("net_income", 0) / 1e9, 2),
            "net_income_fmt":   _format_usd_compact(m.get("net_income", 0)),
            "owner_earnings_b": round(m.get("owner_earnings", 0) / 1e9, 3),
            "owner_earnings_fmt": _format_usd_compact(m.get("owner_earnings", 0)),
            "oeps":             round(m.get("owner_earnings_per_share", 0), 4),
            "oeps_cagr_pct":    round(m.get("oeps_cagr", 0) * 100, 2),
            "roe_pct":          round(m.get("roe", 0) * 100, 1),
            "roic_pct":         round(m.get("roic", 0) * 100, 1),
            "roa_pct":          round(m.get("roa", 0) * 100, 1),
            "gross_margin_pct": round(m.get("gross_margin", 0) * 100, 1),
            "net_margin_pct":   round(m.get("net_margin", 0) * 100, 1),
            "pe_ratio":         ci.get("pe_ratio") or m.get("pe_ratio", 0),
            "lynch_peg":        lynch_peg,
            "pb_ratio":         round(m.get("pb_ratio", 0), 2),
            "ps_ratio":         round(m.get("ps_ratio", 0), 2),
            "ev_ebitda":        round(m.get("ev_ebitda", 0), 1),
            "debt_to_equity":   round(m.get("debt_to_equity", 0), 2),
            "current_ratio":    round(m.get("current_ratio", 0), 2),
            "revenue_growth_1y_pct": round(m.get("revenue_growth_1y", 0) * 100, 1),
            "revenue_cagr_3y_pct":   round(m.get("revenue_cagr_3y", m.get("revenue_cagr_4y", 0)) * 100, 1),
            "piotroski_score":  m.get("piotroski_score", 0),
            "altman_z_score":   round(m.get("altman_z_score", 0), 2),
            "red_flags":        m.get("red_flags", []),
        },
        "company_info": {
            "market_cap_b": round(ci.get("market_cap", 0) / 1e9, 2),
            "market_cap_fmt": _format_usd_compact(ci.get("market_cap", 0)),
            "pe_ratio":     ci.get("pe_ratio", 0),
        },
        "data_quality": c.get("data_quality", {}),
        "analyst_ratings": _fmt_analyst(c.get("analyst_ratings", {})),
    })


def _chat_stock_context_tiny(c: dict) -> dict:
    """Minimal ticker context for the LLM (full EODHD via tool only)."""
    m = c.get("financial_metrics", {})
    ci = c.get("company_info", {})
    s = c.get("investment_scores", {})
    sym = c["symbol"]
    rf = m.get("red_flags") or []
    if isinstance(rf, list):
        rf = rf[:5]
    desc = (ci.get("description") or "")[:400]
    return {
        "ticker": sym,
        "name": c.get("name", sym),
        "sector": c.get("sector"),
        "category": s.get("investment_category"),
        "overall_score": s.get("overall_score"),
        "qvgs": {
            "quality": s.get("quality_score"),
            "value": s.get("value_score"),
            "growth": s.get("growth_score"),
            "safety": s.get("safety_score"),
        },
        "metrics": {
            "revenue_b": round(m.get("revenue", 0) / 1e9, 2),
            "revenue_fmt": _format_usd_compact(m.get("revenue", 0)),
            "net_income_b": round(m.get("net_income", 0) / 1e9, 2),
            "net_income_fmt": _format_usd_compact(m.get("net_income", 0)),
            "pe": ci.get("pe_ratio") or m.get("pe_ratio"),
            "market_cap_b": round(ci.get("market_cap", 0) / 1e9, 2),
            "market_cap_fmt": _format_usd_compact(ci.get("market_cap", 0)),
            "roe_pct": round(m.get("roe", 0) * 100, 1),
            "roic_pct": round(m.get("roic", 0) * 100, 1),
        },
        "red_flags_sample": rf,
        "data_quality": (c.get("data_quality") or {}).get("quality"),
        "description_excerpt": desc,
    }


_CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web (DuckDuckGo) for headlines and snippets; results include titles and URLs but **not** "
                "full page text. To read a specific article the user pasted or from search results, call "
                "`fetch_web_page` with that http(s) URL. You have **no browser** — never say you opened a link unless "
                "you actually invoked `fetch_web_page` (or the user only asked for the URL itself)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_web_page",
            "description": (
                "Fetch plain text from one public http(s) URL (server-side GET). Use after `web_search` when you need "
                "article body or when the user gives a link. Only standard web pages (HTML or plain text / JSON); "
                "cannot log in or run JavaScript."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL, e.g. https://example.com/article",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_math",
            "description": (
                "Evaluate one arithmetic expression with numeric literals only (+ - * / // % **, parentheses). "
                "Use for margins, growth rates, simple ratios, or multi-step arithmetic after you plug in numbers "
                "from context or from eodhd_fundamentals_snapshot — avoids slip-prone mental math."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            'Single expression, e.g. "(128.5 - 99) / 99 * 100" or "45.2 / 12.1". '
                            "Substitute actual numbers; no variable names."
                        ),
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eodhd_fundamentals_snapshot",
            "description": (
                "Fetch a compact EODHD fundamentals snapshot for the ticker on this page. "
                "The server uses EODHD_API_KEY from its environment — never ask the user for keys. "
                "**Call whenever** context JSON lacks a field you need (Highlights, General, recent income). "
                "Prefer this over apologizing, refusing, or guessing; if the call fails, say so briefly. "
                "Use financials detail when you need last annual revenue / net income rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "financials"],
                        "description": (
                            "summary = General + Highlights only; "
                            "financials = also last 3 annual income statement rows."
                        ),
                    },
                },
            },
        },
    }
]


def _eodhd_snapshot_for_tool(symbol: str, detail_level: str) -> str:
    d = _get_fundamentals(symbol)
    if not d:
        return json.dumps({"ok": False, "error": "No EODHD data (cache or API) for this symbol."})
    gen = d.get("General") or {}
    hi = _merged_highlights(d)
    out: dict = {
        "ok": True,
        "symbol": symbol,
        "general": {
            k: gen.get(k)
            for k in ("Name", "Code", "Sector", "Industry", "CurrencyCode", "FiscalYearEnd")
            if gen.get(k) is not None
        },
        "highlights": {
            k: hi.get(k)
            for k in (
                "MarketCapitalization", "PERatio", "EarningsShare", "Beta",
                "52WeekHigh", "52WeekLow", "DividendYield", "AverageVolume",
                "WallStreetTargetPrice",
            )
            if hi.get(k) is not None
        },
    }
    if detail_level == "financials":
        annual = (d.get("Financials") or {}).get("Income_Statement", {}).get("yearly") or {}
        keys = sorted(annual.keys(), reverse=True)[:3]
        out["annual_income_last_3"] = []
        for k in keys:
            inc = annual[k]
            out["annual_income_last_3"].append({
                "period": k,
                "totalRevenue": inc.get("totalRevenue"),
                "netIncome": inc.get("netIncome"),
                "grossProfit": inc.get("grossProfit"),
            })
    try:
        return json.dumps(out, default=str)[:10000]
    except Exception:
        return json.dumps({"ok": False, "error": "serialization failed"})


def _openai_chat_round(
    client,
    model: str,
    messages: list,
    max_out: int,
    temp: float,
    *,
    tools: list | None = None,
):
    """One completion; omits temperature or switches token param if the model rejects it."""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_out,
        "temperature": temp,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e1:
        err = str(e1).lower()
        if "temperature" in err or "unsupported" in err:
            kwargs.pop("temperature", None)
            try:
                return client.chat.completions.create(**kwargs)
            except Exception:
                kwargs.pop("max_tokens", None)
                kwargs["max_completion_tokens"] = max_out
                return client.chat.completions.create(**kwargs)
        if "max_tokens" in err or "max_completion_tokens" in err:
            kwargs.pop("max_tokens", None)
            kwargs["max_completion_tokens"] = max_out
            return client.chat.completions.create(**kwargs)
        raise


def _chat_ndjson_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _chat_system_prompt(ctx_json: str) -> str:
    return (
        "You interpret one stock dashboard page. Be **brief**: default to 2–4 tight sentences "
        "or a tiny bullet list unless the user explicitly asks for depth. No filler. "
        "**Plain text only** — never HTML tags or markup. "
        "You have **no browser window** — you cannot “open” a site except via tools. "
        "Tools: `web_search` (DuckDuckGo snippets + links only); "
        "`fetch_web_page` (server fetches one public URL and returns text — use for a specific article/link); "
        "`evaluate_math` for reliable arithmetic on literals you substitute from context or tools; "
        "`eodhd_fundamentals_snapshot` for missing EODHD fields (server has EODHD_API_KEY — call it freely, "
        "do not treat it as privileged or user-paid). "
        "Not financial advice; "
        "note when numbers are uncertain.\n\n"
        "Context JSON is below.\n\n"
        "**Reply rules:** Answer the **last user message** in the thread only. Do **not** repeat "
        "the same score-card recap on every turn. If they ask a new question (growth %, valuation, "
        "risk, comparison, “why ranked here”, opinion), answer **that** with specifics from context "
        "or from the tool — do not default to re-explaining Q/V/G/S unless they asked how scoring works. "
        "If they ask for an exact word count (e.g. “in 10 words”), reply with **one** line of that length only — "
        "no second summary paragraph.\n\n"
        + ctx_json
    )


def _normalize_chat_history(history: list, max_items: int) -> list[dict]:
    """Keep only valid user/assistant strings; trim to last ``max_items`` messages without orphan turns."""
    clean: list[dict] = []
    for h in history:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        content = h.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        t = content.strip()
        if not t:
            continue
        clean.append({"role": role, "content": t})
    # Drop leading assistant (incomplete thread after truncation or bad client state)
    while clean and clean[0]["role"] == "assistant":
        clean.pop(0)
    if max_items > 0 and len(clean) > max_items:
        clean = clean[-max_items:]
    while clean and clean[0]["role"] == "assistant":
        clean.pop(0)
    return clean


def _chat_build_messages(c: dict, user_msg: str, history: list, max_in: int, max_turns: int) -> tuple[str, list]:
    sym = c["symbol"]
    try:
        ctx_json = json.dumps(_chat_stock_context_tiny(c), ensure_ascii=False, default=str)[:4000]
    except Exception:
        ctx_json = "{}"
    system = _chat_system_prompt(ctx_json)
    messages: list = [{"role": "system", "content": system}]
    max_hist = max(0, max_turns * 2)
    for h in _normalize_chat_history(history, max_hist):
        messages.append({"role": h["role"], "content": h["content"][:max_in]})
    um = user_msg.strip()[:max_in]
    messages.append({"role": "user", "content": um})
    return sym, messages


def _openai_stream_create(client, model: str, messages: list, max_out: int, temp: float | None):
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": max_out,
    }
    if temp is not None:
        kwargs["temperature"] = temp
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e1:
        err = str(e1).lower()
        if temp is not None and ("temperature" in err or "unsupported" in err):
            kwargs.pop("temperature", None)
            try:
                return client.chat.completions.create(**kwargs)
            except Exception:
                kwargs.pop("max_tokens", None)
                kwargs["max_completion_tokens"] = max_out
                return client.chat.completions.create(**kwargs)
        if "max_tokens" in err or "max_completion_tokens" in err:
            kwargs.pop("max_tokens", None)
            kwargs["max_completion_tokens"] = max_out
            return client.chat.completions.create(**kwargs)
        raise


def _chat_run_tool_loop(client, model: str, messages: list, max_out: int, temp: float, sym: str, max_tool_rounds: int) -> str:
    """Mutates messages; returns final assistant reply text."""
    reply_text = ""
    for _ in range(max_tool_rounds):
        rsp = _openai_chat_round(client, model, messages, max_out, temp, tools=_CHAT_TOOLS)
        assistant_msg = rsp.choices[0].message
        tcalls = getattr(assistant_msg, "tool_calls", None) or []

        if not tcalls:
            reply_text = (assistant_msg.content or "").strip()
            break

        assistant_dict: dict = {"role": "assistant", "content": assistant_msg.content}
        assistant_dict["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in tcalls
        ]
        messages.append(assistant_dict)

        for tc in tcalls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            payload = _chat_tool_executor(sym)(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})

    if not reply_text and messages:
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("content"):
                reply_text = str(m["content"]).strip()
                break
    if not reply_text:
        rsp = _openai_chat_round(client, model, messages, max_out, temp, tools=None)
        reply_text = (rsp.choices[0].message.content or "").strip()
    return reply_text


@app.route("/api/auth/status")
def api_auth_status():
    return jsonify(codex_chat.auth_status(PROJECT_ROOT))


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    try:
        if codex_chat.auth_status(PROJECT_ROOT).get("authenticated"):
            return jsonify({"authenticated": True})
        auth_url = codex_chat.start_login(PROJECT_ROOT)
        return jsonify({"authUrl": auth_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    codex_chat.logout(PROJECT_ROOT)
    return jsonify({"ok": True})


def _chat_tool_executor(sym: str):
    def run(name: str, args: dict) -> str:
        return chat_tools.execute_chat_tool(
            name,
            args,
            eodhd_snapshot=_eodhd_snapshot_for_tool,
            default_symbol=sym,
        )

    return run


@app.route("/api/company/<symbol>/chat", methods=["POST"])
def api_company_chat(symbol):
    """Stock-aware chat via ChatGPT subscription (Codex) or legacy API key."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    c = get_company(symbol)
    if not c:
        return jsonify({"error": "Company not found"}), 404

    use_codex = codex_chat.auth_status(PROJECT_ROOT).get("authenticated")
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not use_codex and not api_key:
        return jsonify({
            "error": "Sign in with ChatGPT (Ask AI panel) or set OPENAI_API_KEY on the server.",
        }), 503

    body = request.get_json(silent=True) or {}
    user_msg = (body.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "message is required"}), 400
    max_in = min(int(os.getenv("OPENAI_CHAT_MAX_INPUT", "8000")), 32000)
    if len(user_msg) > max_in:
        return jsonify({"error": "message too long"}), 400

    history = body.get("history")
    if not isinstance(history, list):
        history = []
    max_turns = min(int(os.getenv("OPENAI_CHAT_MAX_TURNS", "16")), 40)

    model = (os.getenv("CODEX_CHAT_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-5.4").strip()
    sym, messages = _chat_build_messages(c, user_msg, history, max_in, max_turns)

    max_out = min(int(os.getenv("OPENAI_CHAT_MAX_TOKENS", "512")), 8192)
    temp = float(os.getenv("OPENAI_CHAT_TEMPERATURE", "0.35"))
    max_tool_rounds = min(int(os.getenv("OPENAI_CHAT_MAX_TOOL_ROUNDS", "4")), 8)

    try:
        if use_codex:
            parts: list[str] = []
            for ev in codex_chat.stream_codex_chat(
                PROJECT_ROOT,
                model=model,
                messages=messages,
                tools=_CHAT_TOOLS,
                tool_executor=_chat_tool_executor(sym),
                max_tool_rounds=max_tool_rounds,
            ):
                if ev.get("token"):
                    parts.append(ev["token"])
                if ev.get("error"):
                    return jsonify({"error": ev["error"]}), 502
            return jsonify({"reply": "".join(parts), "model": model, "provider": "chatgpt"})

        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        reply_text = _chat_run_tool_loop(
            client, model, messages, max_out, temp, sym, max_tool_rounds,
        )
        return jsonify({"reply": reply_text, "model": model, "provider": "openai"})
    except Exception as e:
        return jsonify({"error": f"Chat error: {e!s}"}), 502


@app.route("/api/company/<symbol>/chat/stream", methods=["POST"])
def api_company_chat_stream(symbol):
    """NDJSON stream: optional tool phase, then token deltas; briefer defaults."""
    if not _parse_symbol(symbol):
        return Response(_chat_ndjson_line({"error": "Invalid symbol", "done": True}), status=400, mimetype="application/x-ndjson")

    c = get_company(symbol)
    if not c:
        return Response(_chat_ndjson_line({"error": "Company not found", "done": True}), status=404, mimetype="application/x-ndjson")

    use_codex = codex_chat.auth_status(PROJECT_ROOT).get("authenticated")
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not use_codex and not api_key:
        return Response(
            _chat_ndjson_line({
                "error": "Sign in with ChatGPT (Ask AI panel) to use chat.",
                "done": True,
            }),
            status=503,
            mimetype="application/x-ndjson",
        )

    body = request.get_json(silent=True) or {}
    user_msg = (body.get("message") or "").strip()
    if not user_msg:
        return Response(_chat_ndjson_line({"error": "message is required", "done": True}), status=400, mimetype="application/x-ndjson")

    max_in = min(int(os.getenv("OPENAI_CHAT_MAX_INPUT", "8000")), 32000)
    if len(user_msg) > max_in:
        return Response(_chat_ndjson_line({"error": "message too long", "done": True}), status=400, mimetype="application/x-ndjson")

    history = body.get("history") if isinstance(body.get("history"), list) else []
    max_turns = min(int(os.getenv("OPENAI_CHAT_MAX_TURNS", "16")), 40)
    model = (os.getenv("CODEX_CHAT_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-5.4").strip()
    sym, messages = _chat_build_messages(c, user_msg, history, max_in, max_turns)
    max_out = min(int(os.getenv("OPENAI_CHAT_STREAM_MAX_TOKENS", os.getenv("OPENAI_CHAT_MAX_TOKENS", "512"))), 2048)
    temp = float(os.getenv("OPENAI_CHAT_TEMPERATURE", "0.35"))
    max_tool_rounds = min(int(os.getenv("OPENAI_CHAT_MAX_TOOL_ROUNDS", "4")), 8)

    @stream_with_context
    def gen():
        try:
            if use_codex:
                for ev in codex_chat.stream_codex_chat(
                    PROJECT_ROOT,
                    model=model,
                    messages=messages,
                    tools=_CHAT_TOOLS,
                    tool_executor=_chat_tool_executor(sym),
                    max_tool_rounds=max_tool_rounds,
                ):
                    yield _chat_ndjson_line(ev)
                    if ev.get("done") or ev.get("error"):
                        return
                return

            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            msgs = [dict(m) for m in messages]

            reply_text = ""
            for _ in range(max_tool_rounds):
                rsp = _openai_chat_round(client, model, msgs, max_out, temp, tools=_CHAT_TOOLS)
                assistant_msg = rsp.choices[0].message
                tcalls = getattr(assistant_msg, "tool_calls", None) or []

                if not tcalls:
                    reply_text = (assistant_msg.content or "").strip()
                    break

                tool_name = (tcalls[0].function.name or "").strip() or None
                yield _chat_ndjson_line({"phase": "tool", **({"tool": tool_name} if tool_name else {})})
                assistant_dict: dict = {"role": "assistant", "content": assistant_msg.content}
                assistant_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                    }
                    for tc in tcalls
                ]
                msgs.append(assistant_dict)

                for tc in tcalls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    payload = _chat_tool_executor(sym)(tc.function.name, args)
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": payload})

            if not reply_text and msgs:
                for m in reversed(msgs):
                    if m.get("role") == "assistant" and m.get("content"):
                        reply_text = str(m["content"]).strip()
                        break

            if reply_text:
                step = 6
                for i in range(0, len(reply_text), step):
                    yield _chat_ndjson_line({"token": reply_text[i : i + step]})
            else:
                stream = _openai_stream_create(client, model, msgs, max_out, temp)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    piece = chunk.choices[0].delta.content
                    if piece:
                        yield _chat_ndjson_line({"token": piece})

            yield _chat_ndjson_line({"done": True, "model": model})
        except Exception as e:
            yield _chat_ndjson_line({"error": str(e), "done": True})

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(gen(), mimetype="application/x-ndjson", headers=headers)


@app.route('/api/top/<int:limit>')
def api_top(limit):
    limit = min(limit, 100)
    result = []
    for i, c in enumerate(companies[:limit]):
        s = c.get("investment_scores", {})
        m = c.get("financial_metrics", {})
        result.append({
            "rank":          i + 1,
            "symbol":        c["symbol"],
            "name":          c.get("name", c["symbol"]),
            "sector":        c.get("sector", "Unknown"),
            "overall_score": s.get("overall_score", 0),
            "growth_score":  s.get("growth_score", 0),
            "category":      s.get("investment_category", "UNKNOWN"),
            "revenue_b":     round(m.get("revenue", 0) / 1e9, 2),
            "revenue_fmt":   _format_usd_compact(m.get("revenue", 0)),
            "roe_pct":       round(m.get("roe", 0) * 100, 1),
            "roic_pct":      round(m.get("roic", 0) * 100, 1),
            "market_cap_b":  round(c.get("company_info", {}).get("market_cap", 0) / 1e9, 2),
            "market_cap_fmt": _format_usd_compact(c.get("company_info", {}).get("market_cap", 0)),
        })
    return jsonify(result)

@app.route('/api/sectors')
def api_sectors():
    sectors_data: dict = {}
    for c in companies:
        sec = c.get("sector") or "Unknown"
        if sec not in sectors_data:
            sectors_data[sec] = {"companies": [], "total_score": 0.0}
        sectors_data[sec]["companies"].append(c)
        sectors_data[sec]["total_score"] += _score(c)

    result = []
    for name, d in sectors_data.items():
        n = len(d["companies"])
        top3 = sorted(d["companies"], key=_score, reverse=True)[:3]
        result.append({
            "name":          name,
            "company_count": n,
            "average_score": round(d["total_score"] / n, 2),
            "total_revenue_b": round(sum(c.get("financial_metrics", {}).get("revenue", 0)
                                         for c in d["companies"]) / 1e9, 1),
            "total_revenue_fmt": _format_usd_compact(
                sum(c.get("financial_metrics", {}).get("revenue", 0) for c in d["companies"])
            ),
            "total_market_cap_b": round(sum(c.get("company_info", {}).get("market_cap", 0)
                                             for c in d["companies"]) / 1e9, 1),
            "total_market_cap_fmt": _format_usd_compact(
                sum(c.get("company_info", {}).get("market_cap", 0) for c in d["companies"])
            ),
            "top_companies": [{"symbol": c["symbol"], "name": c.get("name", c["symbol"]),
                               "score": _score(c), "category": c.get("investment_scores", {}).get("investment_category", "N/A")}
                              for c in top3],
        })
    result.sort(key=lambda x: x["average_score"], reverse=True)
    return jsonify(result)

@app.route('/company/<symbol>')
def company_detail(symbol):
    if not _parse_symbol(symbol):
        return "<h2>Invalid symbol</h2>", 400
    c = get_company(symbol)
    if not c:
        return "<h2>Company not found</h2>", 404

    m  = c.get("financial_metrics", {})
    ci = c.get("company_info", {})
    s  = c.get("investment_scores", {})
    pe_disp = float(ci.get("pe_ratio") or m.get("pe_ratio") or 0)
    lynch_peg = _lynch_peg(pe_disp, m)

    # Build a template-friendly view with all pre-calculated fields
    view = {
        "symbol":   c["symbol"],
        "name":     c.get("name", c["symbol"]),
        "sector":   c.get("sector", "Unknown"),
        "industry": c.get("industry", "Unknown"),
        "exchange": c.get("exchange", "US"),
        "data_quality": c.get("data_quality", {
            "income_statement": 0, "balance_sheet": 0,
            "cash_flow": 0, "quality": "N/A",
        }),
        "investment_scores": {
            "overall_score":        s.get("overall_score", 0),
            "quality_score":        s.get("quality_score", 0),
            "value_score":          s.get("value_score", 0),
            "growth_score":         s.get("growth_score", 0),
            "safety_score":         s.get("safety_score", 0),
            "investment_category":  s.get("investment_category", "N/A"),
        },
        "financial_metrics": {
            "revenue_b":            round(m.get("revenue", 0) / 1e9, 2),
            "revenue_fmt":          _format_usd_compact(m.get("revenue", 0)),
            "net_income_b":         round(m.get("net_income", 0) / 1e9, 2),
            "net_income_fmt":       _format_usd_compact(m.get("net_income", 0)),
            "operating_cash_flow_fmt": _format_usd_compact(m.get("operating_cash_flow", 0)),
            "capital_expenditure_fmt": _format_usd_compact(m.get("capital_expenditure", 0)),
            "free_cash_flow_fmt":      _format_usd_compact(m.get("free_cash_flow", 0)),
            "owner_earnings_b":     round(m.get("owner_earnings", 0) / 1e9, 3),
            "owner_earnings_fmt":   _format_usd_compact(m.get("owner_earnings", 0)),
            "oeps_cagr_pct":        round(m.get("oeps_cagr", 0) * 100, 1),
            "gross_margin_pct":     round(m.get("gross_margin", 0) * 100, 1),
            "net_margin_pct":       round(m.get("net_margin", 0) * 100, 1),
            "operating_margin_pct": round(m.get("operating_margin", 0) * 100, 1),
            "roe_pct":              round(m.get("roe", 0) * 100, 1),
            "roic_pct":             round(m.get("roic", 0) * 100, 1),
            "roa_pct":              round(m.get("roa", 0) * 100, 1),
            "pe_ratio":             ci.get("pe_ratio") or m.get("pe_ratio", 0),
            "lynch_peg":            lynch_peg,
            "pb_ratio":             round(m.get("pb_ratio", 0), 2),
            "ps_ratio":             round(m.get("ps_ratio", 0), 2),
            "ev_ebitda":            round(m.get("ev_ebitda", 0), 1),
            "current_ratio":        round(m.get("current_ratio", 0), 2),
            "debt_to_equity":       round(m.get("debt_to_equity", 0), 2),
            "altman_z_score":       round(m.get("altman_z_score", 0), 1),
            "piotroski_score":      m.get("piotroski_score", 0),
            "revenue_growth_1y_pct": round(m.get("revenue_growth_1y", 0) * 100, 1),
            "revenue_cagr_3y_pct":  round(m.get("revenue_cagr_3y", m.get("revenue_cagr_4y", 0)) * 100, 1),
            "red_flags":            m.get("red_flags", []),
        },
        "company_info": {
            "market_cap_b":  round(ci.get("market_cap", 0) / 1e9, 2),
            "market_cap_fmt": _format_usd_compact(ci.get("market_cap", 0)),
            "pe_ratio":      ci.get("pe_ratio", 0),
            "description":   ci.get("description", ""),
        },
        "analyst_ratings": _fmt_analyst(c.get("analyst_ratings", {})),
        "technicals": {"high_52w": None, "low_52w": None, "ma_50": None, "ma_200": None, "beta": None},
    }
    try:
        fund_data = _get_fundamentals(symbol)
        if fund_data:
            tech = fund_data.get("Technicals", {})
            view["technicals"] = {
                "high_52w": round(float(tech.get("52WeekHigh") or 0), 2) or None,
                "low_52w":  round(float(tech.get("52WeekLow") or 0), 2) or None,
                "ma_50":    round(float(tech.get("50DayMA") or 0), 2) or None,
                "ma_200":   round(float(tech.get("200DayMA") or 0), 2) or None,
                "beta":     round(float(tech.get("Beta") or 0), 2) or None,
            }
    except Exception:
        pass
    return render_template('company.html', company=view)


@app.route('/sectors')
def sectors_page():
    return render_template('sectors.html')


@app.route('/api/analysis/progress')
def analysis_progress():
    """Poll the progress of a running analysis."""
    pf = PROJECT_ROOT / "outputs" / "analysis_progress.json"
    if not pf.exists():
        return jsonify({"running": False, "done": 0, "total": 0, "pct": 0})
    try:
        return jsonify(json.loads(pf.read_text(encoding="utf-8")))
    except Exception:
        return jsonify({"running": False, "done": 0, "total": 0, "pct": 0})


def _write_analysis_progress_file(payload: dict) -> None:
    """Atomically write ``outputs/analysis_progress.json`` (avoid empty reads while polling)."""
    pf = PROJECT_ROOT / "outputs" / "analysis_progress.json"
    pf.parent.mkdir(parents=True, exist_ok=True)
    tmp = pf.with_suffix(pf.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(pf)


_analysis_lock = threading.Lock()


def _safe_outputs_path(rel: str | None) -> Path | None:
    """Resolve ``rel`` to a path under ``PROJECT_ROOT/outputs`` only; else None."""
    if not rel or not isinstance(rel, str):
        return None
    raw = rel.strip().replace("\\", "/")
    if not raw or "\x00" in raw:
        return None
    if raw.startswith("/") or ":" in raw[:3]:  # POSIX abs or Windows drive
        return None
    if ".." in Path(raw).parts:
        return None
    base = (PROJECT_ROOT / "outputs").resolve()
    cand = (base / raw).resolve()
    try:
        cand.relative_to(base)
    except ValueError:
        return None
    return cand


def _symbols_list_from_outputs_file(path: Path) -> list[str]:
    """Same rules as ``scripts/scale_analysis_1000._load_symbols_from_file`` (dedupe, order)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sym = line.split(",", maxsplit=1)[0].strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


@app.route('/api/analysis/run', methods=['POST'])
def analysis_run():
    """Trigger a fresh analysis run in a background subprocess."""
    pf = PROJECT_ROOT / "outputs" / "analysis_progress.json"
    if pf.exists():
        try:
            prog = json.loads(pf.read_text())
            if prog.get("running"):
                return jsonify({"error": "Analysis already running"}), 409
        except Exception:
            pass
    if not _analysis_lock.acquire(blocking=False):
        return jsonify({"error": "Analysis already running"}), 409

    body = request.get_json(silent=True) or {}
    target = min(int(body.get("target", 1000)), 4000)
    _cpu = os.cpu_count() or 8
    workers = min(int(body.get("workers", 0)) or _cpu, 64)
    try:
        _fetch_conc = int(os.environ.get("EODHD_FETCH_CONCURRENCY", "200"))
    except ValueError:
        _fetch_conc = 200
    concurrency = min(int(body.get("concurrency", 0)) or _fetch_conc, 300)

    sf_raw = body.get("symbols_file")
    mf_raw = body.get("merge_into")
    sym_path = _safe_outputs_path(sf_raw) if sf_raw else None
    merge_path = _safe_outputs_path(mf_raw) if mf_raw else None

    if sf_raw and sym_path is None:
        _analysis_lock.release()
        return jsonify({"error": "Invalid symbols_file (must be under outputs/)"}), 400
    if sf_raw and sym_path is not None and not sym_path.is_file():
        _analysis_lock.release()
        return jsonify({"error": "symbols_file not found"}), 404

    if mf_raw and merge_path is None:
        _analysis_lock.release()
        return jsonify({"error": "Invalid merge_into (must be under outputs/)"}), 400
    if mf_raw and merge_path is not None and not merge_path.is_file():
        _analysis_lock.release()
        return jsonify({"error": "merge_into not found"}), 404

    sym_list: list[str] = []
    if sym_path is not None:
        sym_list = _symbols_list_from_outputs_file(sym_path)
        if not sym_list:
            _analysis_lock.release()
            return jsonify({"error": "symbols_file is empty"}), 400
        target = min(4000, max(target, len(sym_list)))

    script = PROJECT_ROOT / "scripts" / "scale_analysis_1000.py"
    total_hint = len(sym_list) if sym_list else target
    # Prime progress before returning so the UI's first poll never sees a stale
    # ``running: false`` from an earlier run while the worker thread hasn't run yet.
    _write_analysis_progress_file(
        {
            "running": True,
            "done": 0,
            "total": total_hint,
            "pct": 0,
            "last_sym": "",
            "last_score": 0,
            "successful": 0,
            "failed": 0,
            "started_at": datetime.now().isoformat(),
        }
    )

    def _run():
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            cmd = [
                sys.executable,
                str(script),
                "--refresh",
                "--target",
                str(target),
                "--workers",
                str(workers),
                "--concurrency",
                str(concurrency),
            ]
            if sym_path is not None:
                cmd.extend(["--symbols-file", str(sym_path)])
            if merge_path is not None:
                cmd.extend(["--merge-into", str(merge_path)])
            proc = subprocess.run(cmd, env=env, cwd=str(PROJECT_ROOT))
            if proc.returncode == 0:
                load_data()
            else:
                _write_analysis_progress_file(
                    {
                        "running": False,
                        "done": 0,
                        "total": total_hint,
                        "pct": 0,
                        "last_sym": "",
                        "last_score": 0,
                        "successful": 0,
                        "failed": 0,
                        "started_at": datetime.now().isoformat(),
                        "error": f"subprocess exit {proc.returncode}",
                    }
                )
        except Exception as ex:
            _write_analysis_progress_file(
                {
                    "running": False,
                    "done": 0,
                    "total": total_hint,
                    "pct": 0,
                    "last_sym": "",
                    "last_score": 0,
                    "successful": 0,
                    "failed": 0,
                    "started_at": datetime.now().isoformat(),
                    "error": str(ex)[:240],
                }
            )
        finally:
            _analysis_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    resp = {"started": True, "target": target, "workers": workers}
    out_base = (PROJECT_ROOT / "outputs").resolve()
    if sym_path is not None:
        try:
            resp["symbols_file"] = sym_path.resolve().relative_to(out_base).as_posix()
        except ValueError:
            resp["symbols_file"] = sym_path.name
    if merge_path is not None:
        try:
            resp["merge_into"] = merge_path.resolve().relative_to(out_base).as_posix()
        except ValueError:
            resp["merge_into"] = merge_path.name
    return jsonify(resp)


if __name__ == '__main__':
    print("Equity Analysis Dashboard")
    load_data()
    if companies:
        print(
            f"Top: {companies[0]['symbol']} "
            f"(adj {_compounder_list_score(companies[0]):.1f} · raw {_score(companies[0]):.1f}/20)"
        )
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 3000)))
