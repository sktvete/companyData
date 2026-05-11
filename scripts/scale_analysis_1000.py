#!/usr/bin/env python3

"""
Scale Analysis to 1,000+ Companies
Large-scale comprehensive analysis with real EODHD data.
"""

import sys
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env BEFORE importing Settings (defaults are evaluated at import time)
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from equity_sorter.config import load_settings
from equity_sorter.io_utils import write_jsonl, write_json
from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics
from equity_sorter.providers.eodhd.client import EODHDClient, EODHDRequest

def extract_financial_data_correct(fundamentals):
    """Extract financial data using the CORRECT EODHD API structure."""
    
    financials = {
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": []
    }
    
    financial_data = fundamentals.get("Financials", {})
    
    if isinstance(financial_data, dict):
        # Income Statement
        income_data = financial_data.get("Income_Statement", {})
        if isinstance(income_data, dict):
            quarterly_income = income_data.get("quarterly", {})
            if isinstance(quarterly_income, dict):
                income_list = []
                for date, data in quarterly_income.items():
                    if isinstance(data, dict):
                        data["date"] = date
                        income_list.append(data)
                income_list.sort(key=lambda x: x.get("date", ""), reverse=True)
                financials["income_statement"] = income_list
        
        # Balance Sheet
        balance_data = financial_data.get("Balance_Sheet", {})
        if isinstance(balance_data, dict):
            quarterly_balance = balance_data.get("quarterly", {})
            if isinstance(quarterly_balance, dict):
                balance_list = []
                for date, data in quarterly_balance.items():
                    if isinstance(data, dict):
                        data["date"] = date
                        balance_list.append(data)
                balance_list.sort(key=lambda x: x.get("date", ""), reverse=True)
                financials["balance_sheet"] = balance_list
        
        # Cash Flow
        cash_data = financial_data.get("Cash_Flow", {})
        if isinstance(cash_data, dict):
            quarterly_cash = cash_data.get("quarterly", {})
            if isinstance(quarterly_cash, dict):
                cash_list = []
                for date, data in quarterly_cash.items():
                    if isinstance(data, dict):
                        data["date"] = date
                        cash_list.append(data)
                cash_list.sort(key=lambda x: x.get("date", ""), reverse=True)
                financials["cash_flow"] = cash_list
    
    return financials

def get_top_companies(limit=1000):
    """
    Get list of companies to analyze.
    Priority order:
      1. outputs/company_universe.json  (built by discover_companies.py)
      2. outputs/symbol_list.txt
      3. Hardcoded S&P-500-like list (fallback)
    Run `python scripts/discover_companies.py --limit 2000` to build the universe.
    """
    import json as _json

    universe_file = PROJECT_ROOT / "outputs" / "company_universe.json"
    symbol_file   = PROJECT_ROOT / "outputs" / "symbol_list.txt"

    if universe_file.exists():
        data = _json.loads(universe_file.read_text())
        symbols = data.get("symbols", [])
        if symbols:
            print(f"📋  Loaded {len(symbols)} symbols from company_universe.json")
            # deduplicate preserving order
            seen, out = set(), []
            for s in symbols:
                if s not in seen:
                    seen.add(s); out.append(s)
            return out[:limit]

    if symbol_file.exists():
        syms = [s.strip() for s in symbol_file.read_text().splitlines() if s.strip()]
        if syms:
            print(f"📋  Loaded {len(syms)} symbols from symbol_list.txt")
            return syms[:limit]

    print("⚠️  No universe file found – using built-in list.")
    print("   Run: python scripts/discover_companies.py --limit 2000")

    # ── Fallback hardcoded list ───────────────────────────────────────────────
    top_companies = [
        # Tech Giants
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "ADBE", "CRM", "NFLX",
        "INTC", "CSCO", "ORCL", "IBM", "AMD", "TXN", "QCOM", "AVGO", "MU", "ADI",
        
        # Financial Services
        "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SPGI", "MMC",
        "AIG", "MET", "PRU", "BRK.A", "BRK.B", "V", "MA", "PYPL", "SQ", "COIN",
        
        # Healthcare
        "JNJ", "UNH", "PFE", "ABBV", "TMO", "ABT", "DHR", "BMY", "AMGN", "GILD",
        "CVS", "CI", "HUM", "CNC", "BIIB", "MRK", "LLY", "MDT", "ISRG", "SYK",
        
        # Consumer Discretionary
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "TGT", "SBUX", "BKNG", "EXPE",
        "DIS", "CMCSA", "NFLX", "ROST", "TJX", "DG", "AZO", "ORLY", "AAP", "BBY",
        
        # Consumer Staples
        "PG", "KO", "PEP", "WMT", "COST", "CL", "KMB", "GIS", "SYY", "KR",
        "HSY", "MNST", "K", "CLX", "CHD", "STZ", "ADM", "BGS", "CAG", "HRL",
        
        # Energy
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "BKR", "PSX", "VLO", "MPC",
        "OXY", "BP", "SHEL", "TOT", "ENB", "PBR", "EC", "PTR", "CEO", "CVE",
        
        # Industrial
        "BA", "CAT", "GE", "MMM", "HON", "UPS", "RTX", "LMT", "NOC", "GD",
        "DE", "CMI", "ETN", "EMR", "ITW", "JCI", "PH", "ROP", "TYC", "TXT",
        
        # Materials
        "LIN", "APD", "ECL", "DD", "DOW", "FCX", "NEM", "RIO", "BHP", "VALE",
        "SHW", "MLM", "VMC", "CRH", "STLD", "NUE", "X", "AKS", "CLF", "AA",
        
        # Real Estate
        "AMT", "PLD", "CCI", "EQIX", "PSA", "CBRE", "SPG", "VTR", "WELL", "HST",
        "BXP", "SLG", "ARE", "O", "EXR", "CPT", "ESS", "AVB", "EQR", "MAA",
        
        # Utilities
        "NEE", "DUK", "SO", "AEP", "SRE", "XEL", "WEC", "ED", "DTE", "EIX",
        "PEG", "PPL", "AEE", "CMS", "AWK", "CNP", "ETR", "FE", "PNW", "WR"
    ]
    
    return top_companies[:limit]

CACHE_DIR     = PROJECT_ROOT / "outputs" / "fundamentals_cache"
CACHE_TTL_H   = 24   # hours before a cached file is considered stale


def _load_cached(symbol: str) -> dict | None:
    """Return cached fundamentals if present and fresh, else None."""
    f = CACHE_DIR / f"{symbol}.json"
    if not f.exists():
        return None
    age_h = (time.time() - f.stat().st_mtime) / 3600
    if age_h > CACHE_TTL_H:
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(symbol: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (CACHE_DIR / f"{symbol}.json").write_text(
            json.dumps(data, separators=(",", ":")), encoding="utf-8"
        )
    except Exception:
        pass


def _analyse_one(symbol: str, api_key: str) -> tuple[str, dict | None, str | None]:
    """Fetch + score a single symbol. Caches raw fundamentals to disk (TTL=24h)."""
    try:
        fundamentals = _load_cached(symbol)
        if fundamentals is None:
            client = EODHDClient(api_key=api_key)   # fresh session per thread
            fundamentals = client.get_json(EODHDRequest(
                endpoint=f"fundamentals/{symbol}.US", params={}
            ))
            if fundamentals and isinstance(fundamentals, dict):
                _save_cache(symbol, fundamentals)
        if not fundamentals or not isinstance(fundamentals, dict):
            return symbol, None, "No fundamental data"

        financials = extract_financial_data_correct(fundamentals)
        income_q  = len(financials["income_statement"])
        balance_q = len(financials["balance_sheet"])
        cash_q    = len(financials["cash_flow"])
        min_q     = min(income_q, balance_q, cash_q)

        if min_q >= 100:   quality = "EXCELLENT"
        elif min_q >= 40:  quality = "GOOD"
        elif min_q >= 20:  quality = "FAIR"
        else:              quality = "POOR"

        if min_q < 4:
            return symbol, None, "Insufficient data"

        general    = fundamentals.get("General", {})
        highlights = fundamentals.get("Highlights", {})
        market_cap = float(highlights.get("MarketCapitalization") or 1_000_000_000_000)

        price_data = [{
            "date": "2024-12-31",
            "close": market_cap / 1_000_000_000,
            "market_cap": market_cap,
            "enterprise_value": market_cap * 1.2,
        }]

        metrics = calculate_comprehensive_metrics(financials, price_data)
        if "error" in metrics:
            return symbol, None, "Metrics calculation failed"

        ar_raw = fundamentals.get("AnalystRatings", {})
        analyst_ratings = None
        if ar_raw and ar_raw.get("Rating"):
            analyst_ratings = {
                "Rating":     ar_raw.get("Rating"),
                "TargetPrice": ar_raw.get("TargetPrice", 0),
                "StrongBuy":  ar_raw.get("StrongBuy", 0),
                "Buy":        ar_raw.get("Buy", 0),
                "Hold":       ar_raw.get("Hold", 0),
                "Sell":       ar_raw.get("Sell", 0),
                "StrongSell": ar_raw.get("StrongSell", 0),
            }

        analysis = {
            "symbol":   symbol,
            "name":     general.get("Name", general.get("CompanyName", symbol)),
            "sector":   general.get("Sector", "Unknown"),
            "industry": general.get("Industry", "Unknown"),
            "exchange": "US",
            "data_quality": {
                "income_statement": income_q,
                "balance_sheet":    balance_q,
                "cash_flow":        cash_q,
                "min_quarters":     min_q,
                "quality":          quality,
            },
            "financial_metrics": metrics,
            "metrics_count": len([k for k, v in metrics.items() if isinstance(v, (int, float))]),
            "company_info": {
                "market_cap": market_cap,
                "pe_ratio":   highlights.get("PERatio", 0),
                "eps":        highlights.get("EPS", 0),
                "roe":        highlights.get("ReturnOnEquity", 0),
                "description": (general.get("Description", "") or "")[:300],
            },
            "analyst_ratings": analyst_ratings,
        }
        analysis["investment_scores"] = calculate_investment_scores(metrics)
        return symbol, analysis, None

    except Exception as e:
        return symbol, None, str(e)[:80]


def run_scaled_analysis(target_companies=1000, workers=8):
    """Run large-scale analysis using a thread pool for concurrent API calls."""

    print(f"SCALED ANALYSIS: {target_companies} Companies  (workers={workers})")
    print("=" * 60)

    symbols   = get_top_companies(target_companies)
    settings  = load_settings()
    api_key   = settings.eodhd_api_key

    successful_analyses: list[dict] = []
    failed_companies:    list[dict] = []
    data_quality_stats = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    lock = threading.Lock()
    done = 0

    progress_file = PROJECT_ROOT / "outputs" / "analysis_progress.json"

    def _write_progress(done: int, total: int, last_sym: str = "", last_score: float = 0.0, finished: bool = False):
        try:
            progress_file.write_text(json.dumps({
                "running":    not finished,
                "done":       done,
                "total":      total,
                "pct":        round(done / total * 100, 1) if total else 0,
                "last_sym":   last_sym,
                "last_score": round(last_score, 1),
                "successful": len(successful_analyses),
                "failed":     len(failed_companies),
                "started_at": datetime.now().isoformat(),
            }))
        except Exception:
            pass

    _write_progress(0, len(symbols))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_analyse_one, sym, api_key): sym for sym in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            symbol, analysis, err = future.result()
            with lock:
                done += 1
                if err:
                    print(f"  [{done}/{len(symbols)}] {symbol:6s}  FAIL: {err[:50]}")
                    failed_companies.append({"symbol": symbol, "reason": err})
                    _write_progress(done, len(symbols), symbol)
                else:
                    q = analysis["data_quality"]["quality"]
                    data_quality_stats[q.lower()] = data_quality_stats.get(q.lower(), 0) + 1
                    score = analysis["investment_scores"]["overall_score"]
                    cat   = analysis["investment_scores"]["investment_category"]
                    rev   = analysis["financial_metrics"].get("revenue", 0)
                    print(f"  [{done}/{len(symbols)}] {symbol:6s}  {score:5.1f}/20 {cat:9s} rev=${rev/1e9:.1f}B")
                    successful_analyses.append(analysis)
                    _write_progress(done, len(symbols), symbol, score)
    
    _write_progress(len(symbols), len(symbols), finished=True)

    # Sort by overall score
    successful_analyses.sort(key=lambda x: x.get("investment_scores", {}).get("overall_score", 0), reverse=True)
    
    # Create comprehensive summary
    summary = {
        "analysis_timestamp": datetime.now().isoformat(),
        "scale_target": target_companies,
        "total_companies_tested": len(symbols),
        "successful_analyses": len(successful_analyses),
        "failed_companies": len(failed_companies),
        "success_rate": len(successful_analyses) / len(symbols) * 100,
        "average_metrics_count": sum(a["metrics_count"] for a in successful_analyses) / len(successful_analyses) if successful_analyses else 0,
        "data_quality_stats": data_quality_stats,
        "top_performers": [
            {
                "rank": i + 1,
                "symbol": a["symbol"],
                "name": a["name"],
                "sector": a["sector"],
                "overall_score": a["investment_scores"]["overall_score"],
                "category": a["investment_scores"]["investment_category"],
                "revenue_b": a["financial_metrics"]["revenue"] / 1e9,
                "roe_pct": a["financial_metrics"]["roe"] * 100,
                "pe_ratio": a["financial_metrics"].get("pe_ratio", 0),
                "market_cap_b": a["company_info"]["market_cap"] / 1e9,
                "data_quality": a["data_quality"]["quality"]
            }
            for i, a in enumerate(successful_analyses[:20])
        ],
        "sector_breakdown": analyze_sectors(successful_analyses),
        "investment_categories": analyze_categories(successful_analyses)
    }
    
    # Save results
    settings = load_settings()
    output_dir = settings.output_dir / "scaled_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_file = output_dir / f"scaled_analysis_{timestamp}.jsonl"
    summary_file = output_dir / f"scaled_summary_{timestamp}.json"
    
    write_jsonl(analysis_file, successful_analyses)
    write_json(summary_file, summary)
    
    # Display results
    print(f"\n🎉 SCALED ANALYSIS COMPLETE!")
    print("=" * 60)
    print(f"📊 Target: {summary['scale_target']} companies")
    print(f"✅ Successful: {summary['successful_analyses']}")
    print(f"❌ Failed: {summary['failed_companies']}")
    print(f"📈 Success Rate: {summary['success_rate']:.1f}%")
    print(f"📊 Average Metrics: {summary['average_metrics_count']:.0f} per company")
    
    print(f"\n📊 Data Quality Breakdown:")
    for quality, count in data_quality_stats.items():
        pct = count / summary['successful_analyses'] * 100 if summary['successful_analyses'] > 0 else 0
        print(f"  {quality.upper()}: {count} ({pct:.1f}%)")
    
    print(f"\n🏆 Top 10 Performers:")
    for performer in summary["top_performers"][:10]:
        print(f"  {performer['rank']:2d}. {performer['symbol']} - {performer['overall_score']}/20 ({performer['category']})")
        print(f"      Revenue: ${performer['revenue_b']:.1f}B | ROE: {performer['roe_pct']:.1f}% | MCap: ${performer['market_cap_b']:.1f}B")
    
    print(f"\n📁 Results: {output_dir}")
    print(f"📊 Analysis: {analysis_file}")
    print(f"📋 Summary: {summary_file}")
    
    return successful_analyses, summary

def calculate_investment_scores(metrics):
    """
    Calculate investment scores (each sub-score 0-5, total 0-20).

    Quality  (0-5): ROE, Piotroski, FCF conversion
    Value    (0-5): PE, PB, FCF yield, EV/EBITDA
    Growth   (0-5): Owner-Earnings CAGR, ROIC, revenue growth (from metrics engine)
    Safety   (0-5): Altman Z, current ratio, debt/equity, red flags
    """

    def clamp(v, lo=0, hi=5):
        return max(lo, min(hi, v))

    # ── Quality (0-5) ────────────────────────────────────────────────────────
    q = 0.0
    roe = metrics.get("roe", 0)
    if roe >= 0.25:    q += 2.0
    elif roe >= 0.15:  q += 1.0

    piotroski = metrics.get("piotroski_score", 0)
    if piotroski >= 7:   q += 2.0
    elif piotroski >= 5: q += 1.0

    fcf_conv = metrics.get("fcf_conversion", 0)
    if fcf_conv >= 0.85: q += 1.0
    elif fcf_conv >= 0.6: q += 0.5

    # ── Value (0-5) ───────────────────────────────────────────────────────────
    v = 0.0
    pe = metrics.get("pe_ratio", 0)
    if 0 < pe <= 12:      v += 2.0
    elif 0 < pe <= 20:    v += 1.0
    elif 0 < pe <= 30:    v += 0.5

    pb = metrics.get("pb_ratio", 0)
    if 0 < pb <= 1.5:     v += 1.5
    elif 0 < pb <= 3:     v += 0.75

    fcf_yield = metrics.get("fcf_yield", 0)
    if fcf_yield >= 0.07: v += 1.0
    elif fcf_yield >= 0.04: v += 0.5

    ev_ebitda = metrics.get("ev_ebitda", 0)
    if 0 < ev_ebitda <= 8:   v += 0.5
    elif 0 < ev_ebitda <= 15: v += 0.25

    # ── Growth (0-5) — uses the Owner-Earnings composite from metrics engine ─
    growth_raw = metrics.get("growth_score_raw", 0.0)   # 0-1 from _calculate_growth_score
    g = growth_raw * 5.0

    # Also boost if short-term momentum is very strong
    oeps_cagr = metrics.get("oeps_cagr", 0.0)
    if oeps_cagr >= 0.30: g = min(g + 0.5, 5.0)

    # ── Safety (0-5) ─────────────────────────────────────────────────────────
    s = 5.0
    altman = metrics.get("altman_z_score", 0)
    if altman > 0:
        if altman < 1.8:   s -= 2.5
        elif altman < 3.0: s -= 1.0

    cr = metrics.get("current_ratio", 0)
    if cr > 0:
        if cr < 1.0:   s -= 1.5
        elif cr < 1.5: s -= 0.5

    dte = metrics.get("debt_to_equity", 0)
    if dte > 3.0:   s -= 1.5
    elif dte > 1.5: s -= 0.75

    red = metrics.get("red_flag_count", 0)
    s -= min(red * 0.5, 2.0)

    scores = {
        "quality_score":  round(clamp(q), 2),
        "value_score":    round(clamp(v), 2),
        "growth_score":   round(clamp(g), 2),
        "safety_score":   round(clamp(s), 2),
        "oeps_cagr_pct":            round(metrics.get("oeps_cagr", 0) * 100, 2),
        "owner_earnings_per_share": round(metrics.get("owner_earnings_per_share", 0), 4),
        "roic_pct":                 round(metrics.get("roic", 0) * 100, 2),
        "revenue_cagr_3y_pct":      round(metrics.get("revenue_cagr_3y", metrics.get("revenue_cagr_4y", 0)) * 100, 2),
        "gross_margin_pct":         round(metrics.get("gross_margin", 0) * 100, 2),
        "gross_margin_expansion_pp": round(metrics.get("gross_margin_expansion", 0) * 100, 2),
        "revenue_acceleration_pct":  round(metrics.get("revenue_acceleration", 0) * 100, 2),
        "peg_ratio":                round(metrics.get("peg_ratio", 0), 2),
        "reinvestment_rate":        round(metrics.get("reinvestment_rate", 0), 3),
    }

    overall = scores["quality_score"] + scores["value_score"] + scores["growth_score"] + scores["safety_score"]
    scores["overall_score"] = round(overall, 2)

    if overall >= 16:   scores["investment_category"] = "EXCELLENT"
    elif overall >= 12: scores["investment_category"] = "GOOD"
    elif overall >= 8:  scores["investment_category"] = "FAIR"
    elif overall >= 4:  scores["investment_category"] = "POOR"
    else:               scores["investment_category"] = "RISKY"

    # ── 10x Candidate Score (0-100) ───────────────────────────────────────────
    # Weighted combination of the signals Lynch/Buffett most associate with multi-baggers:
    # High ROIC + high revenue growth + margin expansion + small-ish market cap + PEG < 2
    mktcap_b    = metrics.get("market_cap", 0) / 1e9
    rev_cagr    = metrics.get("revenue_cagr_4y", metrics.get("revenue_cagr_3y", 0))
    gm_exp      = metrics.get("gross_margin_expansion", 0)
    peg         = metrics.get("peg_ratio", 0)
    roic        = metrics.get("roic", 0)
    rev_accel   = metrics.get("revenue_acceleration", 0)

    tx = 0.0
    # ROIC > 20% signals durable competitive moat with high-return reinvestment
    tx += min(roic / 0.40, 1.0) * 25      # max 25 pts at 40% ROIC
    # Revenue CAGR — 10x companies grow fast (40%+ = full credit)
    tx += min(rev_cagr / 0.40, 1.0) * 25  # max 25 pts at 40% CAGR
    # PEG < 1 = Lynch sweet spot; above 3 gets 0
    if 0 < peg <= 3:
        tx += max(0, (3 - peg) / 3) * 20  # max 20 pts at PEG→0
    # Margin expansion (positive = operating leverage kicking in)
    tx += min(max(gm_exp / 0.10, 0), 1.0) * 15  # max 15 pts at +10pp expansion
    # Revenue acceleration (is growth rate itself growing?)
    tx += min(max(rev_accel / 0.15, 0), 1.0) * 10  # max 10 pts
    # Small/mid cap bonus — more runway than mega-caps
    if 0 < mktcap_b < 10:    tx += 5
    elif 0 < mktcap_b < 50:  tx += 2

    scores["tenx_score"] = round(min(tx, 100), 1)

    return scores

def analyze_sectors(analyses):
    """Analyze performance by sector."""
    sectors = {}
    for analysis in analyses:
        sector = analysis.get("sector", "Unknown")
        if sector not in sectors:
            sectors[sector] = {"count": 0, "total_score": 0, "companies": []}
        
        sectors[sector]["count"] += 1
        sectors[sector]["total_score"] += analysis.get("investment_scores", {}).get("overall_score", 0)
        sectors[sector]["companies"].append(analysis["symbol"])
    
    # Calculate averages
    for sector in sectors:
        sectors[sector]["average_score"] = sectors[sector]["total_score"] / sectors[sector]["count"]
        sectors[sector]["companies"] = sectors[sector]["companies"][:5]  # Top 5 companies
    
    return sectors

def analyze_categories(analyses):
    """Analyze investment categories distribution."""
    categories = {}
    for analysis in analyses:
        category = analysis.get("investment_scores", {}).get("investment_category", "UNKNOWN")
        categories[category] = categories.get(category, 0) + 1
    
    return categories

if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser()
    _p.add_argument("--target",  type=int, default=1000)
    _p.add_argument("--workers", type=int, default=20)
    _args = _p.parse_args()
    run_scaled_analysis(target_companies=_args.target, workers=_args.workers)
