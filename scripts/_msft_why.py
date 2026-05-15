import sys, os
os.chdir(os.path.join(r"c:\Users\sktve\Documents\projects\companyData", "web"))
sys.path.insert(0, ".")
import app_enhanced
app_enhanced.load_data()
companies = app_enhanced.companies

msft = next(c for c in companies if c.get("symbol") == "MSFT")
s = msft.get("investment_scores", {})
m = msft.get("financial_metrics", {})
ci = msft.get("company_info", {})
print("=== MSFT Detailed Breakdown ===")
print(f"  Q:{s.get('quality_score')}  V:{s.get('value_score')}  G:{s.get('growth_score')}  S:{s.get('safety_score')}  Overall:{s.get('overall_score')}")
print(f"  PEG:{s.get('peg_ratio')}  RevCAGR3y:{s.get('revenue_cagr_3y_pct')}%  OEPS:{s.get('oeps_cagr_pct')}%")
print(f"  ROIC:{s.get('roic_pct')}%  GrossMargin:{s.get('gross_margin_pct')}%")
print(f"  Listing score: {app_enhanced._compounder_list_score(msft):.2f}")
print()

# What's keeping growth low?
print("  Growth sub-scores:")
print(f"    revenue_cagr_3y: {s.get('revenue_cagr_3y_pct')}%")
print(f"    oeps_cagr: {s.get('oeps_cagr_pct')}%")
print(f"    roic: {s.get('roic_pct')}%")
print()

# Companies just above MSFT
idx = next(i for i, c in enumerate(companies) if c.get("symbol") == "MSFT")
print(f"MSFT is at rank #{idx+1}")
print(f"\nCompanies ranked {max(1,idx-3)} to {idx+4}:")
for i in range(max(0, idx-3), min(len(companies), idx+4)):
    c = companies[i]
    cs = c.get("investment_scores", {})
    score = app_enhanced._compounder_list_score(c)
    print(f"  {i+1:>3} {c['symbol']:<7} Q:{cs.get('quality_score'):<4} V:{cs.get('value_score'):<5} G:{cs.get('growth_score'):<4} S:{cs.get('safety_score'):<4} ListScore:{score:.1f}  {c.get('name','')[:24]}")
