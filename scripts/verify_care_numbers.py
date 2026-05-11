"""One-off verification: CARE analysis JSONL vs API vs fundamentals cache."""
from __future__ import annotations

import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.io_utils import read_jsonl  # noqa: E402

import app_enhanced as ae  # noqa: E402


def safe_float(x, d: float = 0.0) -> float:
    if x is None:
        return d
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", ""))
    except (TypeError, ValueError):
        return d


def main() -> int:
    scaled = PROJECT_ROOT / "outputs/scaled_analysis/scaled_analysis_20260511_215720.jsonl"
    care_row = next(r for r in read_jsonl(scaled) if r.get("symbol") == "CARE")
    cache_path = PROJECT_ROOT / "outputs/fundamentals_cache/CARE.json"
    raw = json.loads(cache_path.read_text(encoding="utf-8"))

    ae.companies = [care_row]
    ae.company_lookup = {"CARE": care_row}
    ae.DATA_SOURCE = "scaled (CARE verification)"
    ae._get_fundamentals = lambda s: raw if s.upper() == "CARE" else None

    client = ae.app.test_client()
    api = client.get("/api/company/CARE").get_json()
    hist = client.get("/api/company/CARE/history").get_json()

    m, ci, s = care_row["financial_metrics"], care_row["company_info"], care_row["investment_scores"]
    fm, api_ci = api["financial_metrics"], api["company_info"]

    checks: list[tuple[str, bool, object, object, float]] = []

    def near(name: str, a: object, b: object, atol: float) -> None:
        ok = (
            isinstance(a, (int, float))
            and isinstance(b, (int, float))
            and abs(float(a) - float(b)) <= atol
        )
        checks.append((name, ok, a, b, atol))

    near("revenue_b", fm["revenue_b"], m["revenue"] / 1e9, 0.02)
    near("net_income_b", fm["net_income_b"], m["net_income"] / 1e9, 0.02)
    near("owner_earnings_b", fm["owner_earnings_b"], m["owner_earnings"] / 1e9, 0.002)
    near("oeps", fm["oeps"], m["owner_earnings_per_share"], 0.0001)
    near("roe_pct", fm["roe_pct"], m["roe"] * 100, 0.2)
    near("roic_pct", fm["roic_pct"], m["roic"] * 100, 0.2)
    near("gross_margin_pct", fm["gross_margin_pct"], m["gross_margin"] * 100, 0.2)
    near("net_margin_pct", fm["net_margin_pct"], m["net_margin"] * 100, 0.2)
    near("pe_ratio", fm["pe_ratio"], ci.get("pe_ratio") or m.get("pe_ratio", 0), 0.02)
    near("market_cap_b", api_ci["market_cap_b"], ci["market_cap"] / 1e9, 0.02)
    near("overall_score", api["investment_scores"]["overall_score"], s["overall_score"], 0.01)
    near("quality_score", api["investment_scores"]["quality_score"], s["quality_score"], 0.01)

    annual = raw["Financials"]["Income_Statement"]["yearly"]
    bs_ann = raw["Financials"]["Balance_Sheet"]["yearly"]
    cf_ann = raw["Financials"]["Cash_Flow"]["yearly"]
    sh_stats = raw.get("SharesStats", {})
    sh_out = float(sh_stats.get("SharesOutstanding") or 1)

    yr = sorted(annual.keys(), reverse=True)[0]
    inc, bs, cf = annual[yr], bs_ann.get(yr, {}), cf_ann.get(yr, {})
    rev = safe_float(inc.get("totalRevenue"))
    ni = safe_float(inc.get("netIncome"))
    ocf = safe_float(cf.get("totalCashFromOperatingActivities"))
    capex = abs(safe_float(cf.get("capitalExpenditures")))
    sbc = safe_float(cf.get("stockBasedCompensation"))
    eq = safe_float(bs.get("totalStockholderEquity")) or 1.0
    sh = safe_float(bs.get("commonStockSharesOutstanding"))
    if not sh:
        sh = safe_float(inc.get("weightedAverageShsOutDil") or inc.get("weightedAverageShsOut"))
    if not sh:
        sh = sh_out or 1.0
    eps = ni / sh if sh else 0.0
    fcf = ocf - capex
    oe = ocf - capex - sbc
    oeps = oe / sh if sh else 0.0

    h0 = hist["history"][0]
    y_ok = str(h0["year"]) == str(yr[:4])
    checks.append(("hist[0].year", y_ok, h0["year"], yr[:4], 0.0))
    near("hist[0].revenue_b", h0["revenue_b"], rev / 1e9, 0.02)
    near("hist[0].net_income_b", h0["net_income_b"], ni / 1e9, 0.02)
    near("hist[0].eps", h0["eps"], eps, 0.0001)
    near("hist[0].oeps", h0["oeps"], oeps, 0.0001)
    near("hist[0].fcf_b", h0["fcf_b"], fcf / 1e9, 0.02)
    near("hist[0].owner_earnings_b", h0["owner_earnings_b"], oe / 1e9, 0.02)
    gp = safe_float(inc.get("grossProfit"))
    near("hist[0].gross_margin_pct", h0["gross_margin_pct"], (gp / rev * 100) if rev else 0, 0.2)
    near("hist[0].net_margin_pct", h0["net_margin_pct"], (ni / rev * 100) if rev else 0, 0.2)
    near("hist[0].roe_pct", h0["roe_pct"], (ni / eq * 100) if eq else 0, 0.2)

    hl = raw.get("Highlights", {})
    near("hist eps_ttm", hist["eps_ttm"], safe_float(hl.get("EarningsShare")), 0.02)
    near("hist pe_ttm", hist["pe_ttm"], safe_float(hl.get("PERatio")), 0.05)
    near("hist market_cap_b", hist["market_cap_b"], safe_float(hl.get("MarketCapitalization")) / 1e9, 0.05)

    ar_raw = raw.get("AnalystRatings", {})
    ar_api = hist.get("analyst_ratings")
    exp_rating = round(float(ar_raw.get("Rating") or ar_raw.get("rating") or 0), 2)
    near("analyst rating", ar_api["rating"], exp_rating, 0.01)
    near("analyst target", ar_api["target_price"], float(ar_raw.get("TargetPrice") or 0), 0.02)

    failed = [c for c in checks if not c[1]]
    print("CARE: scaled JSONL row vs /api/company; CARE.json vs /api/company/CARE/history")
    print("History fiscal key:", yr)
    print("Checks:", len(checks), "failed:", len(failed))
    for name, ok, a, b, tol in checks:
        tag = "OK" if ok else "FAIL"
        print(f"  [{tag}] {name}: got={a!r} expected={b!r} (tol={tol})")
    if failed:
        return 1
    print(
        "\nLive app note: load_data() prefers rescored_analysis; CARE may be missing",
        "from that file while still present in scaled_analysis.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
