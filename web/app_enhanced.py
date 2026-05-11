#!/usr/bin/env python3
"""
Equity Analysis Web Application
Serves rescored company data with full sector analysis and infinite-scroll API.
"""

import os
import sys
import json
import subprocess
import threading
from pathlib import Path
from flask import Flask, render_template, jsonify, request
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

def _latest_nonempty(directory: Path, pattern: str) -> Path | None:
    """Return the most-recent non-empty file matching pattern."""
    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        data = read_jsonl(f)
        if data:
            return f
    return None


def load_data() -> bool:
    """Load the best available analysis data, priority: rescored > scaled > final."""
    global companies, company_lookup, DATA_SOURCE

    output_dir = PROJECT_ROOT / "outputs"

    candidates = [
        (output_dir / "rescored_analysis",     "rescored_*.jsonl",           "rescored"),
        (output_dir / "scaled_analysis",      "scaled_analysis_*.jsonl",    "scaled"),
        (output_dir / "final_working_analysis", "*analysis_*.jsonl",        "final"),
    ]

    for directory, pattern, label in candidates:
        if not directory.exists():
            continue
        f = _latest_nonempty(directory, pattern)
        if f:
            companies = read_jsonl(f)
            # De-duplicate by symbol (keep highest score)
            seen: dict[str, dict] = {}
            for c in companies:
                sym = c["symbol"]
                existing_score = seen.get(sym, {}).get("investment_scores", {}).get("overall_score", -1)
                new_score = c.get("investment_scores", {}).get("overall_score", 0)
                if new_score >= existing_score:
                    seen[sym] = c
            companies = sorted(seen.values(),
                               key=lambda x: x.get("investment_scores", {}).get("overall_score", 0),
                               reverse=True)
            company_lookup = {c["symbol"]: c for c in companies}
            DATA_SOURCE = label
            print(f"[OK] Loaded {len(companies)} companies from {label} ({f.name})")
            return True

    print("[ERR] No analysis data found")
    return False

def _score(c: dict) -> float:
    return c.get("investment_scores", {}).get("overall_score", 0.0)


def get_company(symbol: str) -> dict | None:
    return company_lookup.get(symbol.upper())


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
        cats[s.get("investment_category", "UNKNOWN")] = cats.get(s.get("investment_category", "UNKNOWN"), 0) + 1
        sec = c.get("sector", "Unknown")
        sectors_count[sec] = sectors_count.get(sec, 0) + 1
        total_score += s.get("overall_score", 0)
        total_rev   += c.get("financial_metrics", {}).get("revenue", 0)
        total_mcap  += c.get("company_info", {}).get("market_cap", 0)
        top_growth_score = max(top_growth_score, s.get("growth_score", 0))

    n = len(companies)
    # Top company by growth score
    top_growth = max(companies, key=lambda c: c.get("investment_scores", {}).get("growth_score", 0))
    top_overall = companies[0] if companies else {}

    return jsonify({
        "total_companies": n,
        "data_source": DATA_SOURCE,
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
        "last_updated": datetime.now().isoformat(),
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
    """Return fundamentals for symbol: disk cache first, then EODHD API."""
    sym = symbol.upper()
    cache_file = _CACHE_DIR / f"{sym}.json"

    # Cache hit?
    if cache_file.exists():
        import time
        if time.time() - cache_file.stat().st_mtime < _CACHE_TTL:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    # Cache miss → fetch live
    api_key = os.getenv("EODHD_API_KEY", "")
    if not api_key:
        return None
    r = _req.get(
        f"https://eodhd.com/api/fundamentals/{sym}.US",
        params={"api_token": api_key, "fmt": "json"}, timeout=15
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


@app.route('/api/company/<symbol>/history')
def api_company_history(symbol):
    """Serve historical annual financials + analyst data (cache-first)."""
    try:
        d = _get_fundamentals(symbol)
        if not d:
            return jsonify({"error": "No API key or data"}), 500
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
    return jsonify({
        "history":         history,
        "analyst_ratings": analyst,
        "price":           _safe_float(h.get("WallStreetTargetPrice")),
        "eps_ttm":         _safe_float(h.get("EarningsShare")),
        "pe_ttm":          _safe_float(h.get("PERatio")),
        "market_cap_b":    round(_safe_float(h.get("MarketCapitalization")) / 1e9, 2),
    })


@app.route('/api/company/<symbol>')
def api_company(symbol):
    c = get_company(symbol.upper())
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
    c = get_company(symbol.upper())
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
