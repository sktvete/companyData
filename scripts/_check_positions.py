"""Check positions and details for specific symbols."""
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

targets = ["MSFT", "GOOGL", "AMZN", "META", "NVDA", "AAPL", "V", "MA", "COST", "NFLX", "TJX", "ISRG", "CAT", "GFI", "DRD", "GWW", "ADBE", "PYPL", "JPM"]
print(f"{'Sym':<6} {'Rank':>4} {'Score':>6}  {'Q':>3} {'V':>3} {'G':>3} {'S':>3}  {'MCap':>8} {'P/E':>5} {'RevCAGR':>7} {'OEPS':>6} {'MR':>4}")
print("-" * 80)
for sym in targets:
    for i, c in enumerate(out, 1):
        if c["symbol"] == sym:
            s = c.get("investment_scores") or {}
            ci = c.get("company_info") or {}
            ls = round(app._compounder_list_score(c), 2)
            mcr = app._margin_cycle_ratio(sym)
            mcap = float(ci.get("market_cap") or 0) / 1e9
            rev_cagr = float(s.get("revenue_cagr_3y_pct") or 0)
            oeps = float(s.get("oeps_cagr_pct") or 0)
            pe = float(ci.get("pe_ratio") or 0)
            q = s.get("quality_score", 0)
            v = s.get("value_score", 0)
            g = s.get("growth_score", 0)
            sf = s.get("safety_score", 0)
            mcr_s = f"{mcr:.1f}x" if mcr > 0 else "n/a"
            print(f"{sym:<6} {i:>4} {ls:>6}  {q:>3} {v:>3} {g:>3} {sf:>3}  ${mcap:>6.0f}B {pe:>5.0f} {rev_cagr:>6.0f}% {oeps:>5.0f}% {mcr_s:>5}")
            break
