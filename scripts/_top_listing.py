import json
import urllib.request

url = "http://localhost:3000/api/companies?sort_by=listing_score&sort_order=desc&limit=15"
with urllib.request.urlopen(url, timeout=30) as r:
    d = json.load(r)
for i, c in enumerate(d["companies"], 1):
    s = c.get("investment_scores") or {}
    print(
        f"{i:2} {c['symbol']:6} list={c.get('listing_score', 0):5.2f} "
        f"raw={c.get('overall_score', 0):5.2f} G={c.get('growth_score', 0):4.1f} "
        f"rev3y={c.get('revenue_cagr_3y_pct', 0):5.1f}% "
        f"rev1y={c.get('rev_growth_1y_pct', 0):5.1f}% "
        f"oeps={c.get('oeps_cagr_pct', 0):5.1f}% "
        f"pe={c.get('pe_ratio', 0):5.1f} mcap={c.get('market_cap_fmt', '')}"
    )
