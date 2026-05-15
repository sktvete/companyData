"""Quick scan of top-10 ranked companies after margin normalization."""
import json, importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "app", str(Path(__file__).resolve().parent.parent / "web" / "app_enhanced.py")
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

p = Path(__file__).resolve().parent.parent / "outputs" / "scaled_analysis" / "scaled_analysis_20260513_222058.jsonl"
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
app.companies = rows
app.company_lookup = {c["symbol"]: c for c in rows}
out = app.filter_sort(None, None, 0, "listing_score", "desc", "", 5, 5, 5, 5, 0)


def sf(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


for i, c in enumerate(out[:10], 1):
    s = c.get("investment_scores") or {}
    fm = c.get("financial_metrics") or {}
    ci = c.get("company_info") or {}
    ls = round(app._compounder_list_score(c), 2)
    sym = c["symbol"]
    mcr = app._margin_cycle_ratio(sym)
    mcr_s = f"{mcr:.1f}x" if mcr > 0 else "n/a"

    mcap = sf(ci.get("market_cap")) / 1e9
    rev = sf(fm.get("revenue") or fm.get("total_revenue")) / 1e9
    ni = sf(fm.get("net_income")) / 1e9
    roe = sf(ci.get("roe")) * 100
    roic = sf(s.get("roic_pct"))
    pe = sf(ci.get("pe_ratio"))
    gm = sf(s.get("gross_margin_pct"))
    rev_cagr = sf(s.get("revenue_cagr_3y_pct"))
    oeps = sf(s.get("oeps_cagr_pct"))
    de = sf(fm.get("debt_to_equity"))

    name = c.get("name") or sym
    print(f"=== #{i} {sym} - {name} ===")
    print(f"  Sector: {c.get('sector')}  |  Industry: {c.get('industry')}")
    print(f"  Listing Score: {ls}  |  Q:{s.get('quality_score',0)}/5  V:{s.get('value_score',0)}/5  G:{s.get('growth_score',0)}/5  S:{s.get('safety_score',0)}/5")
    print(f"  Market Cap: ${mcap:.1f}B  |  Revenue: ${rev:.1f}B  |  Net Income: ${ni:.2f}B")
    print(f"  ROE: {roe:.1f}%  |  ROIC: {roic:.1f}%  |  P/E: {pe:.1f}  |  Gross Margin: {gm:.1f}%")
    print(f"  Rev CAGR 3y: {rev_cagr:.1f}%  |  OEPS CAGR: {oeps:.1f}%  |  D/E: {de:.2f}")
    print(f"  Margin Ratio (current/median): {mcr_s}")
    print()
