import urllib.request, json, sys

BASE = "http://127.0.0.1:3000"

def fetch(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())

d = fetch("/api/company/TSM.US/history")

# ── Annual history ────────────────────────────────────────────────
ah = d.get("annual_history", [])
print(f"Annual history rows: {len(ah)}")
for h in ah:
    rev  = h.get("revenue_usd") or h.get("revenue_b", 0) * 1e9
    ni   = h.get("net_income_usd") or h.get("net_income_b", 0) * 1e9
    eps  = h.get("eps")
    gm   = h.get("gross_margin_pct")
    nm   = h.get("net_margin_pct")
    cfo  = h.get("ocf_usd")
    fcf  = h.get("fcf_usd")
    print(f"  {h['year']}: rev={rev/1e9:.1f}B  ni={ni/1e9:.1f}B  eps={eps}  gm={gm}%  nm={nm}%  cfo={cfo}  fcf={fcf}")

# ── Estimates ─────────────────────────────────────────────────────
ests = d.get("estimates", [])
print(f"\nAnnual estimates: {len(ests)}")
for e in ests:
    print(f"  fy={e.get('fiscal_year')} year={e.get('year')}  rev={e.get('revenue_usd',0)/1e9:.1f}B  ni={e.get('net_income_usd',0)/1e9:.1f}B  eps={e.get('eps')}  source={e.get('source','?')}")

# ── TTM ───────────────────────────────────────────────────────────
ttm = d.get("ttm")
if ttm:
    print(f"\nTTM: rev={ttm.get('revenue_usd',0)/1e9:.1f}B  ni={ttm.get('net_income_usd',0)/1e9:.1f}B  cfo={ttm.get('ocf_usd')}  fcf={ttm.get('fcf_usd')}")

# ── Quarterly history (last 12) ───────────────────────────────────
qh = d.get("history", [])
print(f"\nQuarterly history rows: {len(qh)}")
for h in qh[-12:]:
    rev = h.get("revenue_usd") or 0
    ni  = h.get("net_income_usd") or 0
    eps = h.get("eps")
    print(f"  {h.get('period_end','?')}: rev={rev/1e9:.2f}B  ni={ni/1e9:.2f}B  eps={eps}")

# ── Quarterly estimates ───────────────────────────────────────────
qe = d.get("quarterly_estimates", [])
print(f"\nQuarterly estimates: {len(qe)}")
for e in qe:
    print(f"  {e.get('period_end','?')}: rev={e.get('revenue_usd',0)/1e9:.2f}B  ni={e.get('net_income_usd',0)/1e9:.2f}B  eps={e.get('eps')}  source={e.get('source','?')}")
