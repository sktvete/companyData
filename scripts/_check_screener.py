"""Quick check of live screener ranks via API."""
import json
import urllib.request

base = "http://localhost:3000/api/companies"
top = json.load(urllib.request.urlopen(f"{base}?limit=15&sort_by=listing_score&sort_order=desc"))
rows = top.get("companies", [])
print(f"total universe: {top.get('total', '?')}")
print("\nTop 15 by screener rank:")
for r in rows:
    print(
        f"  #{r.get('rank', '?'):>3} {r['symbol']:<6} "
        f"screener={r.get('listing_score', 0):.2f}  "
        f"rev3y={r.get('revenue_cagr_3y_pct', 0):.1f}%  "
        f"oeps={r.get('oeps_cagr_pct', 0):.1f}%"
    )

tt = json.load(urllib.request.urlopen(f"{base}?search=TT&limit=5"))
for r in tt.get("companies", []):
    if r["symbol"] == "TT":
        print(
            f"\nTT: rank=#{r.get('rank')} screener={r.get('listing_score'):.2f} "
            f"overall={r.get('overall_score')} rev3y={r.get('revenue_cagr_3y_pct')}% "
            f"oeps={r.get('oeps_cagr_pct')}%"
        )
        break
