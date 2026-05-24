"""Single stock analysis CLI.

Usage:
    python -m scripts.analyze_stock --ticker AAPL.US --json
    python -m scripts.analyze_stock --ticker NVDA.US --pretty
    python -m scripts.analyze_stock --ticker TSLA.US --output result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

from .eodhd_client import EodhdClient, TickerNotFoundError, normalize_ticker
from .metrics import compute_all_metrics, safe_float
from .scoring import apply_hard_rules, compute_all_scores


def _count_insider_net_buys(fundamentals: dict[str, Any]) -> int:
    """Count net insider buy vs sell transactions in the last 12 months."""
    transactions = fundamentals.get("InsiderTransactions") or {}
    if isinstance(transactions, dict):
        transactions = list(transactions.values())
    if not isinstance(transactions, list):
        return 0

    buys = 0
    sells = 0
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        tx_type = (tx.get("transactionType") or tx.get("ownershipType") or "").lower()
        if "buy" in tx_type or "purchase" in tx_type:
            buys += 1
        elif "sale" in tx_type or "sell" in tx_type:
            sells += 1
    return buys - sells


def _get_analyst_target(fundamentals: dict[str, Any]) -> float | None:
    ar = fundamentals.get("AnalystRatings") or {}
    return safe_float(ar.get("TargetPrice"))


def analyze_single(ticker: str, client: EodhdClient | None = None) -> dict[str, Any]:
    """Run full analysis on a single ticker. Returns schema-compliant dict."""
    if client is None:
        client = EodhdClient()

    ticker = normalize_ticker(ticker)
    raw = client.fetch_all_for_analysis(ticker)

    fundamentals = raw.get("fundamentals") or {}
    if not fundamentals or "General" not in fundamentals:
        return _error_result(ticker, f"No fundamental data returned for {ticker}")

    all_metrics = compute_all_metrics(raw)

    all_metrics["analyst_target_price"] = _get_analyst_target(fundamentals)
    all_metrics["insider_net_buys"] = _count_insider_net_buys(fundamentals)

    score_result = compute_all_scores(all_metrics)
    scores = score_result["scores"]
    overall = score_result["overall_score"]
    red_flags = score_result["red_flags"]

    recommendation, confidence, hard_rule_notes = apply_hard_rules(
        scores, overall, all_metrics, red_flags,
    )

    general = fundamentals.get("General") or {}
    symbol = ticker.split(".")[0]
    exchange = ticker.split(".")[-1] if "." in ticker else "US"

    key_metrics = all_metrics["key_metrics"]
    # Round float metrics for clean output
    for k, v in key_metrics.items():
        if isinstance(v, float):
            key_metrics[k] = round(v, 6)

    bull_case = _build_bull_case(all_metrics, scores)
    bear_case = _build_bear_case(all_metrics, scores, red_flags)

    sources = []
    if raw.get("fundamentals"):
        sources.append({"name": "EODHD", "url_or_endpoint": f"/api/v1.1/fundamentals/{ticker}", "used_for": "fundamentals"})
    if raw.get("eod_prices"):
        sources.append({"name": "EODHD", "url_or_endpoint": f"/api/eod/{ticker}", "used_for": "technical indicators"})
    if raw.get("live_price"):
        sources.append({"name": "EODHD", "url_or_endpoint": f"/api/real-time/{ticker}", "used_for": "current price"})
    if raw.get("news"):
        sources.append({"name": "EODHD", "url_or_endpoint": f"/api/news?s={ticker}", "used_for": "news/sentiment"})

    result: dict[str, Any] = {
        "ticker": symbol,
        "exchange": exchange,
        "company_name": general.get("Name"),
        "currency": general.get("CurrencyCode"),
        "analysis_date": date.today().isoformat(),
        "time_horizon": "long_term_1y_plus",
        "recommendation": recommendation,
        "confidence": confidence,
        "overall_score": overall,
        "scores": scores,
        "key_metrics": key_metrics,
        "decision_summary": {
            "bull_case": bull_case,
            "bear_case": bear_case,
            "main_reason_for_recommendation": hard_rule_notes[0] if hard_rule_notes else _main_reason(recommendation, overall, scores),
            "what_would_change_the_decision": _what_would_change(recommendation, all_metrics, scores),
        },
        "red_flags": red_flags,
        "data_quality": {
            "eodhd_available": True,
            "external_sources_used": [],
            "missing_fields": all_metrics.get("missing_fields", []),
            "stale_fields": [],
            "data_confidence": confidence,
        },
        "sources": sources,
    }
    return result


def _error_result(ticker: str, error: str) -> dict[str, Any]:
    symbol = ticker.split(".")[0] if "." in ticker else ticker
    exchange = ticker.split(".")[-1] if "." in ticker else "US"
    return {
        "ticker": symbol,
        "exchange": exchange,
        "company_name": None,
        "currency": None,
        "analysis_date": date.today().isoformat(),
        "time_horizon": "long_term_1y_plus",
        "recommendation": "no_buy",
        "confidence": "low",
        "overall_score": 0,
        "scores": {
            "growth_score": 0, "quality_score": 0, "valuation_score": 0,
            "balance_sheet_score": 0, "earnings_quality_score": 0,
            "catalyst_score": 0, "sentiment_score": 0, "technical_score": 0,
            "risk_red_flag_score": 0,
        },
        "key_metrics": {},
        "decision_summary": {
            "bull_case": ["Insufficient data"],
            "bear_case": [error],
            "main_reason_for_recommendation": error,
            "what_would_change_the_decision": ["Data availability from EODHD"],
        },
        "red_flags": [],
        "data_quality": {
            "eodhd_available": False,
            "external_sources_used": [],
            "missing_fields": ["all"],
            "stale_fields": [],
            "data_confidence": "low",
        },
        "sources": [],
    }


def _build_bull_case(metrics: dict[str, Any], scores: dict[str, int]) -> list[str]:
    cases: list[tuple[int, str]] = []  # (priority, text)
    km = metrics.get("key_metrics", {})

    rg = km.get("revenue_growth_yoy")
    if rg is not None and rg > 0.20:
        cases.append((100, f"Strong revenue growth: {rg*100:.1f}% YoY"))
    elif rg is not None and rg > 0.05:
        cases.append((60, f"Steady revenue growth: {rg*100:.1f}% YoY"))

    gm = km.get("gross_margin")
    if gm is not None and gm > 0.60:
        cases.append((85, f"High gross margin: {gm*100:.1f}% — strong pricing power"))
    elif gm is not None and gm > 0.40:
        cases.append((50, f"Healthy gross margin: {gm*100:.1f}%"))

    om = km.get("operating_margin")
    if om is not None and om > 0.25:
        cases.append((80, f"Strong operating margin: {om*100:.1f}%"))
    elif om is not None and om > 0.15:
        cases.append((55, f"Solid operating margin: {om*100:.1f}%"))

    fy = km.get("fcf_yield")
    if fy is not None and fy > 0.04:
        cases.append((75, f"Attractive FCF yield: {fy*100:.1f}%"))
    elif fy is not None and fy > 0.02:
        cases.append((45, f"Positive FCF yield: {fy*100:.1f}%"))

    nd = km.get("net_debt_to_ebitda")
    if nd is not None and nd < 0:
        cases.append((70, "Net cash position — no net debt"))
    elif nd is not None and nd < 1:
        cases.append((40, f"Conservative leverage: net debt/EBITDA = {nd:.1f}x"))

    roic = km.get("roic")
    if roic is not None and roic > 0.20:
        cases.append((65, f"High return on capital: {roic*100:.1f}%"))

    dil = metrics.get("dilution", {}).get("dilution_1y")
    if dil is not None and dil < -0.02:
        cases.append((55, f"Active buyback program: shares declining {abs(dil)*100:.1f}% YoY"))

    eq = metrics.get("earnings_quality", {}).get("fcf_to_net_income")
    if eq is not None and eq > 1.0:
        cases.append((50, f"High earnings quality: FCF/NI ratio = {eq:.2f}x"))

    cagr = km.get("revenue_cagr_3y")
    if cagr is not None and cagr > 0.15:
        cases.append((70, f"Consistent multi-year growth: 3Y revenue CAGR = {cagr*100:.1f}%"))

    cases.sort(key=lambda x: x[0], reverse=True)
    result = [c[1] for c in cases[:4]]
    if not result:
        result = ["Limited positive signals identified in available data"]
    return result


def _build_bear_case(metrics: dict[str, Any], scores: dict[str, int], red_flags: list) -> list[str]:
    cases: list[tuple[int, str]] = []
    km = metrics.get("key_metrics", {})

    for rf in red_flags:
        sev_score = {"high": 90, "medium": 60, "low": 40}.get(rf.get("severity", ""), 50)
        cases.append((sev_score, rf["description"]))

    pe = km.get("pe_ratio")
    if pe is not None and pe > 60:
        cases.append((75, f"Very elevated P/E: {pe:.1f}x — expensive relative to earnings"))
    elif pe is not None and pe > 35:
        cases.append((50, f"Elevated P/E ratio: {pe:.1f}x"))

    peg = km.get("peg_ratio")
    if peg is not None and peg > 3:
        cases.append((65, f"Stretched PEG ratio: {peg:.1f}x — paying too much for growth"))

    rsi = km.get("rsi")
    if rsi is not None and rsi > 75:
        cases.append((45, f"Overbought: RSI = {rsi:.0f}"))

    pv200 = km.get("price_vs_200dma")
    if pv200 is not None and pv200 > 50:
        cases.append((55, f"Extended {pv200:.0f}% above 200-day moving average"))

    om = km.get("operating_margin")
    if om is not None and om < 0:
        cases.append((70, f"Negative operating margin: {om*100:.1f}% — not yet profitable"))

    dte = km.get("debt_to_equity")
    if dte is not None and dte > 2:
        cases.append((60, f"High leverage: debt-to-equity = {dte:.2f}"))

    rg = km.get("revenue_growth_yoy")
    if rg is not None and rg < 0:
        cases.append((70, f"Revenue declining: {rg*100:.1f}% YoY"))

    fy = km.get("fcf_yield")
    if fy is not None and fy < 0:
        cases.append((65, "Negative free cash flow"))

    missing = metrics.get("missing_fields", [])
    if len(missing) > 3:
        cases.append((40, f"Data gaps: {len(missing)} key metrics unavailable from EODHD"))

    cases.sort(key=lambda x: x[0], reverse=True)
    result = [c[1] for c in cases[:4]]
    if not result:
        result = ["No significant risk factors identified in available data"]
    return result


def _main_reason(rec: str, overall: int, scores: dict[str, int]) -> str:
    # Find the strongest driver (highest/lowest score) to cite specifically
    category_map = {
        "growth_score": "growth", "quality_score": "quality",
        "valuation_score": "valuation", "balance_sheet_score": "balance sheet",
    }
    if rec == "buy":
        best = max(category_map.items(), key=lambda x: scores.get(x[0], 0))
        return f"Strong {best[1]} fundamentals ({best[0].replace('_score','')} score: {scores[best[0]]}) support a buy at current levels"
    elif rec == "watchlist":
        weakest = min(category_map.items(), key=lambda x: scores.get(x[0], 50))
        if scores.get(weakest[0], 50) < 50:
            return f"Solid business fundamentals held back by weak {weakest[1]} ({scores[weakest[0]]})"
        return f"Mixed signals across scoring categories prevent a confident buy recommendation"
    else:
        weakest = min(category_map.items(), key=lambda x: scores.get(x[0], 50))
        return f"Weak {weakest[1]} fundamentals ({weakest[0].replace('_score','')}: {scores[weakest[0]]}) drive a no-buy verdict"


def _what_would_change(rec: str, metrics: dict[str, Any], scores: dict[str, int]) -> list[str]:
    changes = []
    km = metrics.get("key_metrics", {})
    if rec == "no_buy":
        rg = km.get("revenue_growth_yoy")
        if rg is not None and rg < 0:
            changes.append("Return to positive revenue growth for 2+ consecutive quarters")
        else:
            changes.append("Sustained revenue growth acceleration for 2+ quarters")
        om = km.get("operating_margin")
        if om is not None and om < 0.05:
            changes.append("Operating margin expansion above 10%")
        fy = km.get("fcf_yield")
        if fy is not None and fy < 0:
            changes.append("Positive free cash flow generation")
        else:
            changes.append("Improvement in earnings quality and cash flow consistency")
        if scores.get("balance_sheet_score", 50) < 40:
            changes.append("Meaningful debt reduction or deleveraging progress")
    elif rec == "watchlist":
        if scores.get("valuation_score", 50) < 50:
            pe = km.get("pe_ratio")
            target = f" (e.g., P/E below {int(pe*0.75)})" if pe and pe > 20 else ""
            changes.append(f"Price correction to more attractive valuation{target}")
        if scores.get("growth_score", 50) < 50:
            changes.append("Revenue growth reacceleration above 10% YoY")
        changes.append("Continued earnings beats and upward estimate revisions")
    else:
        changes.append("Deterioration in revenue growth below 5% for 2+ quarters")
        changes.append("Margin contraction exceeding 300bps")
        changes.append("Emergence of significant red flags (governance, regulatory, competitive)")
    return changes[:3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a single stock")
    parser.add_argument("--ticker", "-t", required=True, help="Ticker in SYMBOL.EXCHANGE format (e.g., AAPL.US)")
    parser.add_argument("--json", action="store_true", help="Output compact JSON")
    parser.add_argument("--pretty", action="store_true", help="Output formatted JSON")
    parser.add_argument("--output", "-o", type=str, help="Write output to file")
    parser.add_argument("--cache-ttl", type=int, default=21600, help="Cache TTL in seconds (default: 6h)")
    args = parser.parse_args()

    client = EodhdClient(cache_ttl=args.cache_ttl)

    try:
        result = analyze_single(args.ticker, client)
    except TickerNotFoundError:
        print(f"ERROR: Ticker not found: {args.ticker}", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None
    output = json.dumps(result, indent=indent, default=str)

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
