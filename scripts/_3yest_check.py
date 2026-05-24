import urllib.request, json

for sym in ["META.US", "NVDA.US", "TSLA.US", "CRWD.US"]:
    url = f"http://localhost:3000/api/company/{sym}/history"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())

    ests = data.get("estimates", [])
    q_ests = data.get("quarterly_estimates", [])

    print(f"\n=== {sym} ===")
    print(f"Annual estimates ({len(ests)}):")
    for e in ests:
        src = e.get("estimate_source", "analyst")
        rev = (e.get("revenue_usd") or 0) / 1e9
        ni  = (e.get("net_income_usd") or 0) / 1e9
        fcf = (e.get("fcf_usd") or 0) / 1e9
        print(f"  {e['year']:12s} rev={rev:.1f}B  ni={ni:.1f}B  fcf={fcf:.1f}B  [{src}]")
    print(f"Quarterly estimates ({len(q_ests)}):")
    for e in q_ests[:6]:
        src = e.get("estimate_source", "analyst")
        rev = (e.get("revenue_usd") or 0) / 1e9
        fcf = (e.get("fcf_usd") or 0) / 1e9
        print(f"  {e['year']:12s} rev={rev:.1f}B  fcf={fcf:.1f}B  [{src}]")
