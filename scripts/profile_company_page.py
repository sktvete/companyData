"""Profile /company/<symbol> load: HTTP endpoints + server-side breakdown."""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))

SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else "SBGSF").upper()
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 2

_timings: list[tuple[str, float]] = []


@contextmanager
def span(name: str):
    t0 = time.perf_counter()
    yield
    ms = (time.perf_counter() - t0) * 1000
    _timings.append((name, ms))


def _print_table(rows: list[tuple[str, float]], title: str) -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("(no data)")
        return
    w = max(len(r[0]) for r in rows)
    total = sum(ms for _, ms in rows)
    for name, ms in sorted(rows, key=lambda x: -x[1]):
        pct = (ms / total * 100) if total else 0
        bar = "#" * int(pct / 5)
        print(f"  {name:<{w}}  {ms:8.1f} ms  ({pct:5.1f}%)  {bar}")
    print(f"  {'TOTAL':<{w}}  {total:8.1f} ms")


def profile_history_internals(symbol: str) -> None:
    """Step through api_company_history logic with timers."""
    import app_enhanced as app

    app.load_data()
    _timings.clear()

    with span("get_company (memory)"):
        co = app.get_company(symbol)

    with span("_get_fundamentals"):
        d = app._get_fundamentals(symbol)

    if not d:
        print("No fundamentals — aborting breakdown")
        return

    with span("build annual history loop"):
        annual = d.get("Financials", {}).get("Income_Statement", {}).get("yearly", {})
        bs_ann = d.get("Financials", {}).get("Balance_Sheet", {}).get("yearly", {})
        cf_ann = d.get("Financials", {}).get("Cash_Flow", {}).get("yearly", {})
        shares_stats = d.get("SharesStats", {})
        shares_out = app._safe_float(shares_stats.get("SharesOutstanding")) or 1.0
        history = []
        for yr in sorted(annual.keys(), reverse=True)[:15]:
            inc = annual[yr]
            bs = bs_ann.get(yr, {})
            cf = cf_ann.get(yr, {})
            rev = app._safe_float(inc.get("totalRevenue"))
            ni = app._safe_float(inc.get("netIncome"))
            history.append({"year": yr[:4], "revenue_usd": rev, "net_income_usd": ni})

    with span("_fetch_full_price_history"):
        price_data = app._fetch_full_price_history(symbol)

    with span("attach P/E to history years"):
        price_by_date = {p["date"]: p["close"] for p in price_data} if price_data else {}
        from datetime import datetime, timedelta as _td

        for entry in history:
            yr = entry["year"]
            ye_price = None
            for d_offset in range(0, 10):
                try_date = (datetime(int(yr), 12, 31) - _td(days=d_offset)).strftime("%Y-%m-%d")
                if try_date in price_by_date:
                    ye_price = price_by_date[try_date]
                    break

    q_inc = d.get("Financials", {}).get("Income_Statement", {}).get("quarterly", {})
    q_cf = d.get("Financials", {}).get("Cash_Flow", {}).get("quarterly", {})
    _hl = app._merged_highlights(d)

    with span("_build_ttm_window (1Y)"):
        ttm = app._build_ttm_window(
            q_inc, q_cf, shares_stats, shares_out, price_data, trailing_years=1, highlights=_hl
        )

    with span("_build_ttm_window (2Y)"):
        ttm2 = app._build_ttm_window(
            q_inc, q_cf, shares_stats, shares_out, price_data, trailing_years=2, highlights=_hl
        )

    with span("earnings trend / estimates"):
        trend = d.get("Earnings", {}).get("Trend", {})
        _ = list(trend.keys())

    with span("_analyst_ratings_for_company (yfinance?)"):
        ar = app._analyst_ratings_for_company({**(co or {}), "symbol": symbol})

    with span("_build_quarterly_report_events (SEC)"):
        qr = app._build_quarterly_report_events(d)

    with span("json.dumps history payload"):
        payload = {
            "history_len": len(history),
            "price_points": len(price_data or []),
            "quarterly_reports": len(qr),
            "analyst": bool(ar),
        }
        blob = json.dumps(payload)

    print(f"  price bars: {len(price_data or [])}, SEC report markers: {len(qr)}")
    _print_table(_timings, f"/history internals — {symbol}")


def http_timings(base: str, symbol: str, runs: int) -> list[tuple[str, float]]:
    import urllib.request

    paths = [
        ("HTML  GET /company/{sym}", f"/company/{symbol}"),
        ("API   GET /api/company/{sym}", f"/api/company/{symbol}"),
        ("API   GET /history", f"/api/company/{symbol}/history"),
        ("API   GET /price-history 1y", f"/api/company/{symbol}/price-history?range=1y"),
        ("API   GET /price-history max", f"/api/company/{symbol}/price-history?range=max"),
        ("API   GET /auth/status", "/api/auth/status"),
    ]
    results: list[tuple[str, float]] = []
    print(f"\n=== HTTP timings ({runs} run(s), warm cache) — {symbol} ===")
    for label, path in paths:
        times: list[float] = []
        size = 0
        for i in range(runs):
            url = base + path
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=120) as resp:
                body = resp.read()
            ms = (time.perf_counter() - t0) * 1000
            times.append(ms)
            size = len(body)
        avg = sum(times) / len(times)
        tag = " (cold)" if runs > 1 and times[0] > avg * 1.4 else ""
        print(f"  {label:<32}  avg {avg:7.0f} ms  last {times[-1]:7.0f} ms  {size/1024:6.1f} KB{tag}")
        results.append((label, avg))
    return results


def main() -> None:
    base = "http://127.0.0.1:3000"
    print(f"Profiling company page load for {SYMBOL}")
    print("(Server must be running on :3000)\n")

    try:
        http_rows = http_timings(base, SYMBOL, RUNS)
    except Exception as e:
        print(f"HTTP probe failed: {e}")
        print("Start server: python run_server.py")
        http_rows = []

    profile_history_internals(SYMBOL)

    if http_rows:
        print("\n=== Load waterfall (browser order) ===")
        html = next((ms for k, ms in http_rows if "HTML" in k), 0)
        hist = next((ms for k, ms in http_rows if "history" in k), 0)
        price = next((ms for k, ms in http_rows if "price-history 1y" in k), 0)
        auth = next((ms for k, ms in http_rows if "auth" in k), 0)
        seq = [
            ("1. HTML page (SSR + analyst + fundamentals for technicals)", html),
            ("2. /history (financials + price + SEC + analyst again)", hist),
            ("3. Client Chart.js: 5 fin charts + P/E (after history)", 0),
            ("4. /price-history 1y (after idle; refetches full prices)", price),
            ("5. /auth/status (chat panel)", auth),
        ]
        crit = html + hist + price
        for step, ms in seq:
            note = ""
            if ms == 0 and "Chart" in step:
                note = " ~50–200ms typical in-browser (not measured here)"
            print(f"  {step:<55} {ms:7.0f} ms{note}")
        print(f"\n  Critical path (server, steps 1+2+4): ~{crit:.0f} ms")
        print("\n  Notes:")
        print("  • /history and /price-history both call _fetch_full_price_history (duplicate work).")
        print("  • Analyst yfinance may run on HTML render AND again in /history.")
        print("  • SEC submissions fetch runs inside /history for US CIK tickers.")


if __name__ == "__main__":
    main()
