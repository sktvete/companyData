import urllib.request, json

with urllib.request.urlopen('http://127.0.0.1:3000/api/company/META.US/history', timeout=30) as r:
    d = json.loads(r.read())

price = None
try:
    with urllib.request.urlopen('http://127.0.0.1:3000/api/company/META.US/quote', timeout=10) as r2:
        q = json.loads(r2.read())
        price = q.get('close') or q.get('price')
except Exception:
    pass
print(f"Current price: {price}")

# Annual history P/E
ah = d.get('annual_history', [])
print("\nAnnual history (last 5):")
for h in ah[-5:]:
    print(f"  {h['year']}: eps={h.get('eps')}  pe={h.get('pe_ratio')}  ni={h.get('net_income_usd',0)/1e9:.1f}B  rev={h.get('revenue_usd',0)/1e9:.1f}B")

# Annual estimates P/E
ests = d.get('estimates', [])
print(f"\nAnnual estimates ({len(ests)}):")
for e in ests:
    print(f"  fy={e.get('fiscal_year')} {e.get('year')}: eps={e.get('eps')}  rev={e.get('revenue_usd',0)/1e9:.1f}B  source={e.get('source','?')}")
    if price and e.get('eps'):
        fwd_pe = round(price / e['eps'], 1)
        print(f"    -> Forward P/E = {price} / {e['eps']} = {fwd_pe}")

# Quarterly history (last 8) — P/E
qh = d.get('history', [])
print(f"\nQuarterly history - last 8 (checking annualised P/E):")
for h in qh[-8:]:
    eps_q = h.get('eps') or 0
    pe = h.get('pe_ratio')
    print(f"  {h.get('period_end')}: eps={eps_q}  pe={pe}  (annualised eps={round(eps_q*4,2) if eps_q else 'N/A'})")

# Quarterly estimates
qe = d.get('quarterly_estimates', [])
print(f"\nQuarterly estimates ({len(qe)}):")
for e in qe:
    eps_q = e.get('eps') or 0
    source = e.get('source', '?')
    fwd_pe = round(price / (eps_q * 4), 1) if (price and eps_q) else 'N/A'
    print(f"  {e.get('period_end')}: eps={eps_q}  annualised_eps={round(eps_q*4,2) if eps_q else 'N/A'}  fwd_pe(ann)={fwd_pe}  source={source}")
