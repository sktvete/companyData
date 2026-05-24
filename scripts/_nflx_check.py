import urllib.request, json

for sym in ["NFLX.US"]:
    url = f"http://localhost:3000/api/company/{sym}/history"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())

    ests = data.get("estimates", [])
    q_ests = data.get("quarterly_estimates", [])
    ttm = data.get("ttm") or {}
    
    print(f"=== {sym} ===")
    print(f"TTM: ocf={((ttm.get('ocf_usd') or 0)/1e9):.1f}B  capex={((ttm.get('capex_usd') or 0)/1e9):.1f}B  fcf={((ttm.get('fcf_usd') or 0)/1e9):.1f}B")
    print(f"\nAnnual estimates ({len(ests)}):")
    for e in ests:
        src = e.get("estimate_source", "analyst")
        rev   = (e.get("revenue_usd")     or 0) / 1e9
        ni    = (e.get("net_income_usd")  or 0) / 1e9
        ocf   = (e.get("ocf_usd")         or 0) / 1e9
        capex = (e.get("capex_usd")       or 0) / 1e9
        fcf   = (e.get("fcf_usd")         or 0) / 1e9
        print(f"  {e['year']:12s}  rev={rev:.1f}B  ni={ni:.1f}B  ocf={ocf:.1f}B  capex={capex:.1f}B  fcf={fcf:.1f}B  [{src}]")

    print(f"\nQuarterly estimates ({len(q_ests)}):")
    for e in q_ests[:8]:
        src   = e.get("estimate_source", "analyst")
        rev   = (e.get("revenue_usd")  or 0) / 1e9
        ocf   = (e.get("ocf_usd")      or 0) / 1e9
        capex = (e.get("capex_usd")    or 0) / 1e9
        fcf   = (e.get("fcf_usd")      or 0) / 1e9
        print(f"  {e['year']:12s}  rev={rev:.1f}B  ocf={ocf:.1f}B  capex={capex:.1f}B  fcf={fcf:.1f}B  [{src}]")

    # Show last 4 annual history for context
    ann = data.get("annual_history", [])
    print(f"\nLast 4 annual history:")
    for row in ann[-4:]:
        pe = row.get("period_end","")[:7]
        ocf   = (row.get("ocf_usd")    or 0)/1e9
        capex = (row.get("capex_usd")  or 0)/1e9
        fcf   = (row.get("fcf_usd")    or 0)/1e9
        print(f"  {pe}  ocf={ocf:.1f}B  capex={capex:.1f}B  fcf={fcf:.1f}B")
