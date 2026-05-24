import urllib.request, json

url = "http://localhost:3000/api/company/META.US/history"
with urllib.request.urlopen(url, timeout=60) as r:
    data = json.loads(r.read())

print("Keys:", list(data.keys()))
q = data.get("quarterly", [])
ann = data.get("annual", data.get("annual_history", []))
hist = data.get("history", [])
print(f"quarterly: {len(q)}, annual_history: {len(ann)}, history: {len(hist)}")
if hist:
    print("Sample history[-1]:", json.dumps(hist[-1], indent=2)[:500])
if q:
    for row in q[-4:]:
        pe = row.get("period_end","")[:10]
        print(f"  {pe}: eps={row.get('eps')}, rev={row.get('revenue_usd',0)/1e9:.1f}B")
