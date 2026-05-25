import json, pathlib

f = pathlib.Path('outputs/fundamentals_cache/META.US.json')
d = json.loads(f.read_text())

# Check raw dilutedEPS from income statement for problem quarters
q_inc = d.get('Financials', {}).get('Income_Statement', {}).get('quarterly', {})
earnings_hist = d.get('Earnings', {}).get('History', {})

print("Raw quarterly income statement (dilutedEPS) for 2025:")
for k in sorted(q_inc.keys()):
    if '2025' in k or '2026-03' in k:
        row = q_inc[k]
        dilutedEPS = row.get('dilutedEPS')
        ni = row.get('netIncome')
        sh = row.get('weightedAverageShsOutDil') or row.get('weightedAverageShsOut')
        print(f"  {k}: dilutedEPS={dilutedEPS}  ni={ni}  shares={sh}")

print("\nEarnings.History epsActual for 2025:")
for k in sorted(earnings_hist.keys()):
    if '2025' in k or '2026-03' in k:
        row = earnings_hist[k]
        print(f"  {k}: epsActual={row.get('epsActual')}  epsEstimate={row.get('epsEstimate')}")

# Now check price history around Sep 2025
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:3000/api/company/META.US/history', timeout=30) as r:
    api_data = json.loads(r.read())

qh = api_data.get('history', [])
print("\nAPI quarterly history (2025):")
for h in qh:
    if '2025' in h.get('period_end', '') or '2026-03' in h.get('period_end', ''):
        print(f"  {h['period_end']}: eps={h.get('eps')}  pe={h.get('pe_ratio')}  ye_price={h.get('ye_price')}")
