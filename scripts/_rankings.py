import sys, os
os.chdir(os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
sys.path.insert(0, ".")

import app_enhanced
app_enhanced.load_data()
companies = app_enhanced.companies
_compounder_list_score = app_enhanced._compounder_list_score

print(f"{'#':>3} {'Symbol':<7} {'Name':<28} {'Score':>6} {'Q':>4} {'V':>5} {'G':>5} {'S':>4}  MCap")
print("-" * 90)
for i, c in enumerate(companies[:10]):
    s = c.get("investment_scores", {})
    ci = c.get("company_info", {})
    mcap = ci.get("market_cap", 0)
    mcap_str = f"${mcap/1e12:.2f}T" if mcap >= 1e12 else f"${mcap/1e9:.1f}B"
    name = c.get("name", "")[:26]
    score = _compounder_list_score(c)
    print(f"{i+1:>3} {c['symbol']:<7} {name:<28} {score:>6.1f} {s.get('quality_score',0):>4} {s.get('value_score',0):>5} {s.get('growth_score',0):>5} {s.get('safety_score',0):>4}  {mcap_str}")

print("\n--- Key US Companies ---")
targets = ["MSFT", "GOOGL", "AMZN", "META", "NVDA", "AAPL", "NFLX", "V", "MA", "COST", "JPM", "TSLA"]
for i, c in enumerate(companies):
    if c.get("symbol") in targets:
        s = c.get("investment_scores", {})
        ci = c.get("company_info", {})
        mcap = ci.get("market_cap", 0)
        mcap_str = f"${mcap/1e12:.2f}T" if mcap >= 1e12 else f"${mcap/1e9:.1f}B"
        score = _compounder_list_score(c)
        print(f"{i+1:>4} {c['symbol']:<7} {c.get('name','')[:24]:<26} {score:>6.1f}  Q:{s.get('quality_score',0)}  V:{s.get('value_score',0)}  G:{s.get('growth_score',0)}  S:{s.get('safety_score',0)}  {mcap_str}")
