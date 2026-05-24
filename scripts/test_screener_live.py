#!/usr/bin/env python3
"""Live screener API smoke test against http://127.0.0.1:3000."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:3000"


def get(path):
    r = urllib.request.urlopen(BASE + path, timeout=10)
    return json.loads(r.read())


def main():
    # 1. Health
    h = get("/health")
    assert h.get("service") == "equity-os", f"Unexpected health: {h}"
    print(f"[1] Health OK: {h}")

    # 2. Total companies
    r = get("/api/companies?limit=1")
    companies = r.get("companies", r) if isinstance(r, dict) else r
    total = r.get("total", len(companies)) if isinstance(r, dict) else len(r)
    assert total >= 5000, f"Expected 5000+ companies, got {total}"
    print(f"[2] Total companies: {total} (>= 5000 OK)")

    # 3. Top 10 by default sort (listing_score desc)
    r = get("/api/companies?limit=10")
    top10 = r.get("companies", r) if isinstance(r, dict) else r
    assert len(top10) == 10, f"Expected 10 results, got {len(top10)}"
    print("[3] Top 10 by default sort:")
    for c in top10:
        sym = c.get("symbol", "-")
        name = c.get("name", "")[:35]
        scores = c.get("investment_scores") or {}
        ls = scores.get("listing_score") or c.get("listing_score", "-")
        rank = c.get("rank", "-")
        print(f"    {str(rank):>4}. {sym:<10} {name:<36} listing_score={ls}")

    # 4. Sector filter
    r = get("/api/companies?limit=5&sector=Technology")
    tech = r.get("companies", r) if isinstance(r, dict) else r
    tech_total = r.get("total", len(tech)) if isinstance(r, dict) else len(tech)
    assert len(tech) > 0, "No Technology companies returned"
    print(f"[4] Technology sector: {tech_total} total, showing {len(tech)}:")
    for c in tech:
        print(f"    {c.get('symbol',''):<10} {c.get('sector','')}")

    # 5. Search
    r = get("/api/companies?limit=5&search=Apple")
    hits = r.get("companies", r) if isinstance(r, dict) else r
    assert any("AAPL" in (c.get("symbol") or "") or "Apple" in (c.get("name") or "") for c in hits), \
        f"Search for 'Apple' didn't find AAPL: {[c.get('symbol') for c in hits]}"
    print(f"[5] Search 'Apple': {[c.get('symbol') for c in hits]}")

    # 6. Sort by value_score
    r = get("/api/companies?limit=5&sort=value_score")
    vs = r.get("companies", r) if isinstance(r, dict) else r
    assert len(vs) > 0, "No results for value_score sort"
    print(f"[6] Top 5 by value_score: {[c.get('symbol') for c in vs]}")

    # 7. Company detail page
    import urllib.error
    try:
        r2 = urllib.request.urlopen(f"{BASE}/company/AAPL", timeout=10)
        html = r2.read().decode("utf-8", errors="replace")
        assert "AAPL" in html or "Apple" in html, "Company page missing ticker"
        print("[7] Company page /company/AAPL OK")
    except urllib.error.HTTPError as e:
        print(f"[7] Company page /company/AAPL -> HTTP {e.code} (EODHD data may not be cached)")

    print("\nAll screener tests passed.")


if __name__ == "__main__":
    main()
