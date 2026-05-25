#!/usr/bin/env python3

"""
Scale Analysis to 1,000+ Companies
Large-scale comprehensive analysis with real EODHD data.

CLI examples:
  python scripts/scale_analysis_1000.py --target 3804 --workers 48
  python scripts/scale_analysis_1000.py --symbols-file outputs/scaled_analysis/scaled_failed_symbols_*.txt \\
      --merge-into outputs/scaled_analysis/scaled_analysis_*.jsonl --workers 32
"""

import sys
import io
import json
import time
import os
import asyncio
import platform
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

# Load .env BEFORE importing Settings (defaults are evaluated at import time)
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_jsonl, write_json
from equity_sorter.canonical.comprehensive_metrics import (
    calculate_comprehensive_metrics,
    rate_as_decimal,
    _calculate_growth_score,
)
from equity_sorter.providers.eodhd.client import EODHDClient, EODHDRequest
from equity_sorter.cache import FundamentalsCache
from eodhd_analyst import extract_analyst_ratings

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

def _load_symbols_from_file(path: Path) -> list[str]:
    """One symbol per line; # comments; optional CSV (first column). Deduplicated, order preserved."""
    return [sym for sym, _ in _load_symbol_exchange_pairs(path)]


def _load_symbol_exchange_pairs(path: Path, default_exchange: str = "US") -> list[tuple[str, str]]:
    """SYMBOL or SYMBOL,EXCHANGE per line (e.g. EQNR,OL)."""
    text = path.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip().upper() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        sym = parts[0]
        ex = parts[1] if len(parts) > 1 else default_exchange
        key = (sym, ex)
        if sym and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def get_top_companies(limit: int = 1000, symbols_file: Path | None = None) -> list[str]:
    """
    Get list of companies to analyze.
    If ``symbols_file`` is set, load that list (then apply ``limit``).
    Else priority order:
      1. outputs/company_universe.json  (built by discover_companies.py)
      2. outputs/symbol_list.txt
      3. Hardcoded S&P-500-like list (fallback)
    Run `python scripts/discover_companies.py --limit 2000` to build the universe.
      Sector slice: `python scripts/discover_companies.py --sector Energy --limit 500`
      → use `outputs/symbol_list_sector_energy.txt` with `--symbols-file`.
    """
    import json as _json

    if symbols_file is not None:
        p = Path(symbols_file)
        if not p.is_file():
            print(f"⚠️  Symbols file not found: {p}")
            return []
        syms = _load_symbols_from_file(p)
        print(f"📋  Loaded {len(syms)} symbols from {p.name}")
        return syms[:limit]

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
_DB_PATH      = PROJECT_ROOT / "outputs" / "fundamentals.db"
_DB_CACHE: FundamentalsCache | None = None
_DB_LOCK = threading.Lock()


def _get_db() -> FundamentalsCache:
    """Lazy singleton for the SQLite cache."""
    global _DB_CACHE
    if _DB_CACHE is None:
        with _DB_LOCK:
            if _DB_CACHE is None:
                _DB_CACHE = FundamentalsCache(_DB_PATH, ttl_hours=CACHE_TTL_H)
    return _DB_CACHE


def _load_cached(symbol: str) -> dict | None:
    """Return cached fundamentals if present and fresh (SQLite first, JSON fallback)."""
    db = _get_db()
    hit = db.get(symbol)
    if hit is not None:
        return hit
    # Fallback to legacy JSON file
    f = CACHE_DIR / f"{symbol}.json"
    if not f.exists():
        return None
    age_h = (time.time() - f.stat().st_mtime) / 3600
    if age_h > CACHE_TTL_H:
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        # Migrate to SQLite on read
        if data:
            db.put(symbol, data)
        return data
    except Exception:
        return None


def _save_cache(symbol: str, data: dict) -> None:
    """Save to SQLite (primary) and JSON (legacy fallback)."""
    db = _get_db()
    db.put(symbol, data)
    # Also write JSON for backward compat
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (CACHE_DIR / f"{symbol}.json").write_text(
            json.dumps(data, separators=(",", ":")), encoding="utf-8"
        )
    except Exception:
        pass


_SHARED_SESSION: requests.Session | None = None
_SESSION_LOCK = threading.Lock()


def _get_session() -> requests.Session:
    """Return a shared requests.Session with connection pooling."""
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        with _SESSION_LOCK:
            if _SHARED_SESSION is None:
                import requests.adapters
                s = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=64, pool_maxsize=64, max_retries=2
                )
                s.mount("https://", adapter)
                s.mount("http://", adapter)
                _SHARED_SESSION = s
    return _SHARED_SESSION


def _normalize_exchange_code(exchange: str) -> str:
    ex = (exchange or "US").strip().upper()
    if ex in ("OL", "OS", "XOSL", "OSE"):
        return "OL"
    if ex in ("ST", "STO", "XSTO", "SSE"):
        return "ST"
    if ex in ("CO", "CPH", "XCSE", "CPSE"):
        return "CO"
    if ex in ("HE", "HEL", "XHEL"):
        return "HE"
    return ex or "US"


def _eodhd_symbol(symbol: str, exchange: str = "US") -> str:
    sym = symbol.strip().upper()
    if "." in sym:
        base, suf = sym.rsplit(".", 1)
        if base and len(suf) <= 6:
            return sym
    ex = _normalize_exchange_code(exchange)
    if ex == "US":
        return f"{sym}.US"
    return f"{sym}.{ex}"


def _analyse_one(
    symbol: str,
    api_key: str,
    exchange: str = "US",
) -> tuple[str, dict | None, str | None]:
    """Fetch + score a single symbol. Caches raw fundamentals to disk (TTL=24h)."""
    try:
        fundamentals = _load_cached(symbol)
        eodhd_sym = _eodhd_symbol(symbol, exchange)
        if fundamentals is None:
            last_err = ""
            session = _get_session()
            client = EODHDClient(api_key=api_key, session=session)
            for attempt in range(3):
                try:
                    raw = client.get_json(
                        EODHDRequest(endpoint=f"fundamentals/{eodhd_sym}", params={})
                    )
                    if raw and isinstance(raw, dict) and raw.get("General"):
                        _save_cache(symbol, raw)
                        fundamentals = raw
                        break
                    last_err = "Empty or missing General"
                    fundamentals = None
                except Exception as ex:
                    last_err = str(ex)[:500]
                    fundamentals = None
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
            if not fundamentals:
                msg = "No fundamental data"
                if last_err:
                    msg = f"{msg}: {last_err[:220]}"
                return symbol, None, msg

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

        metrics = calculate_comprehensive_metrics(financials, price_data, highlights=highlights)
        if "error" in metrics:
            err_detail = metrics.get("error")
            msg = "Metrics calculation failed"
            if isinstance(err_detail, str) and err_detail.strip():
                msg = f"{msg}: {err_detail.strip()[:400]}"
            return symbol, None, msg

        analyst_ratings = extract_analyst_ratings(fundamentals)

        currency_code = general.get("CurrencyCode", "USD") or "USD"
        exchange_name = general.get("Exchange", "") or ""
        is_primary = exchange_name.upper() in ("NYSE", "NASDAQ", "AMEX", "NYQ", "NMS", "NGM", "NCM")
        ex_code = _normalize_exchange_code(exchange)

        analysis = {
            "symbol":   symbol,
            "name":     general.get("Name", general.get("CompanyName", symbol)),
            "sector":   general.get("Sector", "Unknown"),
            "industry": general.get("Industry", "Unknown"),
            "exchange": ex_code,
            "currency_code": currency_code,
            "is_primary_listing": is_primary,
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
        analysis["investment_scores"] = calculate_investment_scores(
            metrics, is_primary_listing=is_primary,
            sector=general.get("Sector", ""),
            industry=general.get("Industry", ""),
        )
        return symbol, analysis, None

    except Exception as e:
        return symbol, None, str(e)[:500]


def _merge_with_base(base_path: Path, new_rows: list[dict]) -> list[dict]:
    """Union by symbol; ``new_rows`` overwrite same symbol in base. Sorted by overall_score desc."""
    base = read_jsonl(base_path) if base_path.is_file() else []
    by_sym = {r["symbol"]: r for r in base if r.get("symbol")}
    for r in new_rows:
        sym = r.get("symbol")
        if sym:
            by_sym[sym] = r
    return sorted(
        by_sym.values(),
        key=lambda x: x.get("investment_scores", {}).get("overall_score", 0),
        reverse=True,
    )


def run_scaled_analysis(
    target_companies: int = 1000,
    workers: int = 8,
    symbols_file: Path | None = None,
    merge_into: Path | None = None,
    exchange: str = "US",
):
    """Run large-scale analysis using a thread pool for concurrent API calls."""

    if symbols_file is not None and Path(symbols_file).is_file():
        pairs = _load_symbol_exchange_pairs(Path(symbols_file), default_exchange=exchange)
        pairs = pairs[:target_companies]
        print(f"📋  Loaded {len(pairs)} symbol+exchange pairs from {Path(symbols_file).name}")
    else:
        pairs = [(s, exchange) for s in get_top_companies(target_companies, symbols_file=symbols_file)]
    if not pairs:
        print("⚠️  No symbols to analyze — exiting.")
        return [], {}

    tag = f"{len(pairs)} companies"
    if symbols_file:
        tag = f"{len(pairs)} companies from {Path(symbols_file).name}"
    print(f"SCALED ANALYSIS: {tag}  (workers={workers})")
    print("=" * 60)

    settings = load_settings()
    api_key   = settings.eodhd_api_key

    successful_analyses: list[dict] = []
    failed_companies:    list[dict] = []
    data_quality_stats = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    lock = threading.Lock()
    done = 0

    progress_file = PROJECT_ROOT / "outputs" / "analysis_progress.json"

    def _write_progress(done: int, total: int, last_sym: str = "", last_score: float = 0.0, finished: bool = False):
        try:
            payload = json.dumps({
                "running":    not finished,
                "done":       done,
                "total":      total,
                "pct":        round(done / total * 100, 1) if total else 0,
                "last_sym":   last_sym,
                "last_score": round(last_score, 1),
                "successful": len(successful_analyses),
                "failed":     len(failed_companies),
                "started_at": datetime.now().isoformat(),
            })
            tmp = progress_file.with_suffix(progress_file.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(progress_file)
        except Exception:
            pass

    _write_progress(0, len(pairs))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_analyse_one, sym, api_key, ex): sym for sym, ex in pairs
        }
        for future in as_completed(futures):
            sym = futures[future]
            symbol, analysis, err = future.result()
            with lock:
                done += 1
                if err:
                    print(f"  [{done}/{len(pairs)}] {symbol:6s}  FAIL: {err[:50]}")
                    failed_companies.append({"symbol": symbol, "reason": err})
                    _write_progress(done, len(pairs), symbol)
                else:
                    q = analysis["data_quality"]["quality"]
                    data_quality_stats[q.lower()] = data_quality_stats.get(q.lower(), 0) + 1
                    score = analysis["investment_scores"]["overall_score"]
                    cat   = analysis["investment_scores"]["investment_category"]
                    rev   = analysis["financial_metrics"].get("revenue", 0)
                    print(f"  [{done}/{len(pairs)}] {symbol:6s}  {score:5.1f}/20 {cat:9s} rev=${rev/1e9:.1f}B")
                    successful_analyses.append(analysis)
                    _write_progress(done, len(pairs), symbol, score)
    
    _write_progress(len(pairs), len(pairs), finished=True)

    # Sort this batch by overall score
    successful_analyses.sort(
        key=lambda x: x.get("investment_scores", {}).get("overall_score", 0),
        reverse=True,
    )

    merge_path = Path(merge_into) if merge_into else None
    if merge_path is not None and merge_path.is_file():
        output_rows = _merge_with_base(merge_path, successful_analyses)
        print(
            f"🔗 Merged batch into {merge_path.name}: "
            f"+{len(successful_analyses)} ok / {len(pairs)} tested → {len(output_rows)} rows in output"
        )
    elif merge_path is not None:
        print(f"⚠️  --merge-into not found ({merge_path}) — writing batch only")
        output_rows = successful_analyses
    else:
        output_rows = successful_analyses

    n_sym = len(pairs)
    batch_ok = len(successful_analyses)
    batch_fail = len(failed_companies)
    success_rate = (batch_ok / n_sym * 100) if n_sym else 0.0

    stats_for_summary: dict[str, int] = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    for a in output_rows:
        q = (a.get("data_quality") or {}).get("quality", "POOR")
        stats_for_summary[q.lower()] = stats_for_summary.get(q.lower(), 0) + 1

    avg_metrics = (
        sum(a["metrics_count"] for a in output_rows) / len(output_rows) if output_rows else 0
    )

    # Create comprehensive summary
    summary = {
        "analysis_timestamp": datetime.now().isoformat(),
        "scale_target": target_companies,
        "total_companies_tested": n_sym,
        "successful_analyses": len(output_rows),
        "failed_companies": batch_fail,
        "failed_companies_details": sorted(
            failed_companies, key=lambda x: x.get("symbol", "")
        ),
        "batch_successful": batch_ok,
        "batch_success_rate_pct": round(success_rate, 3),
        "success_rate": success_rate,
        "average_metrics_count": avg_metrics,
        "data_quality_stats": stats_for_summary,
        "merge_base": str(merge_path.resolve()) if merge_path and merge_path.is_file() else None,
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
                "data_quality": a["data_quality"]["quality"],
            }
            for i, a in enumerate(output_rows[:20])
        ],
        "sector_breakdown": analyze_sectors(output_rows),
        "investment_categories": analyze_categories(output_rows),
    }

    # Save results
    output_dir = settings.output_dir / "scaled_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_file = output_dir / f"scaled_analysis_{timestamp}.jsonl"
    summary_file = output_dir / f"scaled_summary_{timestamp}.json"

    write_jsonl(analysis_file, output_rows)
    write_json(summary_file, summary)
    if failed_companies:
        failed_file = output_dir / f"scaled_failed_{timestamp}.jsonl"
        write_jsonl(failed_file, failed_companies)
        print(f"📋 Failures log: {failed_file}")

    # Display results
    print(f"\n🎉 SCALED ANALYSIS COMPLETE!")
    print("=" * 60)
    print(f"📊 This batch: tested={n_sym}  ok={batch_ok}  fail={batch_fail}")
    print(f"📄 Output JSONL rows: {len(output_rows)}")
    print(f"📈 Batch success rate: {success_rate:.1f}%")
    print(f"📊 Avg metrics (output file): {avg_metrics:.0f} per company")

    print(f"\n📊 Data quality (output file):")
    for quality, count in stats_for_summary.items():
        denom = len(output_rows) or 1
        pct = count / denom * 100
        print(f"  {quality.upper()}: {count} ({pct:.1f}%)")

    print(f"\n🏆 Top 10 Performers (output file):")
    for performer in summary["top_performers"][:10]:
        print(f"  {performer['rank']:2d}. {performer['symbol']} - {performer['overall_score']}/20 ({performer['category']})")
        print(f"      Revenue: ${performer['revenue_b']:.1f}B | ROE: {performer['roe_pct']:.1f}% | MCap: ${performer['market_cap_b']:.1f}B")

    print(f"\n📁 Results: {output_dir}")
    print(f"📊 Analysis: {analysis_file}")
    print(f"📋 Summary: {summary_file}")

    return output_rows, summary

def calculate_investment_scores(metrics, *, is_primary_listing: bool = True,
                                sector: str = "", industry: str = ""):
    """
    Calculate investment scores (each sub-score 0-5, total 0-20).

    Quality  (0-5): ROE, Piotroski, FCF conversion
    Value    (0-5): PE, PB, FCF yield, EV/EBITDA
    Growth   (0-5): Owner-Earnings CAGR, ROIC, revenue growth (from metrics engine)
    Safety   (0-5): Altman Z, current ratio, debt/equity, red flags

    Sector-aware adjustments:
      - Cyclical sectors (Basic Materials, Energy) get growth scores capped and
        overall confidence penalized when earnings growth far outpaces revenue.
      - Non-primary listings (OTC, ADR) get a 0.90x confidence haircut.
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
    # Growth-adjusted valuation: PEG is the primary signal for compounders.
    # A company growing EPS 50%/yr at P/E 40 (PEG 0.8) is cheaper than one
    # growing 5%/yr at P/E 15 (PEG 3.0).
    v = 0.0
    peg = metrics.get("peg_ratio", 0)
    if 0 < peg <= 0.5:       v += 2.5
    elif 0 < peg <= 0.8:     v += 2.0
    elif 0 < peg <= 1.2:     v += 1.5
    elif 0 < peg <= 1.5:     v += 1.0
    elif 0 < peg <= 2.0:     v += 0.5

    pe = metrics.get("pe_ratio", 0)
    if 0 < pe <= 12:      v += 1.0
    elif 0 < pe <= 18:    v += 0.75
    elif 0 < pe <= 25:    v += 0.5
    elif 0 < pe <= 35:    v += 0.25

    fcf_yield = metrics.get("fcf_yield", 0)
    if fcf_yield >= 0.08:   v += 1.0
    elif fcf_yield >= 0.05: v += 0.75
    elif fcf_yield >= 0.03: v += 0.5
    elif fcf_yield >= 0.015: v += 0.25

    ev_ebitda = metrics.get("ev_ebitda", 0)
    if 0 < ev_ebitda <= 10:  v += 0.5
    elif 0 < ev_ebitda <= 18: v += 0.25

    # Always derive from latest growth logic (merged JSONL can carry stale growth_score_raw).
    growth_raw = _calculate_growth_score(metrics)
    metrics["growth_score_raw"] = growth_raw
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

    # ── Cyclical sector adjustments ────────────────────────────────────────
    # Commodity companies (gold miners, oil producers) look like perfect
    # compounders near cycle peaks: low P/E, explosive earnings growth, high
    # ROIC.  But the "growth" is price-driven and mean-reverts.  Penalize so
    # they don't crowd out genuine compounders.
    sector_l = (sector or "").strip().lower()
    industry_l = (industry or "").strip().lower()
    _CYCLICAL_SECTORS = {"basic materials", "energy"}
    _CYCLICAL_INDUSTRIES = {"gold", "silver", "copper", "mining", "coal",
                            "steel", "aluminum", "oil", "gas"}
    _CYCLICAL_TECH_KW = {"memory", "storage", "dram", "nand"}
    is_cyclical = (
        sector_l in _CYCLICAL_SECTORS
        or any(kw in industry_l for kw in _CYCLICAL_INDUSTRIES)
        or (sector_l == "technology" and any(kw in industry_l for kw in _CYCLICAL_TECH_KW))
    )
    # Also flag as cyclical based on revenue growth consistency: very volatile
    # growth (consistency < 0.3) with high magnitude means commodity-driven.
    _rc = metrics.get("revenue_growth_consistency")
    rev_consistency = float(_rc) if _rc is not None else 0.5
    if rev_consistency < 0.3 and sector_l == "technology" and "semiconductor" in industry_l:
        is_cyclical = True
    if is_cyclical:
        ni_g = metrics.get("net_income_growth", 0) or 0
        rev_best = max(
            metrics.get("revenue_cagr_4y", 0) or 0,
            metrics.get("revenue_cagr_3y", 0) or 0,
        )
        # Earnings growth far outpacing revenue = commodity price, not volume
        if ni_g > 0.20 and (rev_best < 0.10 or ni_g > rev_best * 2.5):
            g = min(g, 3.0)
        # Very low P/E in cyclicals signals peak earnings, not value
        _pe = metrics.get("pe_ratio", 0)
        if 0 < _pe < 12:
            v = min(v, 3.0)

    scores = {
        "quality_score":  round(clamp(q), 2),
        "value_score":    round(clamp(v), 2),
        "growth_score":   round(clamp(g), 2),
        "safety_score":   round(clamp(s), 2),
        "oeps_cagr_pct":            round(metrics.get("oeps_cagr", 0) * 100, 2),
        "owner_earnings_per_share": round(metrics.get("owner_earnings_per_share", 0), 4),
        "roic_pct":                 round(rate_as_decimal(metrics.get("roic", 0) or 0) * 100, 2),
        "revenue_cagr_3y_pct":      round(metrics.get("revenue_cagr_3y", metrics.get("revenue_cagr_4y", 0)) * 100, 2),
        "gross_margin_pct":         round(metrics.get("gross_margin", 0) * 100, 2),
        "gross_margin_expansion_pp": round(metrics.get("gross_margin_expansion", 0) * 100, 2),
        "revenue_acceleration_pct":  round(metrics.get("revenue_acceleration", 0) * 100, 2),
        "peg_ratio":                round(metrics.get("peg_ratio", 0), 2),
        "reinvestment_rate":        round(metrics.get("reinvestment_rate", 0), 3),
        "revenue_growth_consistency": round(metrics.get("revenue_growth_consistency", 0.5), 3),
    }

    overall = scores["quality_score"] + scores["value_score"] + scores["growth_score"] + scores["safety_score"]

    if is_cyclical:
        overall *= 0.88
    if not is_primary_listing:
        overall *= 0.90

    scores["overall_score"] = round(overall, 2)
    scores["is_primary_listing"] = is_primary_listing
    scores["is_cyclical"] = is_cyclical

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
    gm_raw      = metrics.get("gross_margin", 0)
    gm_exp_raw  = metrics.get("gross_margin_expansion", 0)
    if gm_raw > 0.85 or gm_raw < 0:
        gm_exp = 0.0
    else:
        gm_exp = max(-0.15, min(0.15, gm_exp_raw))
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
        sector = analysis.get("sector") or "Unknown"
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

def _score_from_blob(sym_blob_pair: tuple[str, bytes]) -> tuple[str, dict | None, str | None]:
    """Decompress + score a single (symbol, compressed_blob) pair. No I/O."""
    import zlib as _zlib
    sym, blob = sym_blob_pair
    try:
        data = json.loads(_zlib.decompress(blob))
    except Exception:
        return sym, None, "Cannot decompress"
    return _score_single((sym, data))


def _score_single(sym_data_pair: tuple[str, dict]) -> tuple[str, dict | None, str | None]:
    """Score a single (symbol, fundamentals_dict) pair. Pure CPU, no I/O."""
    sym, data = sym_data_pair
    if not data or not isinstance(data, dict) or not data.get("General"):
        return sym, None, "Invalid cache data"
    try:
        financials = extract_financial_data_correct(data)
        income_q = len(financials["income_statement"])
        balance_q = len(financials["balance_sheet"])
        cash_q = len(financials["cash_flow"])
        min_q = min(income_q, balance_q, cash_q)

        if min_q >= 100:   quality = "EXCELLENT"
        elif min_q >= 40:  quality = "GOOD"
        elif min_q >= 20:  quality = "FAIR"
        else:              quality = "POOR"

        if min_q < 4:
            return sym, None, "Insufficient data"

        general = data.get("General", {})
        highlights = data.get("Highlights", {})
        market_cap = float(highlights.get("MarketCapitalization") or 1_000_000_000_000)

        price_data = [{
            "date": "2024-12-31",
            "close": market_cap / 1_000_000_000,
            "market_cap": market_cap,
            "enterprise_value": market_cap * 1.2,
        }]

        metrics = calculate_comprehensive_metrics(financials, price_data, highlights=highlights)
        if "error" in metrics:
            return sym, None, f"Metrics failed: {metrics.get('error', '')[:200]}"

        analyst_ratings = extract_analyst_ratings(data)

        currency_code = general.get("CurrencyCode", "USD") or "USD"
        exchange_name = general.get("Exchange", "") or ""
        is_primary = exchange_name.upper() in ("NYSE", "NASDAQ", "AMEX", "NYQ", "NMS", "NGM", "NCM")

        analysis = {
            "symbol": sym,
            "name": general.get("Name", general.get("CompanyName", sym)),
            "sector": general.get("Sector", "Unknown"),
            "industry": general.get("Industry", "Unknown"),
            "exchange": "US",
            "currency_code": currency_code,
            "is_primary_listing": is_primary,
            "data_quality": {
                "income_statement": income_q,
                "balance_sheet": balance_q,
                "cash_flow": cash_q,
                "min_quarters": min_q,
                "quality": quality,
            },
            "financial_metrics": metrics,
            "metrics_count": len([k for k, v in metrics.items() if isinstance(v, (int, float))]),
            "company_info": {
                "market_cap": market_cap,
                "pe_ratio": highlights.get("PERatio", 0),
                "eps": highlights.get("EPS", 0),
                "roe": highlights.get("ReturnOnEquity", 0),
                "description": (general.get("Description", "") or "")[:300],
            },
            "analyst_ratings": analyst_ratings,
        }
        analysis["investment_scores"] = calculate_investment_scores(
            metrics, is_primary_listing=is_primary,
            sector=general.get("Sector", ""),
            industry=general.get("Industry", ""),
        )
        return sym, analysis, None
    except Exception as e:
        return sym, None, str(e)[:200]


def _rescore_executor(n_symbols: int, workers: int) -> tuple[type, int, int]:
    """Process pool on Linux/macOS for large batches; threads on Windows (stable under Flask subprocess)."""
    cpus = os.cpu_count() or 8
    w = max(1, min(workers, cpus))
    chunksize = max(1, n_symbols // (w * 16)) if n_symbols >= 400 else 1
    if platform.system() == "Windows" or n_symbols < 800:
        return ThreadPoolExecutor, w, chunksize
    return ProcessPoolExecutor, w, chunksize


def run_cache_only_rescore(merge_into: Path | None = None, workers: int = 48):
    """Re-score ALL symbols from SQLite cache without any API calls.

    Phase 1: Bulk-read all data from SQLite (single sequential scan)
    Phase 2: Decompress + score in parallel (process pool when n >= 400)
    """
    db = _get_db()
    n_total = db.count()
    if n_total == 0:
        print("No data in SQLite cache. Run migration first or use --workers mode.")
        return

    progress_file = PROJECT_ROOT / "outputs" / "analysis_progress.json"

    def _write_progress(done: int, total: int, last_sym: str = "", last_score: float = 0.0,
                        successful: int = 0, failed_n: int = 0, finished: bool = False, phase: str = ""):
        try:
            payload = json.dumps({
                "running":    not finished,
                "done":       done,
                "total":      total,
                "pct":        round(done / total * 100, 1) if total else 0,
                "last_sym":   last_sym,
                "last_score": round(last_score, 1),
                "successful": successful,
                "failed":     failed_n,
                "started_at": datetime.now().isoformat(),
                "phase":      phase,
            })
            tmp = progress_file.with_suffix(progress_file.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(progress_file)
        except Exception:
            pass

    print(f"CACHE-ONLY RESCORE: {n_total} symbols  (workers={workers})")
    print("=" * 60)

    _write_progress(0, n_total, phase="Reading cache")

    t0 = time.time()
    print("  [phase 1] Reading raw blobs from SQLite...", flush=True)
    raw_pairs = db.get_all_raw()  # [(sym, compressed_bytes), ...]
    t_read = time.time() - t0
    print(f"  [phase 1] Read {len(raw_pairs)} blobs in {t_read:.1f}s", flush=True)

    _write_progress(0, len(raw_pairs), phase="Scoring")

    pool_cls, pool_workers, chunksize = _rescore_executor(len(raw_pairs), workers)
    pool_label = "processes" if pool_cls is ProcessPoolExecutor else "threads"
    print(f"  [phase 2] Decompress + score ({pool_workers} {pool_label}, chunksize={chunksize})...", flush=True)
    t1 = time.time()
    results = []
    failed = []
    done_count = 0
    last_score = 0.0

    with pool_cls(max_workers=pool_workers) as pool:
        for sym, analysis, err in pool.map(_score_from_blob, raw_pairs, chunksize=chunksize):
            done_count += 1
            if err:
                failed.append({"symbol": sym, "reason": err})
            else:
                results.append(analysis)
                last_score = analysis.get("investment_scores", {}).get("overall_score", 0)
            if done_count % 200 == 0 or done_count == len(raw_pairs):
                _write_progress(done_count, len(raw_pairs), sym, last_score if not err else 0,
                                successful=len(results), failed_n=len(failed), phase="Scoring")
            if done_count % 1000 == 0:
                print(f"  [{done_count}/{len(raw_pairs)}] ...", flush=True)

    t_score = time.time() - t1
    elapsed = time.time() - t0
    results.sort(key=lambda x: x.get("investment_scores", {}).get("overall_score", 0), reverse=True)

    merge_path = Path(merge_into) if merge_into else None
    if merge_path and merge_path.is_file():
        results = _merge_with_base(merge_path, results)

    output_dir = PROJECT_ROOT / "outputs" / "scaled_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = output_dir / f"scaled_analysis_{timestamp}.jsonl"

    write_jsonl(out_file, results)
    _write_progress(len(raw_pairs), len(raw_pairs), successful=len(results),
                    failed_n=len(failed), finished=True, phase="Done")
    print(f"\n  DONE — {len(results)} scored, {len(failed)} failed")
    print(f"  Read:  {t_read:.1f}s  |  Score: {t_score:.1f}s  |  Total: {elapsed:.1f}s")
    print(f"  Speed: {len(raw_pairs)/elapsed:.0f} symbols/sec")
    print(f"  Output: {out_file}")
    return results


def _default_fetch_concurrency() -> int:
    try:
        return max(20, min(300, int(os.environ.get("EODHD_FETCH_CONCURRENCY", "200"))))
    except ValueError:
        return 200


async def _async_fetch_batch(
    symbols: list[str],
    api_key: str,
    concurrency: int = 100,
    *,
    progress_cb=None,
    write_batch: int = 64,
) -> list[tuple[str, dict | None, str | None]]:
    """Async EODHD fundamentals fetch with batched SQLite writes (avoids per-row commit)."""
    import aiohttp

    if not symbols:
        return []

    db = _get_db()
    concurrency = max(10, min(300, concurrency))
    sem = asyncio.Semaphore(concurrency)
    pending: list[tuple[str, dict]] = []
    pend_lock = asyncio.Lock()
    done = 0

    async def _flush() -> None:
        async with pend_lock:
            if not pending:
                return
            batch = pending[:]
            pending.clear()
        await asyncio.to_thread(db.put_many, batch)

    async def _enqueue(sym: str, data: dict) -> int:
        nonlocal done
        async with pend_lock:
            pending.append((sym, data))
            flush_now = len(pending) >= write_batch
        if flush_now:
            await _flush()
        done += 1
        return done

    async def _fetch_one(session: aiohttp.ClientSession, sym: str):
        eodhd_sym = sym if "." in sym else f"{sym}.US"
        url = f"https://eodhd.com/api/fundamentals/{eodhd_sym}"
        params = {"api_token": api_key, "fmt": "json"}
        async with sem:
            for attempt in range(3):
                try:
                    async with session.get(url, params=params) as resp:
                        if resp.status == 429:
                            await asyncio.sleep(1.0 + attempt * 1.5)
                            continue
                        if resp.status == 200:
                            data = await resp.json()
                            if data and isinstance(data, dict) and data.get("General"):
                                n = await _enqueue(sym, data)
                                if n % 50 == 0:
                                    print(f"    [{n}/{len(symbols)}] ...", flush=True)
                                    if progress_cb:
                                        progress_cb(n, len(symbols))
                                return sym, data, None
                            return sym, None, "Empty payload"
                        return sym, None, f"HTTP {resp.status}"
                except Exception as ex:
                    if attempt < 2:
                        await asyncio.sleep(0.35 * (attempt + 1))
                    else:
                        return sym, None, str(ex)[:150]
        return sym, None, "Max retries"

    connector = aiohttp.TCPConnector(
        limit=concurrency,
        limit_per_host=concurrency,
        ttl_dns_cache=600,
    )
    timeout = aiohttp.ClientTimeout(total=90, connect=12, sock_read=60)
    batch_size = max(50, min(500, int(os.environ.get("EODHD_FETCH_BATCH", "400"))))
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        results: list = []
        for off in range(0, len(symbols), batch_size):
            chunk = symbols[off : off + batch_size]
            results.extend(await asyncio.gather(*[_fetch_one(session, s) for s in chunk]))
    await _flush()
    return list(results)


async def run_async_fetch(
    symbols: list[str],
    api_key: str,
    concurrency: int = 100,
) -> list[tuple[str, dict | None, str | None]]:
    """Fetch fundamentals for many symbols using async HTTP (aiohttp)."""
    return await _async_fetch_batch(symbols, api_key, concurrency)


def run_refresh_and_score(
    target_companies: int = 1000,
    workers: int = 48,
    concurrency: int | None = None,
    symbols_file: Path | None = None,
    merge_into: Path | None = None,
):
    """Full pipeline: async-fetch stale/missing symbols, then rescore entire universe.

    Much faster than the old threaded approach:
    - Phase 1: Identify stale/missing symbols
    - Phase 2: Async-fetch only what's needed (100 concurrent requests)
    - Phase 3: Score everything from SQLite cache
    """
    import asyncio

    settings = load_settings()
    api_key = settings.eodhd_api_key
    db = _get_db()
    if concurrency is None:
        concurrency = _default_fetch_concurrency()

    symbols = get_top_companies(target_companies, symbols_file=symbols_file)
    if not symbols:
        print("No symbols to process.")
        return

    progress_file = PROJECT_ROOT / "outputs" / "analysis_progress.json"

    def _write_progress(done: int, total: int, last_sym: str = "", last_score: float = 0.0,
                        successful: int = 0, failed_n: int = 0, finished: bool = False, phase: str = ""):
        try:
            payload = json.dumps({
                "running":    not finished,
                "done":       done,
                "total":      total,
                "pct":        round(done / total * 100, 1) if total else 0,
                "last_sym":   last_sym,
                "last_score": round(last_score, 1),
                "successful": successful,
                "failed":     failed_n,
                "started_at": datetime.now().isoformat(),
                "phase":      phase,
            })
            tmp = progress_file.with_suffix(progress_file.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(progress_file)
        except Exception:
            pass

    stale = set(db.stale_symbols())
    missing = set(db.missing_symbols(symbols))
    need_fetch = [s for s in symbols if s in stale or s in missing]

    already_cached = db.count()
    total_work = len(need_fetch) + already_cached
    print(f"REFRESH + SCORE: {len(symbols)} symbols")
    print(f"  Cache: {already_cached} total, {len(stale)} stale, {len(missing)} missing")
    print(f"  Need to fetch: {len(need_fetch)} symbols (async, {concurrency} concurrent)")
    print("=" * 60)

    # Start progress at already_cached so the bar reflects true overall completion
    _write_progress(already_cached, total_work, phase=f"Fetching {len(need_fetch)} new symbols")

    if need_fetch:
        t0 = time.time()
        fetch_results = asyncio.run(_async_fetch_batch(need_fetch, api_key, concurrency,
                                                       progress_cb=lambda d, t: _write_progress(
                                                           already_cached + d, total_work,
                                                           phase=f"Fetching ({d}/{t})")))
        ok = sum(1 for _, d, _ in fetch_results if d is not None)
        t_fetch = time.time() - t0
        print(f"  Fetched: {ok}/{len(need_fetch)} in {t_fetch:.1f}s ({ok/max(t_fetch,0.1):.0f}/sec)")
        _write_progress(total_work, total_work, successful=ok,
                        failed_n=len(need_fetch) - ok, phase="Scoring from cache")
    else:
        print("  All symbols fresh in cache — skipping fetch.")
        _write_progress(total_work, total_work, phase="Scoring from cache")

    print("\n  Running full rescore from SQLite...")
    run_cache_only_rescore(merge_into=merge_into, workers=workers)


if __name__ == "__main__":
    import argparse as _ap

    _p = _ap.ArgumentParser(description="Scaled EODHD fundamentals + scoring (JSONL output).")
    _p.add_argument("--target", type=int, default=1000, help="Max symbols from universe")
    _p.add_argument("--workers", type=int, default=48)
    _p.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="Async HTTP concurrency (0 = EODHD_FETCH_CONCURRENCY env or 200)",
    )
    _p.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        help="Path to text file: one ticker per line (# comments ok). Overrides company_universe.json.",
    )
    _p.add_argument(
        "--merge-into",
        type=Path,
        default=None,
        help="Existing scaled_analysis *.jsonl to merge with this batch (new/updated symbols win).",
    )
    _p.add_argument(
        "--exchange",
        type=str,
        default="US",
        help="EODHD exchange suffix for symbols in --symbols-file (e.g. OL for Oslo: ANDF → ANDF.OL).",
    )
    _p.add_argument(
        "--cache-only",
        action="store_true",
        help="Re-score all cached symbols without API calls. Fastest mode (~30s for 5,000 symbols).",
    )
    _p.add_argument(
        "--refresh",
        action="store_true",
        help="Async-fetch stale/missing symbols, then rescore entire universe.",
    )
    _args = _p.parse_args()

    progress_file = PROJECT_ROOT / "outputs" / "analysis_progress.json"

    def _fatal_progress(exc: BaseException) -> None:
        try:
            payload = json.dumps({
                "running": False,
                "done": 0,
                "total": 0,
                "pct": 0,
                "error": str(exc)[:500],
                "phase": "Failed",
            })
            tmp = progress_file.with_suffix(progress_file.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(progress_file)
        except Exception:
            pass

    try:
        if _args.cache_only:
            run_cache_only_rescore(merge_into=_args.merge_into, workers=_args.workers)
        elif _args.refresh:
            conc = _args.concurrency or _default_fetch_concurrency()
            run_refresh_and_score(
                target_companies=_args.target,
                workers=_args.workers,
                concurrency=conc,
                symbols_file=_args.symbols_file,
                merge_into=_args.merge_into,
            )
        else:
            run_scaled_analysis(
                target_companies=_args.target,
                workers=_args.workers,
                symbols_file=_args.symbols_file,
                merge_into=_args.merge_into,
                exchange=_args.exchange,
            )
    except Exception as ex:
        _fatal_progress(ex)
        raise
