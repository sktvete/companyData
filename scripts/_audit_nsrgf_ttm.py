"""Audit NSRGF TTM vs quarters vs annual."""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from equity_sorter.cache import FundamentalsCache

sym = "NSRGF"
c = FundamentalsCache(Path(__file__).resolve().parents[1] / "outputs" / "fundamentals.db", ttl_hours=9999)
d = c.get(sym, ignore_ttl=True)
if not d:
    print("no fundamentals cache for", sym)
    raise SystemExit(1)

q_inc = d.get("Financials", {}).get("Income_Statement", {}).get("quarterly", {})
q_cf = d.get("Financials", {}).get("Cash_Flow", {}).get("quarterly", {})
y_inc = d.get("Financials", {}).get("Income_Statement", {}).get("yearly", {})

keys = sorted(q_inc.keys(), reverse=True)[:8]
print("=== Last 8 quarters (income) ===")
for k in keys:
    inc = q_inc[k]
    rev = inc.get("totalRevenue")
    ni = inc.get("netIncome")
    print(f"  {k}: revenue={rev!r} netIncome={ni!r}")

q4 = sorted(q_inc.keys(), reverse=True)[:4]
ttm_rev = sum(float(q_inc[k].get("totalRevenue") or 0) for k in q4)
ttm_ni = sum(float(q_inc[k].get("netIncome") or 0) for k in q4)
print("\n=== Manual TTM (sum last 4 quarters) ===")
print("  quarters:", q4)
print(f"  revenue_usd: {ttm_rev:,.0f}  ({ttm_rev/1e9:.2f}B)")
print(f"  net_income_usd: {ttm_ni:,.0f}  ({ttm_ni/1e9:.2f}B)")
if ttm_rev:
    print(f"  net margin: {100*ttm_ni/ttm_rev:.1f}%")

print("\n=== Latest 3 annual (EODHD yearly keys) ===")
for k in sorted(y_inc.keys(), reverse=True)[:3]:
    inc = y_inc[k]
    print(f"  {k}: revenue={inc.get('totalRevenue')} ni={inc.get('netIncome')}")

h = json.load(urllib.request.urlopen(f"http://localhost:3000/api/company/{sym}/history"))
for label, block in (("TTM (1Y)", h.get("ttm")), ("TTM2 (2Y avg)", h.get("ttm2"))):
    t = block or {}
    print(f"\n=== API /history {label} ===")
    for k in (
        "year",
        "fiscal_year",
        "period_end",
        "trailing_years",
        "revenue_b",
        "revenue_b_total",
        "net_income_b",
        "gross_margin_pct",
        "net_margin_pct",
        "eps",
        "oeps",
    ):
        print(f"  {k}: {t.get(k)}")
print("\n=== Estimates ===")
for e in h.get("estimates") or []:
    print(f"  {e.get('year')} fy={e.get('fiscal_year')} rev_b={e.get('revenue_b')} ni_b={e.get('net_income_b')}")

print("\n=== Snapshot financial_metrics (sidebar) ===")
snap = json.load(urllib.request.urlopen(f"http://localhost:3000/api/company/{sym}"))
m = snap.get("financial_metrics") or {}
print(f"  revenue_b: {round(float(m.get('revenue',0))/1e9, 2)}")
print(f"  net_income: {m.get('net_income')}")
print(f"  gross_margin: {m.get('gross_margin')}")
print(f"  pe: {(snap.get('company_info') or {}).get('pe_ratio')}")
