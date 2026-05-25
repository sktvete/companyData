import urllib.request, json

with urllib.request.urlopen('http://127.0.0.1:3000/api/company/AAPL.US/history', timeout=30) as r:
    d = json.loads(r.read())

ah = d.get('annual_history', [])
print('AAPL Annual (last 5):')
for h in ah[-5:]:
    rev = h.get('revenue_usd', 0)
    ni  = h.get('net_income_usd', 0)
    eps = h.get('eps')
    print(f"  {h['year']}: rev={rev/1e9:.1f}B  ni={ni/1e9:.1f}B  eps={eps}  margin={ni/rev*100:.1f}%")

ttm = d.get('ttm')
if ttm:
    rev = ttm.get('revenue_usd', 0)
    ni  = ttm.get('net_income_usd', 0)
    print(f"TTM: rev={rev/1e9:.1f}B  ni={ni/1e9:.1f}B  margin={ni/rev*100:.1f}%")
