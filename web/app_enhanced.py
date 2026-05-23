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
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests as _req
_web_dir = Path(__file__).resolve().parent
# Repo root when app lives in web/ (local dev and Docker WORKDIR=/app/web).
PROJECT_ROOT = _web_dir.parent if (_web_dir.parent / "src").is_dir() else _web_dir
sys.path.insert(0, str(PROJECT_ROOT / "src"))
_SCRIPTS_DIR = str(PROJECT_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(1, _SCRIPTS_DIR)

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
import moonstocks_store as ms_store

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(_web_dir / ".env")

MOONSTOCKS_API_BASE = os.environ.get(
    "MOONSTOCKS_API_URL",
    "http://moonstocks-lb-prod-15318164.eu-north-1.elb.amazonaws.com",
).rstrip("/")

app = Flask(__name__)

def _moonstocks_analyzer_url() -> str:
    return (
        os.environ.get("MOONSTOCKS_ANALYZER_URL")
        or "http://moonstocks-ai-analyzer-lb-prod-15318164.eu-north-1.elb.amazonaws.com"
    ).rstrip("/")


def _moonstocks_analyzer_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    key = (os.environ.get("ANALYZER_API_KEY") or "").strip()
    if key:
        headers["X-API-Key"] = key
    return headers


def _moonstocks_ingest_authorized() -> bool:
    """Optional shared secret for POST /api/analysis (analyzer callback)."""
    expected = (
        os.environ.get("MOONSTOCKS_INGEST_API_KEY")
        or os.environ.get("ANALYZER_API_KEY")
        or ""
    ).strip()
    if not expected:
        return True
    return request.headers.get("X-API-Key") == expected


@app.context_processor
def _inject_glossary():
    return {"G": GLOSSARY}

# ── Global state ──────────────────────────────────────────────────────────────
companies: list[dict] = []
company_lookup: dict[str, dict] = {}
screener_rank_by_symbol: dict[str, int] = {}
_companies_listing_sorted: bool = False
momentum_rank_by_symbol: dict[str, int] = {}
_momentum_order_index: dict[str, int] = {}
_companies_momentum_sorted: bool = False
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


def _largest_nonempty(directory: Path, pattern: str) -> Path | None:
    """Return the non-empty file with the most rows (primary universe, not a one-off batch)."""
    best_f: Path | None = None
    best_n = 0
    for f in directory.glob(pattern):
        data = read_jsonl(f)
        n = len(data)
        if n > best_n:
            best_n = n
            best_f = f
    return best_f


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


_calculate_scores_fn = None


def _merge_dict_fieldwise(
    base: dict | None,
    patch: dict | None,
    *,
    skip_zero_for: frozenset[str] | None = None,
) -> dict:
    """Shallow field merge; skip None/empty and optional zero placeholders from stale overlays."""
    out = dict(base or {})
    if not patch:
        return out
    skip = skip_zero_for or frozenset()
    for k, v in patch.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if k in skip and isinstance(v, (int, float)) and float(v) == 0.0:
            continue
        out[k] = v
    return out


def _refresh_investment_scores(c: dict) -> bool:
    """Recompute Q/V/G/S from financial_metrics (PEG-aware value score)."""
    global _calculate_scores_fn
    metrics = c.get("financial_metrics")
    if not metrics or not isinstance(metrics, dict):
        return False
    if _calculate_scores_fn is None:
        from scale_analysis_1000 import calculate_investment_scores as _fn

        _calculate_scores_fn = _fn
    scores = _calculate_scores_fn(
        metrics,
        is_primary_listing=bool(c.get("is_primary_listing", True)),
        sector=str(c.get("sector") or ""),
        industry=str(c.get("industry") or ""),
    )
    c["investment_scores"] = scores
    return True


def _status_print(msg: str) -> None:
    """Print startup status (run_server.py may wrap sys.stdout)."""
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        print(msg, file=stream, flush=True)
    except (ValueError, OSError):
        pass


def _refresh_all_investment_scores(rows: list[dict]) -> int:
    t0 = time.perf_counter()
    n = 0
    for c in rows:
        if _refresh_investment_scores(c):
            n += 1
    ms = (time.perf_counter() - t0) * 1000
    _status_print(f"[OK] Refreshed investment_scores for {n} companies ({ms:.0f} ms)")
    return n


def _inject_analyst_ratings(rows: list[dict]) -> None:
    """Back-fill EODHD buy/hold/sell from fundamentals cache (no Yahoo at startup)."""
    cache_dir = PROJECT_ROOT / "outputs" / "fundamentals_cache"
    if not cache_dir.is_dir():
        return
    from eodhd_analyst import extract_analyst_ratings, has_consensus_votes

    patched = 0
    stripped = 0
    for c in rows:
        stored = c.get("analyst_ratings") or {}
        if has_consensus_votes(stored) and not stored.get("partial"):
            continue
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        if stored.get("partial"):
            c.pop("analyst_ratings", None)
            stripped += 1
        fp = cache_dir / f"{sym}.json"
        if not fp.is_file():
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        extracted = extract_analyst_ratings(data)
        if has_consensus_votes(extracted):
            c["analyst_ratings"] = extracted
            patched += 1
    if patched or stripped:
        print(f"[OK] Analyst inject: {patched} EODHD consensus, {stripped} estimate-only rows cleared")


def _inject_eps_growth(rows: list[dict]) -> None:
    """Back-fill eps_growth and latest-quarter revenue growth from EODHD Highlights."""
    cache_dir = PROJECT_ROOT / "outputs" / "fundamentals_cache"
    if not cache_dir.is_dir():
        return
    patched = 0
    rev_patched = 0
    for c in rows:
        m = c.get("financial_metrics") or c.get("metrics") or {}
        if not isinstance(m, dict):
            continue
        need_eps = not m.get("eps_growth")
        need_rev_q = m.get("latest_quarter_revenue_growth") is None
        if not need_eps and not need_rev_q:
            continue
        sym = c.get("symbol", "")
        fp = cache_dir / f"{sym}.json"
        if not fp.is_file():
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        hl = data.get("Highlights") or {}
        if need_eps:
            val = hl.get("QuarterlyEarningsGrowthYOY")
            if val is not None and val != "":
                eg = float(val) if isinstance(val, (int, float)) else float(str(val).strip())
                if eg != 0.0:
                    m["eps_growth"] = eg
                    patched += 1
        if need_rev_q:
            rv = hl.get("QuarterlyRevenueGrowthYOY")
            if rv is not None and rv != "":
                rq = float(rv) if isinstance(rv, (int, float)) else float(str(rv).strip())
                if rq != 0.0:
                    m["latest_quarter_revenue_growth"] = rq
                    rev_patched += 1
    if patched or rev_patched:
        print(
            f"[OK] Highlights inject: eps_growth={patched}, "
            f"latest_quarter_revenue_growth={rev_patched}"
        )


def load_data() -> bool:
    """Load universe from latest scaled (or final), overlay rescored scores when present.

    Root issue fixed: an older small ``rescored_*.jsonl`` must not replace a larger
    ``scaled_analysis_*.jsonl`` — we always keep the scaled universe and only patch
    ``investment_scores`` / ``name`` from rescored for matching symbols.
    """
    global companies, company_lookup, screener_rank_by_symbol, _companies_listing_sorted
    global momentum_rank_by_symbol, _momentum_order_index, _companies_momentum_sorted
    global DATA_SOURCE, DATA_FILE, DATA_OVERLAY_FILE, sector_valuation_medians

    output_dir = PROJECT_ROOT / "outputs"

    scaled_f = _largest_nonempty(output_dir / "scaled_analysis", "scaled_analysis_*.jsonl")
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
        screener_rank_by_symbol = {}
        _companies_listing_sorted = False
        momentum_rank_by_symbol = {}
        _momentum_order_index = {}
        _companies_momentum_sorted = False
        sector_valuation_medians = {}
        DATA_SOURCE = "none"
        DATA_FILE = None
        DATA_OVERLAY_FILE = None
        print("[ERR] No analysis data found")
        return False

    base_rows = _dedupe_rows_best_score(base_rows)
    def _merge_overlay_jsonl(filename: str, label: str) -> None:
        nonlocal base_rows
        path = output_dir / filename
        if not path.is_file():
            return
        rows = read_jsonl(path)
        if not rows:
            return
        by_sym = {str(c["symbol"]).upper(): c for c in base_rows if c.get("symbol")}
        for c in rows:
            sym = str(c.get("symbol") or "").upper()
            if sym:
                by_sym[sym] = c
        base_rows = list(by_sym.values())
        print(f"[OK] Merged {len(rows)} {label} row(s) from {path.name}")

    _merge_overlay_jsonl("extra_companies.jsonl", "extra universe")
    _merge_overlay_jsonl("nordic_companies.jsonl", "Nordic")
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
                    if rc.get("name"):
                        c["name"] = rc["name"]
                    c["financial_metrics"] = _merge_dict_fieldwise(
                        c.get("financial_metrics"),
                        rc.get("financial_metrics"),
                    )
                    c["company_info"] = _merge_dict_fieldwise(
                        c.get("company_info"),
                        rc.get("company_info"),
                    )
                    overlay_used = True
        else:
            print(f"[SKIP] Overlay {rescored_f.name} is older than base — not applying")

    _refresh_all_investment_scores(base_rows)

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
    _inject_analyst_ratings(companies)
    # Lookup must exist before listing sort: _compounder_list_score applies duplicate-share penalties.
    company_lookup = {c["symbol"]: c for c in companies}
    # Re-rank for dashboard default order: prefer scale + margin reliability over raw model peak.
    companies = sorted(companies, key=_listing_sort_key)
    screener_rank_by_symbol = {c["symbol"]: i + 1 for i, c in enumerate(companies)}
    _companies_listing_sorted = True
    _rebuild_momentum_ranks()
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
    if gap <= 0.22:
        return 0.90
    if gap <= 0.32:
        return 0.84
    return 0.78


def _rebuild_screener_ranks() -> None:
    """Rebuild universe rank map after tests or in-memory company list edits."""
    global screener_rank_by_symbol, _companies_listing_sorted
    screener_rank_by_symbol = {c["symbol"]: i + 1 for i, c in enumerate(companies)}
    _companies_listing_sorted = False


def _screener_rank(symbol: str) -> int | None:
    return screener_rank_by_symbol.get((symbol or "").strip().upper())


def _cached_listing_score(c: dict) -> float:
    """Listing score computed once at load; avoid O(n) recompute on every API page."""
    cached = c.get("_listing_score")
    if cached is not None:
        return float(cached)
    val = _compounder_list_score(c)
    c["_listing_score"] = val
    return val


def _listing_sort_key(c: dict) -> tuple[float, str]:
    return (-_cached_listing_score(c), (c.get("symbol") or ""))


def _growth_pct_to_unit(g: float, cap: float = 0.60) -> float:
    """Map a YoY growth ratio (0.25 = 25%) to 0–1."""
    x = float(g or 0.0)
    if not math.isfinite(x) or x <= 0:
        return 0.0
    return _clamp01(x / cap)


def _short_term_growth_score(c: dict) -> float:
    """Short-term high-growth rank (0–20) from quarterly-derived metrics already in the universe.

    Uses TTM revenue/EPS growth, revenue acceleration (recent 4Q vs prior 4Q), and the latest
    reported quarter YoY when available. Designed to surface names for deeper quarterly review
    without re-parsing 4k+ filings on every dashboard request.
    """
    m = c.get("financial_metrics") or {}
    min_q = int((c.get("data_quality") or {}).get("min_quarters", 0) or 0)

    rev_ttm = float(m.get("revenue_growth_1y") or 0.0)
    rev_q = float(m.get("latest_quarter_revenue_growth") or 0.0)
    rev_near = max(rev_ttm, rev_q) if (rev_q > 0 or rev_ttm <= 0) else rev_ttm

    rev_accel = float(m.get("revenue_acceleration") or 0.0)
    eps_g = float(m.get("eps_growth") or 0.0)
    ni_g = float(m.get("net_income_growth") or 0.0)
    earn_g = max(eps_g, ni_g)

    if rev_near < 0.05 and earn_g > 0.40:
        earn_g = min(0.15, rev_near * 2.0 + 0.05)

    u_rev = _growth_pct_to_unit(rev_near, 0.65)
    u_accel = _clamp01((rev_accel + 0.08) / 0.40)
    u_earn = _growth_pct_to_unit(earn_g, 0.75)
    u_ttm = _growth_pct_to_unit(rev_ttm, 0.55)

    base = (0.38 * u_rev) + (0.24 * u_accel) + (0.26 * u_earn) + (0.12 * u_ttm)

    if rev_near < 0.10 and rev_accel < 0.02 and earn_g < 0.12:
        base *= 0.30
    if rev_near < 0:
        base *= 0.12

    conf = 1.0
    if min_q < 4:
        conf *= 0.50
    elif min_q < 8:
        conf *= 0.72
    elif min_q >= 12:
        conf = min(1.0, conf * 1.04)

    red = int(m.get("red_flag_count") or 0)
    if red >= 3:
        conf *= 0.68
    elif red >= 1:
        conf *= 0.88

    gm_exp = float(m.get("gross_margin_expansion") or 0.0)
    if gm_exp > 0.02:
        base = min(1.0, base * 1.05)

    return round(base * conf * 20.0, 2)


def _cached_momentum_score(c: dict) -> float:
    cached = c.get("_momentum_score")
    if cached is not None:
        return float(cached)
    val = _short_term_growth_score(c)
    c["_momentum_score"] = val
    return val


def _momentum_sort_key(c: dict) -> tuple[float, str]:
    return (-_cached_momentum_score(c), (c.get("symbol") or ""))


def _rebuild_momentum_ranks() -> None:
    """Precompute momentum order for fast dashboard sort (quarterly-growth screener)."""
    global momentum_rank_by_symbol, _momentum_order_index, _companies_momentum_sorted
    ordered = sorted(companies, key=_momentum_sort_key)
    momentum_rank_by_symbol = {
        (c.get("symbol") or "").strip().upper(): i + 1 for i, c in enumerate(ordered)
    }
    _momentum_order_index = {
        (c.get("symbol") or "").strip().upper(): i for i, c in enumerate(ordered)
    }
    _companies_momentum_sorted = True


def _momentum_rank(symbol: str) -> int | None:
    return momentum_rank_by_symbol.get((symbol or "").strip().upper())


def _momentum_score_breakdown(c: dict) -> dict:
    m = c.get("financial_metrics") or {}
    rev_ttm = float(m.get("revenue_growth_1y") or 0.0)
    rev_q = float(m.get("latest_quarter_revenue_growth") or 0.0)
    return {
        "momentum_score": _cached_momentum_score(c),
        "momentum_rank": _momentum_rank(c.get("symbol") or ""),
        "revenue_growth_ttm_pct": round(rev_ttm * 100, 1),
        "revenue_growth_latest_q_pct": round(rev_q * 100, 1),
        "revenue_acceleration_pct": round(float(m.get("revenue_acceleration") or 0) * 100, 1),
        "eps_growth_ttm_pct": round(float(m.get("eps_growth") or 0) * 100, 1),
        "min_quarters": int((c.get("data_quality") or {}).get("min_quarters", 0) or 0),
    }


def _analyst_for_list_api(c: dict) -> dict | None:
    """Dashboard rows: stored consensus only — never hit Yahoo on list requests."""
    from eodhd_analyst import has_consensus_votes

    ar = c.get("analyst_ratings") or {}
    if has_consensus_votes(ar) and not ar.get("partial"):
        return _fmt_analyst(ar)
    return None


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

    # Weights: growth leads; value/safety are guardrails (not a substitute for compounding).
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
    # Scale confidence: discount micro-caps; mid-cap steady compounders need not be $50B+.
    confidence *= _listing_scale_confidence(mcap_b, rev_b)
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

    confidence *= _steady_compounder_confidence_lift(m, s)

    score = 20.0 * base * confidence
    score *= _per_share_growth_distortion_factor(m)
    # Growth floor: weak compounders can't top the list on safety/value/scale alone.
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


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")


def _parse_symbol(raw: str) -> str | None:
    """Reject path tricks and garbage; allow BRK.B style tickers."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not _SYMBOL_RE.fullmatch(s):
        return None
    return s


def _normalize_exchange_code(ex: str) -> str:
    """Map listing metadata to EODHD suffix (OL, ST, CO, HE, US)."""
    u = (ex or "US").strip().upper()
    if u in ("OL", "OS", "XOSL", "OSE"):
        return "OL"
    if u in ("ST", "STO", "XSTO", "SSE"):
        return "ST"
    if u in ("CO", "CPH", "XCSE", "CPSE"):
        return "CO"
    if u in ("HE", "HEL", "XHEL"):
        return "HE"
    return u or "US"


def _eodhd_ticker(symbol: str, company: dict | None = None) -> str | None:
    """EODHD symbol with exchange suffix (AAPL.US, EQNR.OL, NOVO-B.CO)."""
    sym = _parse_symbol(symbol)
    if not sym:
        return None
    if "." in sym:
        base, suf = sym.rsplit(".", 1)
        if base and len(suf) <= 6 and suf in ("US", "OL", "ST", "CO", "HE"):
            return sym
    ex = _normalize_exchange_code(
        (company or {}).get("exchange") or (company or {}).get("eodhd_exchange") or "US"
    )
    if ex == "US":
        return f"{sym}.US"
    return f"{sym}.{ex}"


def get_company(symbol: str) -> dict | None:
    ps = _parse_symbol(symbol)
    if not ps:
        return None
    if ps in company_lookup:
        return company_lookup[ps]
    if "." in ps:
        base = ps.rsplit(".", 1)[0]
        return company_lookup.get(base)
    return None


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
        r1 = _fnum(c.get("rev_growth_1y_pct"))
        if r1 == 0.0:
            r1 = _fnum((m.get("revenue_growth_1y") or 0) * 100.0)
        oe = _fnum(s.get("oeps_cagr_pct"))
        # Tie-break %s are hints only; uncapped bad rows (double-counted ROIC, FX slips)
        # should not reorder the whole table.
        def _clip_pct(x: float, lo: float = -150.0, hi: float = 120.0) -> float:
            if not math.isfinite(x):
                return 0.0
            return max(lo, min(hi, x))

        return (g, max(_clip_pct(roic_p), _clip_pct(rc), _clip_pct(r1), _clip_pct(oe)))

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
        "listing_score":  _cached_listing_score,
        "momentum_score": _cached_momentum_score,
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
        "analyst":        lambda c: (
            _fnum(
                (c.get("analyst_ratings") or {}).get("Rating")
                or (c.get("analyst_ratings") or {}).get("rating"),
            )
            if not (c.get("analyst_ratings") or {}).get("partial")
            else _fnum((c.get("analyst_ratings") or {}).get("total_analysts")) * 0.01
        ),
    }
    key_fn = key_map.get(sort_by, key_map["listing_score"])
    if not (
        sort_by == "listing_score"
        and so == "desc"
        and _companies_listing_sorted
        and _rows_keep_listing_order(result)
    ) and not (
        sort_by == "momentum_score"
        and so == "desc"
        and _companies_momentum_sorted
        and _rows_keep_momentum_order(result)
    ):
        result = sorted(result, key=key_fn, reverse=(so == "desc"))
    return result


def _rows_keep_momentum_order(rows: list[dict]) -> bool:
    if not rows or not _momentum_order_index:
        return True
    last = -1
    for c in rows:
        i = _momentum_order_index.get((c.get("symbol") or "").strip().upper(), -1)
        if i < last:
            return False
        last = i
    return True


def _rows_keep_listing_order(rows: list[dict]) -> bool:
    """True when row order matches the pre-sorted universe (filters only, no reorder)."""
    if not rows:
        return True
    idx = {c["symbol"]: i for i, c in enumerate(companies)}
    last = -1
    for c in rows:
        i = idx.get(c.get("symbol"), -1)
        if i < last:
            return False
        last = i
    return True

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
            "listing_score": round(_cached_listing_score(top_overall), 2) if top_overall else 0.0,
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
            "listing_score": round(_cached_listing_score(c), 2),
            "momentum_score": round(_cached_momentum_score(c), 2),
            "screener_rank": _screener_rank(c["symbol"]),
            "momentum_rank": _momentum_rank(c["symbol"]),
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
            "analyst_ratings": _analyst_for_list_api(c),
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


@app.route("/api/screener/high-growth-shortlist")
def api_high_growth_shortlist():
    """Top names by short-term quarterly growth score — candidates for deeper report review."""
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 500))
    except (TypeError, ValueError):
        limit = 200
    try:
        min_score = float(request.args.get("min_score", 8.0))
    except (TypeError, ValueError):
        min_score = 8.0
    try:
        min_rev_pct = float(request.args.get("min_rev_growth_pct", 15.0))
    except (TypeError, ValueError):
        min_rev_pct = 15.0
    min_rev = min_rev_pct / 100.0

    pool = []
    for c in companies:
        m = c.get("financial_metrics") or {}
        rev_ttm = float(m.get("revenue_growth_1y") or 0.0)
        rev_q = float(m.get("latest_quarter_revenue_growth") or 0.0)
        if max(rev_ttm, rev_q) < min_rev:
            continue
        ms = _cached_momentum_score(c)
        if ms < min_score:
            continue
        row = {
            "symbol": c.get("symbol"),
            "name": c.get("name", c.get("symbol")),
            "sector": c.get("sector", "Unknown"),
            **_momentum_score_breakdown(c),
        }
        pool.append(row)
    pool.sort(key=lambda r: (-r["momentum_score"], r.get("symbol") or ""))
    page = pool[:limit]
    return jsonify({
        "candidates": page,
        "total_qualified": len(pool),
        "limit": limit,
        "min_score": min_score,
        "min_rev_growth_pct": min_rev_pct,
        "description": (
            "Pre-screened from quarterly TTM and latest-quarter growth already in the universe. "
            "Use company pages for full quarterly report timelines."
        ),
    })


def _fmt_analyst(ar: dict) -> dict | None:
    if not ar:
        return None
    from eodhd_analyst import has_consensus_votes

    if ar.get("partial") and not has_consensus_votes(ar):
        return None

    strong_buy = int(ar.get("StrongBuy") or ar.get("strong_buy") or 0)
    buy = int(ar.get("Buy") or ar.get("buy") or 0)
    hold = int(ar.get("Hold") or ar.get("hold") or 0)
    sell = int(ar.get("Sell") or ar.get("sell") or 0)
    strong_sell = int(ar.get("StrongSell") or ar.get("strong_sell") or 0)
    total = strong_buy + buy + hold + sell + strong_sell

    r = ar.get("Rating") if ar.get("Rating") is not None else ar.get("rating")
    if r is None or str(r).strip() in ("", "0", "0.0"):
        if total < 1:
            return None
        weighted = (5 * strong_buy + 4 * buy + 3 * hold + 2 * sell + 1 * strong_sell) / total
        r = weighted

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
        "total_analysts": total,
        "rating_detail": detail,
        "partial": False,
        "source": ar.get("source") or "eodhd",
    }


def _analyst_ratings_for_company(c: dict) -> dict | None:
    """Buy/hold/sell consensus: EODHD, then primary listing, then Yahoo Finance."""
    from eodhd_analyst import has_consensus_votes, resolve_consensus_analyst_ratings

    sym = str(c.get("symbol") or "").upper()
    if not sym:
        return None
    stored = c.get("analyst_ratings")
    if has_consensus_votes(stored) and not stored.get("partial"):
        return stored

    fundamentals = _read_fundamentals_cache_file(sym)
    ar = resolve_consensus_analyst_ratings(sym, fundamentals=fundamentals, stored=stored)
    return ar if has_consensus_votes(ar) else None


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


def _eodhd_display_metrics(history: list, ttm: dict | None, h: dict | None) -> dict:
    """Headline figures with explicit basis (TTM vs latest filed FY) — matches financial charts."""
    latest = history[-1] if history else {}
    fy = str(latest.get("year") or "")
    out: dict = {
        "source": "eodhd",
        "note": (
            "Flow metrics (revenue, net income, CFO, FCF) on this page use TTM (sum of last 4 quarters). "
            "Filed FY is the latest annual column on the charts — do not compare TTM net income to FY FCF."
        ),
    }
    if ttm:
        out["flow"] = {
            "basis": "TTM",
            "period_end": (ttm.get("period_end") or "")[:10],
            "revenue_fmt": _format_usd_compact(_safe_float(ttm.get("revenue_usd"))),
            "net_income_fmt": _format_usd_compact(_safe_float(ttm.get("net_income_usd"))),
            "operating_cash_flow_fmt": _format_usd_compact(_safe_float(ttm.get("ocf_usd"))),
            "capital_expenditure_fmt": _format_usd_compact(_safe_float(ttm.get("capex_usd"))),
            "free_cash_flow_fmt": _format_usd_compact(_safe_float(ttm.get("fcf_usd"))),
            "gross_margin_pct": round(_safe_float(ttm.get("gross_margin_pct")), 1),
            "net_margin_pct": round(_safe_float(ttm.get("net_margin_pct")), 1),
        }
    if latest:
        out["filed_fy"] = {
            "basis": f"FY{fy}" if fy else "Filed FY",
            "year": fy,
            "revenue_fmt": _format_usd_compact(_safe_float(latest.get("revenue_usd"))),
            "net_income_fmt": _format_usd_compact(_safe_float(latest.get("net_income_usd"))),
            "operating_cash_flow_fmt": _format_usd_compact(_safe_float(latest.get("ocf_usd"))),
            "capital_expenditure_fmt": _format_usd_compact(_safe_float(latest.get("capex_usd"))),
            "free_cash_flow_fmt": _format_usd_compact(_safe_float(latest.get("fcf_usd"))),
            "gross_margin_pct": round(_safe_float(latest.get("gross_margin_pct")), 1),
            "net_margin_pct": round(_safe_float(latest.get("net_margin_pct")), 1),
        }
    if h:
        pe = _safe_float(h.get("PERatio"))
        if pe > 0:
            out["pe_ttm"] = round(pe, 2)
    return out


def _chat_metrics_from_eodhd(symbol: str) -> dict | None:
    """Lightweight EODHD headline for chat context (avoids stale scan-only metrics)."""
    try:
        d = _get_fundamentals(symbol)
        if not d:
            return None
        annual = (d.get("Financials") or {}).get("Income_Statement", {}).get("yearly") or {}
        if not annual:
            return None
        yr_key = sorted(annual.keys())[-1]
        inc = annual[yr_key]
        bs = (d.get("Financials") or {}).get("Balance_Sheet", {}).get("yearly", {}).get(yr_key, {})
        cf = (d.get("Financials") or {}).get("Cash_Flow", {}).get("yearly", {}).get(yr_key, {})
        shares_stats = d.get("SharesStats") or {}
        shares_out = _safe_float(shares_stats.get("SharesOutstanding")) or 1.0
        rev = _safe_float(inc.get("totalRevenue"))
        ni = _safe_float(inc.get("netIncome"))
        ocf = _safe_float(cf.get("totalCashFromOperatingActivities"))
        capex = abs(_safe_float(cf.get("capitalExpenditures")))
        cor = _safe_float(inc.get("costOfRevenue"))
        gp = _safe_float(inc.get("grossProfit"))
        if rev > 0 and cor > 0 and gp >= rev * 0.999:
            gp = rev - cor
        latest_row = {
            "year": yr_key[:4],
            "revenue_usd": rev,
            "net_income_usd": ni,
            "ocf_usd": ocf,
            "capex_usd": capex,
            "fcf_usd": ocf - capex,
            "gross_margin_pct": round(gp / rev * 100, 1) if rev else 0,
            "net_margin_pct": round(ni / rev * 100, 1) if rev else 0,
        }
        q_inc = (d.get("Financials") or {}).get("Income_Statement", {}).get("quarterly") or {}
        q_cf = (d.get("Financials") or {}).get("Cash_Flow", {}).get("quarterly") or {}
        price_data = _price_store.get(symbol) or []
        ttm = _build_ttm_window(
            q_inc, q_cf, shares_stats, shares_out, price_data, trailing_years=1,
            highlights=_merged_highlights(d),
        )
        return _eodhd_display_metrics([latest_row], ttm, _merged_highlights(d))
    except Exception:
        return None


_CHART_MONEY_SCALARS = (
    "revenue_usd", "revenue_b",
    "net_income_usd", "net_income_b",
    "op_income_usd", "op_income_b",
    "ocf_usd", "ocf_b",
    "capex_usd", "capex_b",
    "fcf_usd", "fcf_b",
    "owner_earnings_usd", "owner_earnings_b",
)


def _statement_currency(d: dict) -> str:
    """Currency on filed income statements (may differ from ADR General.CurrencyCode)."""
    inc_y = (d.get("Financials") or {}).get("Income_Statement", {}).get("yearly") or {}
    for k in sorted(inc_y.keys(), reverse=True):
        c = (inc_y[k].get("currency_symbol") or "").strip().upper()
        if c:
            return c
    return ((d.get("General") or {}).get("CurrencyCode") or "USD").strip().upper()


_FX_TO_USD_CACHE: dict[str, tuple[float, float]] = {}


def _local_to_usd_factor(ccy: str) -> tuple[float, str | None]:
    """Multiply local-currency amounts by factor to get USD (e.g. TWD × 0.0317)."""
    ccy = (ccy or "USD").strip().upper()
    if ccy in ("USD", ""):
        return 1.0, None
    now = time.time()
    cached = _FX_TO_USD_CACHE.get(ccy)
    if cached and now - cached[1] < 12 * 3600:
        return cached[0], f"Financials converted from {ccy} to USD"

    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    factor = 0.0
    if api_key:
        try:
            resp = _req.get(
                f"https://eodhd.com/api/real-time/{ccy}USD.FOREX",
                params={"api_token": api_key, "fmt": "json"},
                timeout=12,
            )
            if resp.status_code == 200:
                factor = _safe_float((resp.json() or {}).get("close"))
        except Exception:
            factor = 0.0
    if factor <= 0:
        fallbacks = {"TWD": 0.0317, "SEK": 0.095, "NOK": 0.092, "DKK": 0.14, "KRW": 0.00072}
        factor = fallbacks.get(ccy, 0.0)
    if factor <= 0:
        return 1.0, None
    _FX_TO_USD_CACHE[ccy] = (factor, now)
    return factor, f"Financials converted from {ccy} to USD (EODHD {ccy}USD)"


def _looks_like_local_ccy_amount(usd_val: float | None, threshold: float = 250e9) -> bool:
    """Values above ~250B USD are usually local currency (TWD/SEK) mislabeled."""
    return bool(usd_val and usd_val > threshold)


def _recompute_chart_per_share_from_usd(row: dict | None, shares_out: float) -> None:
    """After TWD→USD on totals, per-share lines must use converted USD (not local EPS)."""
    if not row or shares_out <= 0:
        return
    ni = row.get("net_income_usd")
    if ni is not None:
        row["eps"] = round(ni / shares_out, 4)
    oe = row.get("owner_earnings_usd")
    if oe is not None:
        row["oeps"] = round(oe / shares_out, 4)


def _scale_chart_money_row(
    row: dict | None,
    factor: float,
    *,
    shares_out: float = 0.0,
) -> None:
    """Convert statement currency → USD; skip fields already in USD scale (common on ADRs)."""
    if not row or factor == 1.0:
        return
    rev = row.get("revenue_usd")
    ni = row.get("net_income_usd")
    convert_rev = _looks_like_local_ccy_amount(rev)
    convert_ni = _looks_like_local_ccy_amount(ni) and not (
        ni and rev and ni < 250e9 and rev > 500e9
    )
    field_groups = []
    if convert_rev:
        field_groups.extend(("revenue_usd", "revenue_b", "op_income_usd", "op_income_b",
                             "ocf_usd", "ocf_b", "capex_usd", "capex_b", "fcf_usd", "fcf_b",
                             "owner_earnings_usd", "owner_earnings_b"))
    if convert_ni:
        field_groups.extend(("net_income_usd", "net_income_b"))
    for key in field_groups:
        if key.endswith("_usd") and row.get(key) is not None:
            row[key] = row[key] * factor
        elif key.endswith("_b") and row.get(key) is not None:
            row[key] = round(row[key] * factor, 2)
    if convert_rev or convert_ni:
        _recompute_chart_per_share_from_usd(row, shares_out)


def _scale_chart_revenue_estimate(est: dict, factor: float) -> None:
    """Revenue estimates from EODHD are usually in listing currency; EPS/NI est. often USD."""
    if not est or factor == 1.0:
        return
    rev = est.get("revenue_usd")
    if rev:
        est["revenue_usd"] = rev * factor
        est["revenue_b"] = round(est["revenue_usd"] / 1e9, 2)
    # earningsEstimateAvg is USD/ADR share; SharesOutstanding is often local — drop bogus NI est.
    if est.get("eps"):
        est.pop("net_income_usd", None)
        est.pop("net_income_b", None)


def _sanitize_revenue_estimate(rev_est: float | None, ref_rev: float | None) -> float | None:
    """Fix EODHD revenueEstimateAvg when it is clearly not USD (common on dual-listed ADRs).

    E.g. GFI: EODHD ~214B vs ~11B USD consensus — ~214B ZAR / ~18 ≈ 11.9B USD.
    """
    if not rev_est or rev_est <= 0:
        return None
    if not ref_rev or ref_rev <= 0:
        return rev_est
    ratio = rev_est / ref_rev
    if 0.2 <= ratio <= 3.0:
        return rev_est
    for divisor in (18.5, 18.0, 17.5, 19.0, 16.0):
        fixed = rev_est / divisor
        if 0.2 <= fixed / ref_rev <= 3.0:
            return fixed
    return None


def _historical_fiscal_years(history: list[dict]) -> set[int]:
    years: set[int] = set()
    for row in history:
        fy = row.get("fiscal_year")
        if fy is not None:
            try:
                years.add(int(fy))
                continue
            except (ValueError, TypeError):
                pass
        try:
            years.add(int(str(row.get("year", ""))[:4]))
        except (ValueError, TypeError):
            pass
    return years


def _quarter_chart_label(period_end: str) -> str:
    try:
        d = datetime.strptime(str(period_end)[:10], "%Y-%m-%d")
        q = (d.month - 1) // 3 + 1
        return f"Q{q} '{d.strftime('%y')}"
    except (TypeError, ValueError):
        return str(period_end)[:7]


def _price_on_or_before(price_by_date: dict, period_end: str, lookback_days: int = 10) -> float:
    if not price_by_date or not period_end:
        return 0.0
    try:
        end = datetime.strptime(str(period_end)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return 0.0
    from datetime import timedelta as _td

    for d_off in range(lookback_days + 1):
        d_str = (end - _td(days=d_off)).strftime("%Y-%m-%d")
        px = _safe_float(price_by_date.get(d_str))
        if px > 0:
            return px
    return 0.0


def _fundamentals_period_row(
    inc: dict,
    cf: dict,
    *,
    period_end: str,
    label: str,
    fiscal_year: int | None,
    shares_default: float,
    price_by_date: dict | None = None,
    eps_periods: int = 1,
) -> dict:
    rev = _safe_float(inc.get("totalRevenue"))
    ni = _safe_float(inc.get("netIncome"))
    op = _safe_float(inc.get("operatingIncome") or inc.get("ebit"))
    ocf = _safe_float(cf.get("totalCashFromOperatingActivities"))
    capex = abs(_safe_float(cf.get("capitalExpenditures")))
    sbc = _safe_float(cf.get("stockBasedCompensation"))
    sh = _safe_float(
        inc.get("weightedAverageShsOutDil")
        or inc.get("weightedAverageShsOut")
    ) or shares_default or 1.0
    eps = _safe_float(inc.get("dilutedEPS"))
    if eps <= 0 and sh > 0 and ni != 0:
        eps = ni / sh
    fcf = ocf - capex
    oe = ocf - capex - sbc
    oeps = oe / sh if sh else 0.0
    cor = _safe_float(inc.get("costOfRevenue"))
    gp = _eodhd_adjust_gross_profit(rev, _safe_float(inc.get("grossProfit")), cor)
    row = {
        "period_end": period_end,
        "year": label,
        "fiscal_year": fiscal_year,
        "revenue_usd": rev,
        "revenue_b": round(rev / 1e9, 2),
        "net_income_usd": ni,
        "net_income_b": round(ni / 1e9, 2),
        "op_income_usd": op,
        "op_income_b": round(op / 1e9, 2),
        "ocf_usd": ocf,
        "ocf_b": round(ocf / 1e9, 2),
        "capex_usd": capex,
        "capex_b": round(capex / 1e9, 2),
        "fcf_usd": fcf,
        "fcf_b": round(fcf / 1e9, 2),
        "owner_earnings_usd": oe,
        "owner_earnings_b": round(oe / 1e9, 2),
        "eps": round(eps, 4),
        "oeps": round(oeps, 4),
        "gross_margin_pct": round(gp / rev * 100, 1) if rev else 0,
        "net_margin_pct": round(ni / rev * 100, 1) if rev else 0,
        "pe_ratio": None,
        "ye_price": None,
    }
    if price_by_date:
        px = _price_on_or_before(price_by_date, period_end)
        if px > 0 and eps > 0:
            row["pe_ratio"] = round(px / (eps * eps_periods), 1)
            row["ye_price"] = round(px, 2)
    return row


def _build_annual_history(
    annual: dict,
    bs_ann: dict,
    cf_ann: dict,
    shares_out: float,
    price_by_date: dict | None,
    *,
    max_years: int = 15,
) -> list[dict]:
    history: list[dict] = []
    for yr in sorted(annual.keys())[-max_years:]:
        inc = annual[yr]
        bs = bs_ann.get(yr, {})
        cf = cf_ann.get(yr, {})
        eq = _safe_float(bs.get("totalStockholderEquity")) or 1.0
        sh = _safe_float(bs.get("commonStockSharesOutstanding"))
        if not sh:
            sh = _safe_float(
                inc.get("weightedAverageShsOutDil") or inc.get("weightedAverageShsOut")
            )
        if not sh:
            sh = shares_out or 1.0
        row = _fundamentals_period_row(
            inc, cf,
            period_end=yr,
            label=yr[:4],
            fiscal_year=int(yr[:4]) if yr[:4].isdigit() else None,
            shares_default=sh,
            price_by_date=price_by_date,
        )
        row["roe_pct"] = round(_safe_float(row["net_income_usd"]) / eq * 100, 1) if eq else 0
        if price_by_date and row.get("pe_ratio") is None:
            eps_val = row.get("eps", 0)
            ye_price = _price_on_or_before(price_by_date, f"{yr[:4]}-12-31", lookback_days=12)
            if ye_price > 0 and eps_val and eps_val > 0:
                row["pe_ratio"] = round(ye_price / eps_val, 1)
                row["ye_price"] = round(ye_price, 2)
        history.append(row)
    return history


def _build_quarterly_history(
    q_inc: dict,
    q_cf: dict,
    shares_out: float,
    price_by_date: dict | None,
    *,
    max_quarters: int = 80,
) -> list[dict]:
    keys = sorted(q_inc.keys())[-max_quarters:]
    history: list[dict] = []
    for period_end in keys:
        inc = q_inc[period_end]
        cf = q_cf.get(period_end, {})
        try:
            fiscal_year = int(str(period_end)[:4])
        except (TypeError, ValueError):
            fiscal_year = None
        history.append(
            _fundamentals_period_row(
                inc,
                cf,
                period_end=period_end,
                label=_quarter_chart_label(period_end),
                fiscal_year=fiscal_year,
                shares_default=shares_out,
                price_by_date=price_by_date,
                eps_periods=4,
            )
        )
    return history


def _drop_estimates_for_reported_years(
    history: list[dict], estimates: list[dict]
) -> list[dict]:
    """Remove FYxxxxE rows when filed annuals for that fiscal year are already in history."""
    reported = _historical_fiscal_years(history)
    if not reported:
        return estimates
    return [
        e for e in estimates
        if int(e.get("fiscal_year") or 0) not in reported
    ]


def _prune_implausible_revenue_estimates(
    estimates: list[dict],
    ttm: dict | None,
    history: list[dict],
) -> None:
    """Drop forward revenue bars that are far below TTM (bad EODHD rows, e.g. cyclical energy)."""
    ref = _safe_float((ttm or {}).get("revenue_usd"))
    if not ref and history:
        ref = _safe_float(history[0].get("revenue_usd"))
    if not ref:
        return
    for est in estimates:
        rev = _safe_float(est.get("revenue_usd"))
        if rev > 0 and rev < ref * 0.35:
            est.pop("revenue_usd", None)
            est["revenue_b"] = None


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
            c = get_company(sym)
            eodhd_sym = _eodhd_ticker(sym, c) or f"{sym}.US"
            r = _req.get(
                f"https://eodhd.com/api/fundamentals/{eodhd_sym}",
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


_FYE_MONTH = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_ABBR = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fiscal_year_end_month(general: dict) -> int:
    raw = (general.get("FiscalYearEnd") or "December").strip().lower()
    return _FYE_MONTH.get(raw, 12)


def _quarter_report_label(period_end: str, form: str) -> str:
    try:
        y = period_end[:4]
        m = int(period_end[5:7])
        abbr = _MONTH_ABBR[m] if 1 <= m <= 12 else period_end[5:7]
        return f"{form} · {abbr} '{y[2:]}"
    except (ValueError, IndexError, TypeError):
        return form


_SEC_SUBMISSIONS_CACHE: dict[str, tuple[float, dict]] = {}
_SEC_SUBMISSIONS_TTL = 86400.0


def _sec_cik_int(cik: str) -> str:
    raw = str(cik or "").strip().lstrip("0")
    return raw or "0"


def _sec_edgar_document_url(cik: str, accession: str, primary_document: str) -> str:
    """Direct link to the primary filing HTML (10-Q / 10-K)."""
    acc = str(accession or "").replace("-", "")
    doc = str(primary_document or "").strip()
    if not acc or not doc:
        return ""
    return f"https://www.sec.gov/Archives/edgar/data/{_sec_cik_int(cik)}/{acc}/{doc}"


def _fetch_sec_submissions(cik: str) -> dict | None:
    cik10 = str(cik or "").strip().zfill(10)
    if not cik10.strip("0"):
        return None
    now = time.time()
    cached = _SEC_SUBMISSIONS_CACHE.get(cik10)
    if cached and (now - cached[0]) < _SEC_SUBMISSIONS_TTL:
        return cached[1]
    ua = (os.getenv("SEC_EDGAR_USER_AGENT") or "companyData equity-research contact@example.com").strip()
    try:
        r = _req.get(
            f"https://data.sec.gov/submissions/CIK{cik10}.json",
            headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            _SEC_SUBMISSIONS_CACHE[cik10] = (now, data)
            return data
    except Exception:
        pass
    return None


def _match_sec_filing(
    submissions: dict,
    form: str,
    filing_date: str,
    *,
    max_day_slop: int = 14,
) -> tuple[str, str] | None:
    """Map EODHD filing_date + form to SEC accession + primary document."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primaries = recent.get("primaryDocument") or []
    if not forms or not dates:
        return None
    target_s = str(filing_date or "")[:10]
    if len(target_s) < 10:
        return None
    try:
        target = datetime.strptime(target_s, "%Y-%m-%d").date()
    except ValueError:
        return None

    def _row(i: int) -> tuple[str, str] | None:
        if i >= len(accessions) or i >= len(primaries):
            return None
        acc = str(accessions[i] or "").strip()
        doc = str(primaries[i] or "").strip()
        if acc and doc:
            return acc, doc
        return None

    for i, f in enumerate(forms):
        if f != form or i >= len(dates):
            continue
        if str(dates[i])[:10] == target_s:
            hit = _row(i)
            if hit:
                return hit

    best: tuple[str, str] | None = None
    best_delta = max_day_slop + 1
    for i, f in enumerate(forms):
        if f != form or i >= len(dates):
            continue
        try:
            fd = datetime.strptime(str(dates[i])[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = abs((fd - target).days)
        if delta <= max_day_slop and delta < best_delta:
            hit = _row(i)
            if hit:
                best_delta = delta
                best = hit
    return best


def _sec_edgar_browse_url(cik: str, form: str, filing_date: str) -> str:
    """Fallback: EDGAR filing list filtered around filing_date."""
    cik_str = str(cik).strip()
    if not cik_str:
        return ""
    try:
        dt = datetime.strptime(str(filing_date)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return f"https://www.sec.gov/edgar/browse/?CIK={_sec_cik_int(cik_str)}"
    datea = (dt - timedelta(days=7)).strftime("%Y%m%d")
    dateb = (dt + timedelta(days=7)).strftime("%Y%m%d")
    return (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik_str}&type={form}&dateb={dateb}&datea={datea}&owner=exclude&count=20"
    )


def _sec_edgar_filing_url(
    cik: str,
    form: str,
    filing_date: str,
    submissions: dict | None = None,
) -> str:
    """Prefer direct 10-Q/10-K document; fall back to browse-edgar."""
    cik_str = str(cik).strip()
    if not cik_str:
        return ""
    if filing_date:
        sub = submissions if submissions is not None else _fetch_sec_submissions(cik_str)
        if sub:
            match = _match_sec_filing(sub, form, filing_date)
            if match:
                doc_url = _sec_edgar_document_url(cik_str, match[0], match[1])
                if doc_url:
                    return doc_url
        return _sec_edgar_browse_url(cik_str, form, filing_date)
    return f"https://www.sec.gov/edgar/browse/?CIK={_sec_cik_int(cik_str)}"


def _build_quarterly_report_events(fundamentals: dict | None) -> list[dict]:
    """Quarterly SEC filings + earnings dates for price-chart markers."""
    if not fundamentals or not isinstance(fundamentals, dict):
        return []
    gen = fundamentals.get("General") or {}
    cik = str(gen.get("CIK") or "").strip()
    if not cik:
        return []
    fye_month = _fiscal_year_end_month(gen)
    q_inc = (fundamentals.get("Financials") or {}).get("Income_Statement", {}).get("quarterly") or {}
    earn_hist = (fundamentals.get("Earnings") or {}).get("History") or {}

    earn_by_period: dict[str, str] = {}
    for key, row in earn_hist.items():
        if not isinstance(row, dict):
            continue
        pe = str(row.get("date") or key)[:10]
        rd = str(row.get("reportDate") or "")[:10]
        if pe and rd:
            earn_by_period[pe] = rd

    submissions = _fetch_sec_submissions(cik)

    events: list[dict] = []
    for period_key, inc in q_inc.items():
        if not isinstance(inc, dict):
            continue
        period_end = str(inc.get("date") or period_key)[:10]
        if len(period_end) < 10:
            continue
        filing_date = str(inc.get("filing_date") or "")[:10]
        if filing_date and len(filing_date) < 10:
            filing_date = ""
        try:
            period_month = int(period_end[5:7])
        except ValueError:
            period_month = 0
        form = "10-K" if period_month == fye_month else "10-Q"
        earnings_date = earn_by_period.get(period_end) or None
        marker_date = filing_date or earnings_date or period_end
        sec_url = _sec_edgar_filing_url(cik, form, filing_date, submissions) if filing_date else (
            f"https://www.sec.gov/edgar/browse/?CIK={_sec_cik_int(cik)}"
        )
        events.append({
            "period_end": period_end,
            "filing_date": filing_date or None,
            "earnings_date": earnings_date,
            "marker_date": marker_date,
            "form": form,
            "label": _quarter_report_label(period_end, form),
            "sec_url": sec_url,
        })

    events.sort(key=lambda e: e.get("marker_date") or "")
    return events


def _empty_history_payload(message: str) -> dict:
    return {
        "history":         [],
        "annual_history":  [],
        "history_cadence": "quarterly",
        "quarterly_reports": [],
        "analyst_ratings": None,
        "price":           0.0,
        "eps_ttm":         0.0,
        "pe_ttm":          0.0,
        "market_cap_b":    0.0,
        "market_cap_usd":  0.0,
        "market_cap_fmt":  "$0",
        "price_chart_1y":  [],
        "partial":         True,
        "message":         message,
    }


_price_store = PriceStore(PROJECT_ROOT / "outputs" / "fundamentals.db")
_LIVE_QUOTE_CACHE: dict[str, tuple[dict, float]] = {}
_LIVE_POLL_OPEN_SEC = 5
_LIVE_QUOTE_TTL_OPEN_SEC = 4.0
_LIVE_QUOTE_TTL_CLOSED_SEC = 60.0
_STALE_QUOTE_SEC = 20 * 60
_ET = ZoneInfo("America/New_York")

# Cash session windows (local exchange time; no holiday calendar).
_EXCHANGE_HOURS: dict[str, dict] = {
    "US": {
        "tz": "America/New_York",
        "pre": (4, 0),
        "open": (9, 30),
        "close": (16, 0),
        "after_end": (20, 0),
    },
    "OL": {"tz": "Europe/Oslo", "open": (9, 0), "close": (16, 25)},
    "ST": {"tz": "Europe/Stockholm", "open": (9, 0), "close": (17, 30)},
    "CO": {"tz": "Europe/Copenhagen", "open": (9, 0), "close": (17, 0)},
    "HE": {"tz": "Europe/Helsinki", "open": (10, 0), "close": (18, 30)},
}


def _listing_exchange(c: dict | None, symbol: str) -> str:
    sym = (_parse_symbol(symbol) or "").upper()
    if "." in sym:
        suf = sym.rsplit(".", 1)[-1]
        if suf in ("US", "OL", "ST", "CO", "HE"):
            return suf
    return _normalize_exchange_code((c or {}).get("exchange") or (c or {}).get("eodhd_exchange") or "US")


def _is_us_equity_listing(c: dict | None, symbol: str) -> bool:
    sym = (_parse_symbol(symbol) or "").upper()
    if "." in sym:
        suf = sym.rsplit(".", 1)[-1]
        if suf in ("OL", "ST", "CO", "HE", "L", "PA", "MI", "TO", "V"):
            return False
    ex = _normalize_exchange_code((c or {}).get("exchange") or (c or {}).get("eodhd_exchange") or "US")
    return ex == "US"


def _market_session_now(exchange: str = "US", when: datetime | None = None) -> str:
    """Exchange-local session bucket (no holiday calendar)."""
    meta = _EXCHANGE_HOURS.get(exchange) or _EXCHANGE_HOURS["US"]
    tz = ZoneInfo(meta["tz"])
    now = when or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if exchange == "US":
        if dt_time(meta["pre"][0], meta["pre"][1]) <= t < dt_time(meta["open"][0], meta["open"][1]):
            return "pre_market"
        if dt_time(meta["open"][0], meta["open"][1]) <= t < dt_time(meta["close"][0], meta["close"][1]):
            return "regular"
        if dt_time(meta["close"][0], meta["close"][1]) <= t < dt_time(meta["after_end"][0], meta["after_end"][1]):
            return "after_hours"
        return "closed"
    o = dt_time(meta["open"][0], meta["open"][1])
    c = dt_time(meta["close"][0], meta["close"][1])
    if o <= t < c:
        return "regular"
    return "closed"


def _us_market_session_now(when: datetime | None = None) -> str:
    return _market_session_now("US", when)


def _quote_tz(exchange: str) -> ZoneInfo:
    meta = _EXCHANGE_HOURS.get(exchange) or _EXCHANGE_HOURS["US"]
    return ZoneInfo(meta["tz"])


def _format_quote_as_of(value: object, exchange: str) -> str | None:
    """Normalize API timestamps to exchange-local ISO for display."""
    if value in (None, ""):
        return None
    tz = _quote_tz(exchange)
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(int(value), tz=ZoneInfo("UTC"))
        else:
            s = str(value).strip()
            if s.isdigit():
                dt = datetime.fromtimestamp(int(s), tz=ZoneInfo("UTC"))
            else:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)[:19]


def _quote_age_seconds(as_of: object) -> float | None:
    if as_of in (None, ""):
        return None
    try:
        if isinstance(as_of, (int, float)):
            ts = float(as_of)
        else:
            s = str(as_of).strip()
            if s.isdigit():
                ts = float(s)
            else:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                ts = dt.timestamp()
        return max(0.0, time.time() - ts)
    except (TypeError, ValueError, OSError):
        return None


def _apply_quote_session_truth(quote: dict, exchange: str) -> dict:
    """Align session labels with listing hours and quote freshness (avoid false Live)."""
    cal = _market_session_now(exchange)
    age = _quote_age_seconds(quote.get("as_of"))
    stale = bool(quote.get("stale")) or quote.get("source") == "eod_daily"

    if stale or (age is not None and age > _STALE_QUOTE_SEC):
        quote = {**quote, "session": "closed", "market_open": False, "stale": True}
    elif cal == "closed":
        quote = {**quote, "session": "closed", "market_open": False}
    elif cal in ("pre_market", "after_hours"):
        quote = {**quote, "session": cal, "market_open": True}
    else:
        quote = {**quote, "session": "regular", "market_open": True}

    if quote.get("stale"):
        quote["session_label"] = "Last trade"
    elif quote.get("session") == "closed":
        quote["session_label"] = "Closed"
    elif quote.get("session") == "pre_market":
        quote["session_label"] = "Pre-market"
    elif quote.get("session") == "after_hours":
        quote["session_label"] = "After-hours"
    else:
        quote["session_label"] = "Live"
    return quote


def _ms_to_iso(ms: object) -> str | None:
    if ms in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=_ET).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _eod_previous_close_from_store(symbol: str) -> float:
    prices = _price_store.get(symbol) or []
    if len(prices) < 2:
        return 0.0
    return _safe_float(prices[-2].get("close"))


def _us_quote_session_split_fields(reg: float, eth: float, prev: float) -> dict:
    """RTH last vs prior close (At close); ETH vs RTH last (After-hours) when they differ."""
    regular_change = regular_change_pct = extended_change = extended_change_pct = None
    if reg > 0 and prev > 0:
        regular_change = reg - prev
        regular_change_pct = (regular_change / prev) * 100.0
    if eth > 0 and reg > 0:
        extended_change = eth - reg
        extended_change_pct = (extended_change / reg) * 100.0
    show_session_split = False
    if regular_change is not None and extended_change is not None and reg > 0:
        # Min 0.01% or $0.02 — smaller moves round to "+0.00% (+0.00)" in the UI
        if abs(extended_change_pct) >= 0.01 or abs(extended_change) >= 0.02:
            show_session_split = True
    return {
        "regular_change": regular_change,
        "regular_change_pct": regular_change_pct,
        "extended_change": extended_change,
        "extended_change_pct": extended_change_pct,
        "show_session_split": show_session_split,
    }


def _recompute_us_session_split(quote: dict) -> dict:
    """Derive At close / After-hours lines from regular, extended, and prior close."""
    prev = _safe_float(quote.get("previous_close"))
    reg = _safe_float(quote.get("regular_close"))
    eth = _safe_float(quote.get("extended_price"))
    split = _us_quote_session_split_fields(reg, eth, prev)
    regular_change = split["regular_change"]
    regular_change_pct = split["regular_change_pct"]
    extended_change = split["extended_change"]
    extended_change_pct = split["extended_change_pct"]
    show_session_split = split["show_session_split"]
    out = {**quote}
    out["regular_change"] = round(regular_change, 4) if regular_change is not None else None
    out["regular_change_pct"] = round(regular_change_pct, 3) if regular_change_pct is not None else None
    out["extended_change"] = round(extended_change, 4) if extended_change is not None else None
    out["extended_change_pct"] = round(extended_change_pct, 3) if extended_change_pct is not None else None
    out["show_session_split"] = show_session_split
    return out


def _backfill_us_quote_previous_close(symbol: str, quote: dict) -> dict:
    if quote.get("source") != "eodhd_us_quote":
        return quote
    if _safe_float(quote.get("previous_close")) > 0:
        return quote
    prev = _eod_previous_close_from_store(symbol)
    if prev <= 0:
        return quote
    return _recompute_us_session_split({**quote, "previous_close": round(prev, 4)})


def _parse_us_quote_delayed(row: dict, session: str) -> dict | None:
    """Build display quote from EODHD us-quote-delayed row (incl. extended hours)."""
    reg = _safe_float(row.get("lastTradePrice"))
    eth = _safe_float(row.get("ethPrice"))
    prev = _safe_float(
        row.get("previousClosePrice")
        or row.get("previousClose")
        or row.get("previous_close")
    )
    if prev <= 0 and reg > 0:
        chg = _safe_float(row.get("change"))
        if chg != 0.0:
            prev = reg - chg
    reg_ms = int(_safe_float(row.get("lastTradeTime")) or 0)
    eth_ms = int(_safe_float(row.get("ethTime")) or 0)

    use_extended = False
    if session in ("pre_market", "after_hours") and eth > 0:
        use_extended = True
    elif session == "closed" and eth > 0 and eth_ms > reg_ms > 0:
        use_extended = True

    if use_extended:
        price = eth
        ref = reg if reg > 0 else prev
        disp_session = session if session != "closed" else "after_hours"
        as_of = _ms_to_iso(eth_ms) or _ms_to_iso(row.get("timestamp"))
    else:
        price = reg if reg > 0 else prev
        ref = prev if prev > 0 else reg
        disp_session = "regular" if session == "regular" else "closed"
        as_of = _ms_to_iso(reg_ms) or _ms_to_iso(row.get("timestamp"))

    if price <= 0:
        return None

    chg = _safe_float(row.get("change"))
    chg_p = _safe_float(row.get("changePercent"))
    if use_extended and ref > 0:
        chg = price - ref
        chg_p = (chg / ref) * 100.0
    elif (chg == 0.0 or chg_p == 0.0) and ref > 0:
        chg = price - ref
        chg_p = (chg / ref) * 100.0

    split = _us_quote_session_split_fields(reg, eth, prev)
    regular_change = split["regular_change"]
    regular_change_pct = split["regular_change_pct"]
    extended_change = split["extended_change"]
    extended_change_pct = split["extended_change_pct"]
    show_session_split = split["show_session_split"]

    if not show_session_split and prev > 0:
        if abs(chg) < 1e-9 and abs(chg_p) < 1e-9:
            chg = reg - prev if reg > 0 else price - prev
            chg_p = (chg / prev) * 100.0
        elif reg > 0:
            chg = reg - prev
            chg_p = (chg / prev) * 100.0

    is_live = disp_session in ("regular", "pre_market", "after_hours")
    return {
        "price": round(price, 4),
        "regular_close": round(reg, 4) if reg > 0 else None,
        "extended_price": round(eth, 4) if eth > 0 else None,
        "previous_close": round(prev, 4) if prev > 0 else None,
        "change": round(chg, 4),
        "change_pct": round(chg_p, 3),
        "regular_change": round(regular_change, 4) if regular_change is not None else None,
        "regular_change_pct": round(regular_change_pct, 3) if regular_change_pct is not None else None,
        "extended_change": round(extended_change, 4) if extended_change is not None else None,
        "extended_change_pct": round(extended_change_pct, 3) if extended_change_pct is not None else None,
        "show_session_split": show_session_split,
        "bid": round(_safe_float(row.get("bidPrice")), 4) or None,
        "ask": round(_safe_float(row.get("askPrice")), 4) or None,
        "volume": int(_safe_float(row.get("volume")) or 0),
        "eth_volume": int(_safe_float(row.get("ethVolume")) or 0),
        "as_of": as_of,
        "session": disp_session,
        "market_open": is_live,
        "change_label": "vs close" if use_extended else "today",
        "source": "eodhd_us_quote",
        "stale": False,
        "pe_snapshot": round(_safe_float(row.get("pe")), 2) or None,
        "market_cap_usd_api": _safe_float(row.get("marketCap")) or None,
    }


def _fetch_eodhd_us_quote_delayed(symbol: str) -> dict | None:
    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    if not api_key:
        return None
    c = get_company(symbol)
    eodhd_sym = _eodhd_ticker(symbol, c) or f"{_parse_symbol(symbol)}.US"
    try:
        resp = _req.get(
            "https://eodhd.com/api/us-quote-delayed",
            params={"api_token": api_key, "s": eodhd_sym, "fmt": "json"},
            timeout=12,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json() or {}
        row = (payload.get("data") or {}).get(eodhd_sym)
        if not row and payload.get("data"):
            row = next(iter(payload["data"].values()), None)
        if not isinstance(row, dict):
            return None
        return _parse_us_quote_delayed(row, _us_market_session_now())
    except Exception:
        return None


def _live_quote_cache_ttl(session: str) -> float:
    if session in ("regular", "pre_market", "after_hours"):
        return _LIVE_QUOTE_TTL_OPEN_SEC
    return _LIVE_QUOTE_TTL_CLOSED_SEC


def _parse_eodhd_realtime_quote(raw: object, exchange: str = "US") -> dict | None:
    """Normalize EODHD real-time JSON to a small quote dict."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        return None
    close = _safe_float(raw.get("close"))
    if close <= 0:
        close = _safe_float(raw.get("adjusted_close"))
    prev = _safe_float(raw.get("previousClose") or raw.get("previous_close"))
    if close <= 0 and prev > 0:
        close = prev
    if close <= 0:
        return None
    chg = _safe_float(raw.get("change"))
    chg_p = _safe_float(raw.get("change_p"))
    if chg == 0.0 and prev > 0:
        chg = close - prev
    if chg_p == 0.0 and prev > 0:
        chg_p = (chg / prev) * 100.0
    as_of = _format_quote_as_of(raw.get("timestamp"), exchange)
    session = _market_session_now(exchange)
    return {
        "price": round(close, 4),
        "previous_close": round(prev, 4) if prev > 0 else None,
        "change": round(chg, 4),
        "change_pct": round(chg_p, 3),
        "open": round(_safe_float(raw.get("open")), 4) or None,
        "high": round(_safe_float(raw.get("high")), 4) or None,
        "low": round(_safe_float(raw.get("low")), 4) or None,
        "volume": int(_safe_float(raw.get("volume")) or 0),
        "as_of": as_of,
        "code": raw.get("code"),
        "session": session,
        "market_open": session in ("regular", "pre_market", "after_hours"),
        "change_label": "today",
        "source": "eodhd_realtime",
        "stale": False,
    }


def _fetch_eodhd_live_quote(symbol: str) -> dict | None:
    """EODHD real-time endpoint (delay depends on subscription tier)."""
    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    if not api_key:
        return None
    c = get_company(symbol)
    eodhd_sym = _eodhd_ticker(symbol, c) or f"{_parse_symbol(symbol)}.US"
    try:
        resp = _req.get(
            f"https://eodhd.com/api/real-time/{eodhd_sym}",
            params={"api_token": api_key, "fmt": "json"},
            timeout=12,
        )
        if resp.status_code != 200:
            return None
        ex = _listing_exchange(c, symbol)
        return _parse_eodhd_realtime_quote(resp.json(), exchange=ex)
    except Exception:
        return None


def _live_quote_fallback_from_eod(symbol: str) -> dict | None:
    """When real-time is unavailable, use the latest stored daily close."""
    prices = _price_store.get(symbol) or _fetch_full_price_history(symbol)
    if not prices:
        return None
    last = prices[-1]
    prev = prices[-2] if len(prices) > 1 else None
    close = float(last.get("close") or 0)
    if close <= 0:
        return None
    prev_c = float(prev.get("close") or 0) if prev else 0.0
    chg = close - prev_c if prev_c > 0 else 0.0
    chg_p = (chg / prev_c * 100.0) if prev_c > 0 else 0.0
    return {
        "price": round(close, 4),
        "previous_close": round(prev_c, 4) if prev_c > 0 else None,
        "change": round(chg, 4),
        "change_pct": round(chg_p, 3),
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "volume": int(last.get("volume") or 0),
        "as_of": last.get("date"),
        "code": None,
        "stale": True,
        "session": "closed",
        "market_open": False,
        "change_label": "today",
        "source": "eod_daily",
    }


def _enrich_live_quote_out(quote: dict, sym: str, exchange: str) -> dict:
    c = get_company(sym) or {}
    m = c.get("financial_metrics") or {}
    price = float(quote["price"])
    shares = _safe_float(m.get("diluted_shares") or m.get("shares_outstanding"))
    if shares <= 0:
        try:
            d = _get_fundamentals(sym)
            if d:
                shares = _safe_float((d.get("SharesStats") or {}).get("SharesOutstanding"))
        except Exception:
            shares = 0.0

    eps_ttm = _safe_float(m.get("eps_diluted"))
    if eps_ttm <= 0:
        try:
            h = _merged_highlights(_get_fundamentals(sym) or {})
            eps_ttm = _safe_float(h.get("EarningsShare"))
        except Exception:
            pass

    out = {**quote, "symbol": sym, "shares_outstanding": shares if shares > 0 else None}
    mcap_api = _safe_float(quote.get("market_cap_usd_api"))
    if mcap_api > 0:
        out["market_cap_usd"] = mcap_api
        out["market_cap_fmt"] = _format_usd_compact(mcap_api)
    elif shares > 0:
        mcap = price * shares
        out["market_cap_usd"] = mcap
        out["market_cap_fmt"] = _format_usd_compact(mcap)
    pe_snap = quote.get("pe_snapshot")
    if pe_snap and pe_snap > 0:
        out["pe_ttm"] = pe_snap
    elif eps_ttm > 0:
        out["pe_ttm"] = round(price / eps_ttm, 2)
        out["eps_ttm"] = round(eps_ttm, 4)
    out["poll_seconds"] = _LIVE_POLL_OPEN_SEC if quote.get("market_open") else 60
    if not out.get("session_label"):
        sess = str(quote.get("session") or "closed")
        out["session_label"] = {
            "regular": "Live",
            "pre_market": "Pre-market",
            "after_hours": "After-hours",
            "closed": "Closed",
        }.get(sess, "Closed")
    return out


def _get_live_quote(symbol: str) -> dict | None:
    sym = (_parse_symbol(symbol) or "").upper()
    if not sym:
        return None
    now = time.time()
    cached = _LIVE_QUOTE_CACHE.get(sym)
    if cached:
        ttl = _live_quote_cache_ttl(str(cached[0].get("session") or "closed"))
        if now - cached[1] < ttl:
            return dict(cached[0])

    c = get_company(sym) or {}
    exchange = _listing_exchange(c, sym)
    quote = None
    if _is_us_equity_listing(c, sym):
        quote = _fetch_eodhd_us_quote_delayed(sym)
    if not quote:
        quote = _fetch_eodhd_live_quote(sym)
    if not quote:
        quote = _live_quote_fallback_from_eod(sym)
    if not quote:
        return None

    quote = _backfill_us_quote_previous_close(sym, quote)
    quote = _apply_quote_session_truth(quote, exchange)
    out = _enrich_live_quote_out(quote, sym, exchange)
    _LIVE_QUOTE_CACHE[sym] = (out, now)
    return out


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


def _intraday_bar_from_raw(p: dict, ts: int) -> dict | None:
    try:
        close = float(p.get("close"))
    except (TypeError, ValueError):
        return None
    if close <= 0:
        return None
    from datetime import timezone

    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    label = dt.strftime("%Y-%m-%d %H:%M")
    try:
        op = float(p.get("open", close))
        hi = float(p.get("high", close))
        lo = float(p.get("low", close))
    except (TypeError, ValueError):
        op, hi, lo = close, close, close
    vol = p.get("volume", 0)
    return {
        "date": label,
        "close": round(close, 4),
        "open": round(op, 4),
        "high": round(hi, 4),
        "low": round(lo, 4),
        "volume": vol,
    }


def _parse_eodhd_intraday(data) -> list:
    """Convert EODHD intraday JSON (list or timestamp-keyed dict) to OHLCV rows."""
    rows: list[dict] = []
    if isinstance(data, dict):
        if not data or data.get("errors"):
            return []
        if all(str(k).isdigit() for k in data.keys()):
            for k in sorted(data.keys(), key=lambda x: int(x)):
                p = data[k]
                if isinstance(p, dict):
                    bar = _intraday_bar_from_raw(p, int(k))
                    if bar:
                        rows.append(bar)
            return rows
        data = [v for v in data.values() if isinstance(v, dict)]
    if not isinstance(data, list):
        return []
    for p in data:
        if not isinstance(p, dict):
            continue
        ts = p.get("datetime")
        if ts is None:
            continue
        bar = _intraday_bar_from_raw(p, int(ts))
        if bar:
            rows.append(bar)
    rows.sort(key=lambda x: x["date"])
    return rows


def _fetch_intraday_1d(symbol: str) -> list:
    """1-minute bars for recent sessions (150–400 points for the 1D chart)."""
    from datetime import timedelta, timezone

    api_key = (os.getenv("EODHD_API_KEY") or "").strip()
    if not api_key:
        return []
    try:
        c = get_company(symbol)
        eodhd_sym = _eodhd_ticker(symbol, c) or f"{symbol}.US"
        now = datetime.now(timezone.utc)
        from_ts = int((now - timedelta(days=4)).timestamp())
        to_ts = int(now.timestamp())
        resp = _req.get(
            f"https://eodhd.com/api/intraday/{eodhd_sym}",
            params={
                "api_token": api_key,
                "fmt": "json",
                "interval": "1m",
                "from": from_ts,
                "to": to_ts,
            },
            timeout=25,
        )
        if resp.status_code != 200:
            return []
        bars = _parse_eodhd_intraday(resp.json())
        if not bars:
            return []
        days = sorted({b["date"][:10] for b in bars})
        for n_days in (2, 3, 4):
            if len(days) < n_days:
                subset = bars
            else:
                keep = set(days[-n_days:])
                subset = [b for b in bars if b["date"][:10] in keep]
            if len(subset) >= _MIN_CHART_POINTS:
                bars = subset
                break
        else:
            bars = subset
        if len(bars) > _MAX_CHART_POINTS:
            return _downsample_prices_evenly(bars, _MAX_CHART_POINTS)
        if len(bars) >= _MIN_CHART_POINTS:
            return bars
        return []
    except Exception:
        return []


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

        c = get_company(symbol)
        eodhd_sym = _eodhd_ticker(symbol, c) or f"{symbol}.US"
        resp = _req.get(
            f"https://eodhd.com/api/eod/{eodhd_sym}",
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


_MIN_CHART_POINTS = 150
_MAX_CHART_POINTS = 400


def _downsample_prices_evenly(prices: list, target: int) -> list:
    """Evenly spaced sample of exactly ``target`` points (first and last bar included)."""
    n = len(prices)
    if n <= target:
        return list(prices)
    if target <= 1:
        return [prices[-1]]
    return [prices[round(i * (n - 1) / (target - 1))] for i in range(target)]


def _apply_price_density(prices: list, density: float) -> list:
    """Return a fraction of points (evenly spaced) for fast chart preview."""
    if not prices or density >= 1.0:
        return list(prices)
    d = max(0.1, min(1.0, float(density)))
    target = max(12, int(len(prices) * d))
    if target >= len(prices):
        return list(prices)
    return _downsample_prices_evenly(prices, target)


def _slice_and_downsample(prices: list, rng: str) -> list:
    """Slice EOD history to a range; keep 200–400 points when enough data exists."""
    from datetime import timedelta
    if not prices:
        return []
    now = datetime.now()
    # Calendar lookback per button (daily bars; 1D stays short — no 200-pt expansion).
    range_days = {
        "1d": 5,
        "1w": 30,
        "1m": 60,
        "3m": 100,
        "6m": 190,
        "1y": 370,
        "3y": 1100,
        "5y": 1830,
        "10y": 3660,
        "max": 999999,
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

    # Short ranges: extend backward until at least _MIN_CHART_POINTS (daily EOD fallback).
    if len(sliced) < _MIN_CHART_POINTS and len(prices) > len(sliced):
        need = _MIN_CHART_POINTS - len(sliced)
        first_idx = len(prices) - len(sliced)
        start_idx = max(0, first_idx - need)
        sliced = prices[start_idx:]

    if len(sliced) > _MAX_CHART_POINTS:
        return _downsample_prices_evenly(sliced, _MAX_CHART_POINTS)
    return sliced


def _chart_prices_for_range(
    all_prices: list, rng: str = "1y", symbol: str | None = None,
) -> list:
    """Slice/downsample bars for a chart range; 1D uses intraday 1m when available."""
    if rng == "1d" and symbol:
        intra = _fetch_intraday_1d(symbol)
        if intra:
            return intra
    if not all_prices:
        return []
    return _slice_and_downsample(all_prices, rng)


@app.route('/api/company/<symbol>/price-history')
def api_company_price_history(symbol):
    """Serve price history from EODHD EOD endpoint with configurable range."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    rng = request.args.get("range", "1y").lower()
    density_raw = request.args.get("density", "1")
    try:
        density_f = float(density_raw)
    except (TypeError, ValueError):
        density_f = 1.0
    try:
        all_prices = _fetch_full_price_history(symbol)
        if not all_prices:
            return jsonify({"error": "No price data", "prices": []}), 200
        prices = _chart_prices_for_range(all_prices, rng, symbol=symbol)
        preview = density_f < 1.0
        if preview:
            prices = _apply_price_density(prices, density_f)
        return jsonify({
            "prices": prices,
            "preview": preview,
            "count": len(prices),
        })
    except Exception as ex:
        return jsonify({"error": str(ex)[:200], "prices": []}), 200


@app.route("/api/company/<symbol>/quote")
def api_company_quote(symbol):
    """Near-live quote (EODHD real-time with short server cache; falls back to last EOD close)."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    q = _get_live_quote(symbol)
    if not q:
        return jsonify({"error": "No quote available", "symbol": symbol}), 200
    return jsonify(q)


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
    """Serve quarterly financial chart series + annual filed FY for metrics (cache-first)."""
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

    price_data = _fetch_full_price_history(symbol)
    price_chart_1y = _chart_prices_for_range(price_data, "1y")
    price_by_date = {p["date"]: p["close"] for p in price_data} if price_data else {}

    annual_history = _build_annual_history(
        annual, bs_ann, cf_ann, shares_out, price_by_date, max_years=15,
    )

    q_inc = d.get("Financials", {}).get("Income_Statement", {}).get("quarterly", {})
    q_cf = d.get("Financials", {}).get("Cash_Flow", {}).get("quarterly", {})
    history = _build_quarterly_history(
        q_inc, q_cf, shares_out, price_by_date, max_quarters=80,
    )
    if not history and annual_history:
        history = annual_history
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
    ref_rev = _safe_float(_hl.get("RevenueTTM"))
    if not ref_rev and ttm:
        ref_rev = _safe_float(ttm.get("revenue_usd"))
    if not ref_rev and annual_history:
        ref_rev = _safe_float(annual_history[-1].get("revenue_usd"))
    elif not ref_rev and history:
        ref_rev = _safe_float(history[-1].get("revenue_usd"))
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
        rev_est = _sanitize_revenue_estimate(
            _safe_float(t.get("revenueEstimateAvg")) or None, ref_rev or None
        )
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
    estimates = _drop_estimates_for_reported_years(annual_history, estimates)

    co = get_company(symbol) or {}
    analyst = _fmt_analyst(_analyst_ratings_for_company({**co, "symbol": symbol}) or {})
    h = _merged_highlights(d)
    quarterly_reports = _build_quarterly_report_events(d)
    if not history and not annual_history:
        return jsonify({
            **_empty_history_payload(
                "Fundamentals file has no quarterly or annual income statement — charts skipped."
            ),
            "quarterly_reports": quarterly_reports,
            "analyst_ratings": analyst,
            "price_chart_1y":  price_chart_1y,
            "price":           _safe_float(h.get("WallStreetTargetPrice")),
            "eps_ttm":         _safe_float(h.get("EarningsShare")),
            "pe_ttm":          _safe_float(h.get("PERatio")),
            "market_cap_b":    round(_safe_float(h.get("MarketCapitalization")) / 1e9, 2),
            "market_cap_usd":  _safe_float(h.get("MarketCapitalization")),
            "market_cap_fmt":  _format_usd_compact(_safe_float(h.get("MarketCapitalization"))),
        })

    mcap_usd = _safe_float(h.get("MarketCapitalization"))
    chart_fx_note = None
    fx_factor, fx_note = _local_to_usd_factor(_statement_currency(d))
    if fx_factor != 1.0:
        for row in history:
            _scale_chart_money_row(row, fx_factor, shares_out=shares_out)
        for row in annual_history:
            _scale_chart_money_row(row, fx_factor, shares_out=shares_out)
        _scale_chart_money_row(ttm, fx_factor, shares_out=shares_out)
        _scale_chart_money_row(ttm2, fx_factor, shares_out=shares_out)
        for est in estimates:
            _scale_chart_revenue_estimate(est, fx_factor)
        chart_fx_note = fx_note

    _prune_implausible_revenue_estimates(estimates, ttm, annual_history)

    display_metrics = _eodhd_display_metrics(annual_history, ttm, h)

    return jsonify({
        "history":         history,
        "annual_history":  annual_history,
        "history_cadence": "quarterly" if q_inc else "annual",
        "quarterly_reports": quarterly_reports,
        "ttm":             ttm,
        "ttm2":            ttm2,
        "estimates":       estimates,
        "display_metrics": display_metrics,
        "analyst_ratings": analyst,
        "price_chart_1y":  price_chart_1y,
        "price":           _safe_float(h.get("WallStreetTargetPrice")),
        "eps_ttm":         _safe_float(h.get("EarningsShare")),
        "pe_ttm":          _safe_float(h.get("PERatio")),
        "market_cap_b":    round(mcap_usd / 1e9, 2) if mcap_usd else 0.0,
        "market_cap_usd":  mcap_usd,
        "market_cap_fmt":  _format_usd_compact(mcap_usd),
        "shares_outstanding": shares_out if shares_out > 0 else None,
        "partial":         False,
        "chart_fx_note":   chart_fx_note,
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

    ls = round(_compounder_list_score(c), 2)
    return jsonify({
        "symbol":   c["symbol"],
        "name":     c.get("name", c["symbol"]),
        "sector":   c.get("sector", "Unknown"),
        "industry": c.get("industry", "Unknown"),
        "exchange": c.get("exchange", "US"),
        "description": ci.get("description", ""),
        "listing_score": ls,
        "momentum_score": round(_cached_momentum_score(c), 2),
        "screener_rank": _screener_rank(c["symbol"]),
        "momentum_rank": _momentum_rank(c["symbol"]),
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
        "analyst_ratings": _fmt_analyst(_analyst_ratings_for_company(c) or {}),
    })


def _chat_stock_context_tiny(c: dict) -> dict:
    """Minimal ticker context for the LLM (EODHD headline when cached; full detail via tools)."""
    m = c.get("financial_metrics", {})
    ci = c.get("company_info", {})
    s = c.get("investment_scores", {})
    sym = c["symbol"]
    rf = m.get("red_flags") or []
    if isinstance(rf, list):
        rf = rf[:5]
    desc = (ci.get("description") or "")[:400]
    eodhd = _chat_metrics_from_eodhd(sym)
    metrics = {
        "revenue_b": round(m.get("revenue", 0) / 1e9, 2),
        "revenue_fmt": _format_usd_compact(m.get("revenue", 0)),
        "net_income_b": round(m.get("net_income", 0) / 1e9, 2),
        "net_income_fmt": _format_usd_compact(m.get("net_income", 0)),
        "pe": ci.get("pe_ratio") or m.get("pe_ratio"),
        "market_cap_b": round(ci.get("market_cap", 0) / 1e9, 2),
        "market_cap_fmt": _format_usd_compact(ci.get("market_cap", 0)),
        "roe_pct": round(m.get("roe", 0) * 100, 1),
        "roic_pct": round(m.get("roic", 0) * 100, 1),
        "basis": "universe_scan_ttm",
    }
    if eodhd:
        metrics["eodhd"] = eodhd
        if eodhd.get("flow"):
            metrics["basis"] = "eodhd_ttm"
        if eodhd.get("filed_fy"):
            metrics["filed_fy"] = eodhd["filed_fy"]
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
        "metrics": metrics,
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
                "Search the web (DuckDuckGo) for recent news, catalysts, earnings reactions, guidance, lawsuits, "
                "management changes, and macro context. **Call proactively** when the user asks why the stock moved, "
                "what happened lately, risks, competitors, or anything time-sensitive — do not guess from memory. "
                "Snippets + URLs only (not full articles); follow with `fetch_web_page` when you need the body. "
                "You have **no browser** — never claim you read a page unless you called `fetch_web_page`."
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
                "Fetch plain text from one public http(s) URL (server-side GET). Use after `web_search` when snippets "
                "are not enough, or when the user pastes a link. **Prefer fetching** over saying you cannot read URLs. "
                "Standard HTML/text/JSON only; no login or JavaScript."
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
                "Fetch live EODHD fundamentals for the ticker on this page (General, Highlights, optional annual income). "
                "Server already has EODHD_API_KEY — **never ask the user for keys or permission**. "
                "**Default to calling this** when you need P/E, EPS, margins, 52-week range, target price, sector, "
                "or any number missing/stale in context JSON; also to verify before stating a figure. "
                "Use detail_level=financials for ~12 years of annual statements; full adds quarterly + more years. "
                "If the call fails, say so briefly — do not invent numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "financials", "full"],
                        "description": (
                            "summary = General + Highlights; "
                            "financials = up to 12 annual income + 8 annual cash-flow rows; "
                            "full = up to 20 annual income, 12 quarterly income, balance-sheet snapshot."
                        ),
                    },
                },
            },
        },
    }
]


def _eodhd_chat_pick(d: dict, *keys: str):
    """Include only present EODHD numeric fields (keeps JSON smaller)."""
    row = {}
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            row[k] = v
    return row


def _eodhd_chat_income_row(inc: dict, period: str) -> dict:
    row = {"period": period}
    row.update(_eodhd_chat_pick(
        inc,
        "totalRevenue",
        "costOfRevenue",
        "grossProfit",
        "operatingIncome",
        "ebit",
        "researchDevelopment",
        "interestExpense",
        "incomeBeforeTax",
        "incomeTaxExpense",
        "netIncome",
        "eps",
        "epsDiluted",
        "weightedAverageShsOut",
        "weightedAverageShsOutDil",
    ))
    return row


def _eodhd_chat_cf_row(cf: dict, period: str) -> dict:
    row = {"period": period}
    row.update(_eodhd_chat_pick(
        cf,
        "totalCashFromOperatingActivities",
        "capitalExpenditures",
        "stockBasedCompensation",
        "freeCashFlow",
        "dividendsPaid",
    ))
    return row


def _eodhd_snapshot_append_financials(out: dict, d: dict, detail_level: str) -> None:
    fin = d.get("Financials") or {}
    inc_y = (fin.get("Income_Statement") or {}).get("yearly") or {}
    cf_y = (fin.get("Cash_Flow") or {}).get("yearly") or {}
    bs_y = (fin.get("Balance_Sheet") or {}).get("yearly") or {}

    n_annual = 20 if detail_level == "full" else 12
    inc_keys = sorted(inc_y.keys(), reverse=True)[:n_annual]
    out["annual_income"] = [_eodhd_chat_income_row(inc_y[k], k) for k in inc_keys]
    out["annual_income_count"] = len(out["annual_income"])

    cf_keys = sorted(cf_y.keys(), reverse=True)[: (12 if detail_level == "full" else 8)]
    out["annual_cash_flow"] = [_eodhd_chat_cf_row(cf_y[k], k) for k in cf_keys]

    if bs_y:
        bs_key = sorted(bs_y.keys(), reverse=True)[0]
        bs = bs_y[bs_key]
        out["balance_sheet_latest"] = {
            "period": bs_key,
            **_eodhd_chat_pick(
                bs,
                "totalAssets",
                "totalLiab",
                "totalStockholderEquity",
                "cash",
                "shortLongTermDebtTotal",
                "longTermDebt",
                "commonStockSharesOutstanding",
            ),
        }

    if detail_level == "full":
        q_inc = (fin.get("Income_Statement") or {}).get("quarterly") or {}
        q_keys = sorted(q_inc.keys(), reverse=True)[:12]
        out["quarterly_income"] = [
            {
                "period": k,
                **_eodhd_chat_pick(q_inc[k], "totalRevenue", "grossProfit", "netIncome", "eps", "epsDiluted"),
            }
            for k in q_keys
        ]
        out["quarterly_income_count"] = len(out["quarterly_income"])


def _eodhd_snapshot_for_tool(symbol: str, detail_level: str) -> str:
    d = _get_fundamentals(symbol)
    if not d:
        return json.dumps({"ok": False, "error": "No EODHD data (cache or API) for this symbol."})
    gen = d.get("General") or {}
    hi = _merged_highlights(d)
    out: dict = {
        "ok": True,
        "symbol": symbol,
        "detail_level": detail_level,
        "general": {
            k: gen.get(k)
            for k in ("Name", "Code", "Sector", "Industry", "CurrencyCode", "FiscalYearEnd")
            if gen.get(k) is not None
        },
        "highlights": {
            k: hi.get(k)
            for k in (
                "MarketCapitalization", "PERatio", "EarningsShare", "EBITDA", "BookValue",
                "Beta", "52WeekHigh", "52WeekLow", "DividendYield", "AverageVolume",
                "WallStreetTargetPrice", "RevenueTTM", "ProfitMargin", "OperatingMarginTTM",
            )
            if hi.get(k) is not None
        },
    }
    if detail_level in ("financials", "full"):
        _eodhd_snapshot_append_financials(out, d, detail_level)
    max_chars = min(int(os.getenv("CHAT_EODHD_SNAPSHOT_MAX_CHARS", "32000")), 50000)
    try:
        return json.dumps(out, default=str)[:max_chars]
    except Exception:
        return json.dumps({"ok": False, "error": "serialization failed"})


def _chat_ndjson_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _chat_system_prompt(ctx_json: str) -> str:
    return (
        "You interpret one stock dashboard page. Be **brief**: default to 2–4 tight sentences "
        "or a tiny bullet list unless the user explicitly asks for depth. No filler. "
        "**Plain text only** — never HTML tags or markup. "
        "You have **no browser window** — you cannot “open” a site except via tools. "
        "Not financial advice; note when numbers are uncertain.\n\n"
        "**Tools (use them — do not hesitate):**\n"
        "- `eodhd_fundamentals_snapshot`: **first choice** for metrics and history (default detail_level=financials: "
        "~12 annual income + cash-flow rows; use full for quarterly). Server API key is already configured — "
        "never ask the user to enable EODHD or paste keys.\n"
        "- `web_search`: **default for news/catalysts** (“why down today”, earnings, guidance, legal, product, "
        "macro). Search before saying you do not know recent events.\n"
        "- `fetch_web_page`: read a specific URL from search or the user.\n"
        "- `evaluate_math`: margins, growth %, ratios — substitute literals from context/tools.\n"
        "**Tool bias:** If a good answer needs live data or recent news, **call tools in the same turn** "
        "(often `eodhd_fundamentals_snapshot` + `web_search` together). Do **not** ask “want me to search?” — "
        "just search. Do **not** refuse tools as “unnecessary” when context is thin or the question is timely. "
        "Only skip tools when context already fully answers a static question about scores on this page.\n\n"
        "Context JSON is below.\n\n"
        "**Reply rules:** Answer the **last user message** in the thread only. Do **not** repeat "
        "the same score-card recap on every turn. If they ask a new question (growth %, valuation, "
        "risk, comparison, “why ranked here”, opinion), answer **that** with specifics from context "
        "and tools — do not default to re-explaining Q/V/G/S unless they asked how scoring works. "
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
    """Stock-aware chat via ChatGPT subscription (Codex OAuth)."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    c = get_company(symbol)
    if not c:
        return jsonify({"error": "Company not found"}), 404

    if not codex_chat.auth_status(PROJECT_ROOT).get("authenticated"):
        return jsonify({
            "error": "Sign in with ChatGPT (Ask AI panel) to use chat.",
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

    max_tool_rounds = min(int(os.getenv("OPENAI_CHAT_MAX_TOOL_ROUNDS", "6")), 10)

    try:
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

    if not codex_chat.auth_status(PROJECT_ROOT).get("authenticated"):
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
    max_tool_rounds = min(int(os.getenv("OPENAI_CHAT_MAX_TOOL_ROUNDS", "6")), 10)

    @stream_with_context
    def gen():
        try:
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
        "ms_ticker": _eodhd_ticker(symbol, c) or f"{symbol}.US",
        "ms_app_url": MOONSTOCKS_API_BASE,
        "data_quality": c.get("data_quality", {
            "income_statement": 0, "balance_sheet": 0,
            "cash_flow": 0, "quality": "N/A",
        }),
        "listing_score": round(_compounder_list_score(c), 2),
        "momentum_score": round(_cached_momentum_score(c), 2),
        "screener_rank": _screener_rank(c["symbol"]),
        "momentum_rank": _momentum_rank(c["symbol"]),
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
            "fcf_yield_pct":        round(float(m.get("fcf_yield", 0) or 0) * 100, 1),
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
        "analyst_ratings": _fmt_analyst(_analyst_ratings_for_company(c) or {}),
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


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "equity-os",
        "moonstocks_storage": "postgres" if ms_store.uses_postgres() else "sqlite",
    })


@app.route('/api/moonstocks/<path:ticker>')
def moonstocks_analysis(ticker):
    """Get Moonstocks AI analysis for a ticker from local database."""
    try:
        row = ms_store.get_analysis(PROJECT_ROOT, ticker)
        if not row:
            return jsonify(None), 404
        return jsonify(ms_store.row_to_moonstocks_json(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/moonstocks/<path:ticker>/trigger', methods=['POST'])
def moonstocks_trigger(ticker):
    """Trigger Moonstocks AI analysis by calling the external analyzer service."""
    try:
        resp = _req.post(
            f"{_moonstocks_analyzer_url()}/{ticker}",
            headers=_moonstocks_analyzer_headers(),
            timeout=30,
        )
        body = resp.json() if resp.content else {}
        return jsonify(body), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/api/analysis', methods=['GET'])
def get_all_analyses():
    """Get all Moonstocks AI analyses (for moonstocks-app compatibility)."""
    try:
        rows = ms_store.list_analyses(PROJECT_ROOT)
        return jsonify([ms_store.row_to_compat_json(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analysis/<ticker_and_exchange_code>', methods=['POST'])
def create_analysis(ticker_and_exchange_code):
    """Store a Moonstocks AI analysis (called by analyzer service)."""
    if not _moonstocks_ingest_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.get_json(silent=True) or {}
        json_report = data.get("jsonReport") or data.get("json_report")
        if not json_report:
            return jsonify({"error": "Missing jsonReport"}), 400
        if isinstance(json_report, dict):
            json_report = json.dumps(json_report)
        
        generated_time = int(datetime.now().timestamp() * 1000)
        ms_store.upsert_analysis(
            PROJECT_ROOT, ticker_and_exchange_code, json_report, generated_time
        )
        return jsonify({"status": "created", "tickerAndExchangeCode": ticker_and_exchange_code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analysis/<ticker_and_exchange_code>/trigger', methods=['POST'])
def trigger_analysis_api(ticker_and_exchange_code):
    """Trigger Moonstocks AI analysis (for moonstocks-app compatibility)."""
    try:
        resp = _req.post(
            f"{_moonstocks_analyzer_url()}/{ticker_and_exchange_code}",
            headers=_moonstocks_analyzer_headers(),
            timeout=30,
        )
        body = resp.json() if resp.content else {}
        return jsonify(body), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


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
    target = min(int(body.get("target", 1000)), 8000)
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
            proc = subprocess.run(
                cmd,
                env=env,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode == 0:
                load_data()
            else:
                err_tail = ""
                if proc.stderr:
                    err_tail = proc.stderr.strip()[-800:]
                elif proc.stdout:
                    err_tail = proc.stdout.strip()[-800:]
                msg = f"subprocess exit {proc.returncode}"
                if err_tail:
                    msg = f"{msg}: {err_tail}"
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
                        "error": msg[:500],
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
