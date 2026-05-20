#!/usr/bin/env python3
"""Smoke-test dashboard + history for top names and growth leaders."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:3000"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode())


def check_history(sym: str) -> list[str]:
    issues: list[str] = []
    try:
        h = get(f"/api/company/{sym}/history")
    except Exception as e:
        return [f"{sym}: history request failed: {e}"]
    if h.get("error"):
        return [f"{sym}: {h['error']}"]
    ttm = h.get("ttm") or {}
    est = h.get("estimates") or []
    rev_ttm = ttm.get("revenue_b")
    if rev_ttm and rev_ttm > 2500:
        issues.append(f"{sym}: TTM revenue {rev_ttm}B looks like unconverted local currency")
    for i, e in enumerate(est):
        rev = e.get("revenue_b")
        if rev and rev_ttm and rev < rev_ttm * 0.35:
            issues.append(f"{sym}: FY est revenue {rev}B << TTM {rev_ttm}B (should be pruned)")
    return issues


def main() -> int:
    try:
        dash = get("/api/companies?limit=10&sort_by=listing_score&sort_order=desc")
    except urllib.error.URLError:
        print("Server not running on :3000"); return 1

    print("=== Top 10 (listing_score) ===")
    syms = []
    for c in dash["companies"]:
        syms.append(c["symbol"])
        print(
            f"  {c['symbol']:8s} list={c.get('listing_score', 0):5.2f} "
            f"g={c.get('growth_score')} rev1y={c.get('rev_growth_1y_pct')}% "
            f"rev5y={c.get('rev_growth_5y_pct')}%"
        )

    growth = get("/api/companies?limit=5&sort_by=growth_score&sort_order=desc")
    print("\n=== Top 5 (growth_score) ===")
    for c in growth["companies"]:
        print(f"  {c['symbol']:8s} g={c.get('growth_score')} list={c.get('listing_score', 0):.2f}")

    extra = ["AAPL", "GFI", "NOVO-B", "EQNR"]
    all_syms = syms + extra
    issues: list[str] = []
    for sym in all_syms:
        issues.extend(check_history(sym))

    print(f"\nTotal companies: {dash['total']}")
    if issues:
        print(f"\n{len(issues)} issue(s):")
        for i in issues:
            print(" ", i)
        return 1
    print("\nAll history checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
