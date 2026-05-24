import urllib.request, json

targets = {
    "META.US": {
        "2026-03-31": 7.31,
        "2025-12-31": 8.88,
        "2025-09-30": 7.25,
        "2025-06-30": 7.14,
    },
    "NVDA.US": {
        "2026-04-30": 1.87,
        "2026-01-31": 1.62,
        "2025-10-31": 1.30,
        "2025-07-31": 1.05,
    },
    "AAPL.US": {},
    "MSFT.US": {},
    "AMZN.US": {},
    "GOOGL.US": {},
    "TSLA.US": {},
    "CRWD.US": {},
    "AMD.US": {},
    "PLTR.US": {},
}

print("=== EPS Validation vs EODHD Earnings.History ===\n")
issues = []

for sym, expected_eps in targets.items():
    url = f"http://localhost:3000/api/company/{sym}/history"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"{sym}: ERROR {e}")
        continue

    rows = data.get("history", [])
    print(f"\n--- {sym} (last 6 quarters) ---")
    for row in rows[-6:]:
        pe = row.get("period_end", "")[:10]
        eps = row.get("eps")
        rev_b = (row.get("revenue_usd") or 0) / 1e9
        fcf_b = (row.get("fcf_usd") or 0) / 1e9
        cfo_b = (row.get("ocf_usd") or 0) / 1e9
        capex_b = (row.get("capex_usd") or 0) / 1e9

        if pe in expected_eps:
            exp = expected_eps[pe]
            ok = eps is not None and abs(eps - exp) < 0.02
            match = "OK" if ok else f"MISMATCH (expected {exp})"
            if not ok:
                issues.append(f"{sym} {pe}: got {eps}, expected {exp}")
        else:
            match = ""
        eps_str = f"{eps:.3f}" if eps is not None else "None"
        print(f"  {pe}: eps={eps_str:>6}, rev={rev_b:.1f}B, cfo={cfo_b:.1f}B, capex={capex_b:.1f}B, fcf={fcf_b:.1f}B  {match}")

print("\n\n=== ANNUAL EPS (last 5 years) ===")
for sym in ["META.US", "NVDA.US", "AAPL.US"]:
    url = f"http://localhost:3000/api/company/{sym}/history"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"{sym}: ERROR {e}")
        continue
    ann = data.get("annual_history", [])
    print(f"\n--- {sym} ---")
    for row in ann[-5:]:
        pe = row.get("period_end", "")[:10]
        eps = row.get("eps")
        rev_b = (row.get("revenue_usd") or 0) / 1e9
        print(f"  {pe}: eps={eps}, rev={rev_b:.1f}B")

if issues:
    print(f"\n\nFAILED {len(issues)} EPS checks:")
    for i in issues:
        print(f"  X {i}")
else:
    print("\n\nAll expected EPS checks PASSED!")
