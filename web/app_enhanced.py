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
import subprocess
import threading
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from datetime import datetime
from dotenv import load_dotenv
import requests as _req

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.io_utils import read_jsonl, read_json

load_dotenv()

app = Flask(__name__)

# ── Global state ──────────────────────────────────────────────────────────────
companies: list[dict] = []
company_lookup: dict[str, dict] = {}
DATA_SOURCE = "none"
DATA_FILE: Path | None = None  # primary universe jsonl (e.g. scaled)
DATA_OVERLAY_FILE: Path | None = None  # rescored jsonl applied on top, if any

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


def load_data() -> bool:
    """Load universe from latest scaled (or final), overlay rescored scores when present.

    Root issue fixed: an older small ``rescored_*.jsonl`` must not replace a larger
    ``scaled_analysis_*.jsonl`` — we always keep the scaled universe and only patch
    ``investment_scores`` / ``name`` from rescored for matching symbols.
    """
    global companies, company_lookup, DATA_SOURCE, DATA_FILE, DATA_OVERLAY_FILE

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
        DATA_SOURCE = "none"
        DATA_FILE = None
        DATA_OVERLAY_FILE = None
        print("[ERR] No analysis data found")
        return False

    base_rows = _dedupe_rows_best_score(base_rows)
    rescored_map = {c["symbol"]: c for c in rescored_rows} if rescored_rows else {}
    overlay_used = False
    if rescored_map and base_label in ("scaled", "final"):
        for c in base_rows:
            sym = c["symbol"]
            if sym in rescored_map:
                rc = rescored_map[sym]
                c["investment_scores"] = dict(rc.get("investment_scores") or c.get("investment_scores", {}))
                if rc.get("name"):
                    c["name"] = rc["name"]
                overlay_used = True

    companies = sorted(
        base_rows,
        key=lambda x: x.get("investment_scores", {}).get("overall_score", 0),
        reverse=True,
    )
    company_lookup = {c["symbol"]: c for c in companies}

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


def filter_sort(sector=None, category=None, min_score=0.0,
                sort_by="overall_score", sort_order="desc",
                search="",
                wq=5, wv=5, wg=5, ws=5, wa=0) -> list[dict]:
    result = companies
    if sector:
        result = [c for c in result if c.get("sector", "").lower() == sector.lower()]
    if category:
        result = [c for c in result
                  if c.get("investment_scores", {}).get("investment_category", "").lower() == category.lower()]
    if min_score > 0:
        result = [c for c in result if _score(c) >= min_score]
    if search:
        q = search.lower()
        result = [c for c in result
                  if q in c.get("symbol", "").lower() or q in c.get("name", "").lower()]

    def _custom_score(c):
        s  = c.get("investment_scores", {})
        tw = wq + wv + wg + ws
        if tw == 0:
            base = 0.0
        else:
            base = (s.get("quality_score",0)*wq + s.get("value_score",0)*wv +
                    s.get("growth_score",0)*wg  + s.get("safety_score",0)*ws) / tw * 5
        if wa > 0:
            ar = c.get("analyst_ratings") or {}
            r  = float(ar.get("Rating") or ar.get("rating") or 0)
            if r > 0:
                base += ((r - 1) / 4) * wa * 0.4
        return base

    key_map = {
        "overall_score":  lambda c: _score(c),
        "custom_score":   _custom_score,
        "quality_score":  lambda c: c.get("investment_scores", {}).get("quality_score", 0),
        "value_score":    lambda c: c.get("investment_scores", {}).get("value_score", 0),
        "growth_score":   lambda c: c.get("investment_scores", {}).get("growth_score", 0),
        "safety_score":   lambda c: c.get("investment_scores", {}).get("safety_score", 0),
        "tenx_score":     lambda c: c.get("investment_scores", {}).get("tenx_score", 0),
        "revenue":        lambda c: c.get("financial_metrics", {}).get("revenue", 0),
        "market_cap":     lambda c: c.get("company_info", {}).get("market_cap", 0),
        "roic":           lambda c: c.get("financial_metrics", {}).get("roic", 0),
        "roe":            lambda c: c.get("financial_metrics", {}).get("roe", 0),
        "pe_ratio":       lambda c: c.get("company_info", {}).get("pe_ratio") or c.get("financial_metrics", {}).get("pe_ratio", 9999),
        "symbol":         lambda c: c.get("symbol", ""),
        "peg_ratio":      lambda c: c.get("investment_scores", {}).get("peg_ratio") or 999,
        "oeps_cagr":      lambda c: c.get("investment_scores", {}).get("oeps_cagr_pct", 0),
        "revenue_cagr":   lambda c: c.get("investment_scores", {}).get("revenue_cagr_3y_pct", 0),
    }
    key_fn = key_map.get(sort_by, key_map["overall_score"])
    result = sorted(result, key=key_fn,
                    reverse=(sort_order == "desc") if sort_by != "symbol" else (sort_order == "desc"))
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
        "total_market_cap_t": round(total_mcap / 1e12, 2),
        "investment_categories": cats,
        "sectors": sectors_count,
        "top_overall": {"symbol": top_overall.get("symbol"), "score": _score(top_overall)},
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
    sort_by    = request.args.get('sort_by', 'overall_score')
    sort_order = request.args.get('sort_order', 'desc')
    search     = request.args.get('search', '').strip()

    wq = int(request.args.get('wq', 5))
    wv = int(request.args.get('wv', 5))
    wg = int(request.args.get('wg', 5))
    ws = int(request.args.get('ws', 5))
    wa = int(request.args.get('wa', 0))
    use_custom = any([wq!=5, wv!=5, wg!=5, ws!=5, wa!=0])
    effective_sort = 'custom_score' if use_custom else sort_by
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
            "roe_pct":       round(m.get("roe", 0) * 100, 1),
            "pe_ratio":      ci.get("pe_ratio") or m.get("pe_ratio", 0),
            "market_cap_b":  round(ci.get("market_cap", 0) / 1e9, 2),
            "data_quality":  c.get("data_quality", {}).get("quality", "N/A"),
            "analyst_ratings": _fmt_analyst(c.get("analyst_ratings", {})),
        }

    return jsonify({
        "companies": [fmt(c) for c in page],
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "has_more": (offset + limit) < total,
    })

def _fmt_analyst(ar: dict) -> dict | None:
    if not ar:
        return None
    r = ar.get("Rating") or ar.get("rating")
    if not r:
        return None
    return {
        "rating":      round(float(r), 2),
        "target_price": float(ar.get("TargetPrice") or ar.get("target_price") or 0),
        "strong_buy":  int(ar.get("StrongBuy") or ar.get("strong_buy") or 0),
        "buy":         int(ar.get("Buy") or ar.get("buy") or 0),
        "hold":        int(ar.get("Hold") or ar.get("hold") or 0),
        "sell":        int(ar.get("Sell") or ar.get("sell") or 0),
        "strong_sell": int(ar.get("StrongSell") or ar.get("strong_sell") or 0),
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
        "partial":         True,
        "message":         message,
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
    for yr in sorted(annual.keys(), reverse=True)[:8]:
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
        history.append({
            "year":      yr[:4],
            "revenue_b": round(rev / 1e9, 2),
            "net_income_b": round(ni / 1e9, 2),
            "op_income_b":  round(op / 1e9, 2),
            "fcf_b":        round(fcf / 1e9, 2),
            "owner_earnings_b": round(oe / 1e9, 2),
            "eps":          round(eps, 4),
            "oeps":         round(oeps, 4),
            "roe_pct":      round(ni / eq * 100, 1) if eq else 0,
            "gross_margin_pct": round(
                _safe_float(inc.get("grossProfit")) / rev * 100, 1) if rev else 0,
            "net_margin_pct": round(ni / rev * 100, 1) if rev else 0,
        })

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
        })

    return jsonify({
        "history":         history,
        "analyst_ratings": analyst,
        "price":           _safe_float(h.get("WallStreetTargetPrice")),
        "eps_ttm":         _safe_float(h.get("EarningsShare")),
        "pe_ttm":          _safe_float(h.get("PERatio")),
        "market_cap_b":    round(_safe_float(h.get("MarketCapitalization")) / 1e9, 2),
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
            "net_income_b":     round(m.get("net_income", 0) / 1e9, 2),
            "owner_earnings_b": round(m.get("owner_earnings", 0) / 1e9, 3),
            "oeps":             round(m.get("owner_earnings_per_share", 0), 4),
            "oeps_cagr_pct":    round(m.get("oeps_cagr", 0) * 100, 2),
            "roe_pct":          round(m.get("roe", 0) * 100, 1),
            "roic_pct":         round(m.get("roic", 0) * 100, 1),
            "roa_pct":          round(m.get("roa", 0) * 100, 1),
            "gross_margin_pct": round(m.get("gross_margin", 0) * 100, 1),
            "net_margin_pct":   round(m.get("net_margin", 0) * 100, 1),
            "pe_ratio":         ci.get("pe_ratio") or m.get("pe_ratio", 0),
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
            "net_income_b": round(m.get("net_income", 0) / 1e9, 2),
            "pe": ci.get("pe_ratio") or m.get("pe_ratio"),
            "market_cap_b": round(ci.get("market_cap", 0) / 1e9, 2),
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
            "name": "eodhd_fundamentals_snapshot",
            "description": (
                "Fetch a compact EODHD fundamentals snapshot for the ticker on this page. "
                "The server uses EODHD_API_KEY from its environment — never ask the user for keys. "
                "Use when you need Highlights, General metadata, or recent annual income lines."
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
    hi = d.get("Highlights") or {}
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
        "Context JSON is below. For more EODHD fields call `eodhd_fundamentals_snapshot` "
        "(server uses EODHD_API_KEY; never ask users for keys). Not financial advice; "
        "note when numbers are uncertain.\n\n"
        + ctx_json
    )


def _chat_build_messages(c: dict, user_msg: str, history: list, max_in: int, max_turns: int) -> tuple[str, list]:
    sym = c["symbol"]
    try:
        ctx_json = json.dumps(_chat_stock_context_tiny(c), ensure_ascii=False, default=str)[:4000]
    except Exception:
        ctx_json = "{}"
    system = _chat_system_prompt(ctx_json)
    messages: list = [{"role": "system", "content": system}]
    for h in history[-max_turns:]:
        role = h.get("role")
        content = h.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        messages.append({"role": role, "content": content[:max_in]})
    messages.append({"role": "user", "content": user_msg})
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
            if tc.function.name != "eodhd_fundamentals_snapshot":
                payload = json.dumps({"ok": False, "error": "unknown tool"})
            else:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                detail = args.get("detail_level") or "summary"
                if detail not in ("summary", "financials"):
                    detail = "summary"
                payload = _eodhd_snapshot_for_tool(sym, detail)
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


@app.route("/api/company/<symbol>/chat", methods=["POST"])
def api_company_chat(symbol):
    """Stock-aware chat: OpenAI (default GPT-5 family); EODHD only via server tool."""
    if not _parse_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    c = get_company(symbol)
    if not c:
        return jsonify({"error": "Company not found"}), 404

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return jsonify({
            "error": "Chat is not configured. Set OPENAI_API_KEY in the server environment (never commit keys).",
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

    model = (os.getenv("OPENAI_CHAT_MODEL") or "gpt-5-mini").strip()
    sym, messages = _chat_build_messages(c, user_msg, history, max_in, max_turns)

    max_out = min(int(os.getenv("OPENAI_CHAT_MAX_TOKENS", "512")), 8192)
    temp = float(os.getenv("OPENAI_CHAT_TEMPERATURE", "0.35"))
    max_tool_rounds = min(int(os.getenv("OPENAI_CHAT_MAX_TOOL_ROUNDS", "4")), 8)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        reply_text = _chat_run_tool_loop(
            client, model, messages, max_out, temp, sym, max_tool_rounds,
        )
        return jsonify({"reply": reply_text, "model": model})
    except Exception as e:
        return jsonify({"error": f"OpenAI error: {e!s}"}), 502


@app.route("/api/company/<symbol>/chat/stream", methods=["POST"])
def api_company_chat_stream(symbol):
    """NDJSON stream: phase thinking/tool, then token deltas; briefer defaults."""
    if not _parse_symbol(symbol):
        return Response(_chat_ndjson_line({"error": "Invalid symbol", "done": True}), status=400, mimetype="application/x-ndjson")

    c = get_company(symbol)
    if not c:
        return Response(_chat_ndjson_line({"error": "Company not found", "done": True}), status=404, mimetype="application/x-ndjson")

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return Response(
            _chat_ndjson_line({"error": "OPENAI_API_KEY not set", "done": True}),
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
    model = (os.getenv("OPENAI_CHAT_MODEL") or "gpt-5-mini").strip()
    sym, messages = _chat_build_messages(c, user_msg, history, max_in, max_turns)
    max_out = min(int(os.getenv("OPENAI_CHAT_STREAM_MAX_TOKENS", os.getenv("OPENAI_CHAT_MAX_TOKENS", "512"))), 2048)
    temp = float(os.getenv("OPENAI_CHAT_TEMPERATURE", "0.35"))
    max_tool_rounds = min(int(os.getenv("OPENAI_CHAT_MAX_TOOL_ROUNDS", "4")), 8)

    @stream_with_context
    def gen():
        yield _chat_ndjson_line({"phase": "thinking"})
        try:
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

                yield _chat_ndjson_line({"phase": "tool"})
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
                    if tc.function.name != "eodhd_fundamentals_snapshot":
                        payload = json.dumps({"ok": False, "error": "unknown tool"})
                    else:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        detail = args.get("detail_level") or "summary"
                        if detail not in ("summary", "financials"):
                            detail = "summary"
                        payload = _eodhd_snapshot_for_tool(sym, detail)
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": payload})

            if not reply_text and msgs:
                for m in reversed(msgs):
                    if m.get("role") == "assistant" and m.get("content"):
                        reply_text = str(m["content"]).strip()
                        break

            if reply_text:
                step = 32
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
            "roe_pct":       round(m.get("roe", 0) * 100, 1),
            "roic_pct":      round(m.get("roic", 0) * 100, 1),
            "market_cap_b":  round(c.get("company_info", {}).get("market_cap", 0) / 1e9, 2),
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
            "total_market_cap_b": round(sum(c.get("company_info", {}).get("market_cap", 0)
                                             for c in d["companies"]) / 1e9, 1),
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
            "net_income_b":         round(m.get("net_income", 0) / 1e9, 2),
            "owner_earnings_b":     round(m.get("owner_earnings", 0) / 1e9, 3),
            "oeps_cagr_pct":        round(m.get("oeps_cagr", 0) * 100, 1),
            "gross_margin_pct":     round(m.get("gross_margin", 0) * 100, 1),
            "net_margin_pct":       round(m.get("net_margin", 0) * 100, 1),
            "operating_margin_pct": round(m.get("operating_margin", 0) * 100, 1),
            "roe_pct":              round(m.get("roe", 0) * 100, 1),
            "roic_pct":             round(m.get("roic", 0) * 100, 1),
            "roa_pct":              round(m.get("roa", 0) * 100, 1),
            "pe_ratio":             ci.get("pe_ratio") or m.get("pe_ratio", 0),
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
            "pe_ratio":      ci.get("pe_ratio", 0),
            "description":   ci.get("description", ""),
        },
        "analyst_ratings": _fmt_analyst(c.get("analyst_ratings", {})),
    }
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
        return jsonify(json.loads(pf.read_text()))
    except Exception:
        return jsonify({"running": False, "done": 0, "total": 0, "pct": 0})


_analysis_lock = threading.Lock()

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

    body    = request.get_json(silent=True) or {}
    target  = min(int(body.get("target", 1000)), 2000)
    workers = min(int(body.get("workers", 8)), 20)

    script = PROJECT_ROOT / "scripts" / "scale_analysis_1000.py"

    def _run():
        try:
            # Write initial progress immediately so UI shows something
            pf = PROJECT_ROOT / "outputs" / "analysis_progress.json"
            pf.write_text(json.dumps({
                "running": True, "done": 0, "total": target,
                "pct": 0, "last_sym": "", "last_score": 0,
                "successful": 0, "failed": 0,
                "started_at": datetime.now().isoformat(),
            }))
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                [sys.executable, str(script),
                 "--target",  str(target),
                 "--workers", str(workers)],
                env=env, cwd=str(PROJECT_ROOT),
            )
            if proc.returncode == 0:
                load_data()   # hot-reload once done
        finally:
            _analysis_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True, "target": target, "workers": workers})


if __name__ == '__main__':
    print("Equity Analysis Dashboard")
    load_data()
    if companies:
        print(f"Top: {companies[0]['symbol']} ({_score(companies[0]):.1f}/20)")
    app.run(debug=True, host='0.0.0.0', port=5000)
