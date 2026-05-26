#!/usr/bin/env python3
"""E2E smoke tests for tracker research tools + HTTP API."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

BASE = os.environ.get("TRACKER_E2E_BASE", "http://localhost:3000")


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    raise SystemExit(1)


def test_tool_layer() -> None:
    print("\n=== Tool layer ===")
    from web.tracker_research_agent import (
        _edgar_entity_filings,
        _edgar_fulltext_search,
        _fetch_institutional_holdings,
        _fetch_ownership_stakes,
        _json_dumps,
        _known_filing_entity,
    )

    # JSON serialization (regression for httpx.URL bug)
    payload = _edgar_entity_filings("DJT", form_type="SC 13D/A", limit=1)
    json.loads(_json_dumps(payload))
    ok("find_edgar_entity JSON serializable")

    # EDGAR fulltext returns index URLs
    hits = _edgar_fulltext_search('"Donald J. Trump"', form_types="SC 13D,SC 13D/A", max_hits=3)
    if not hits or not hits[0].get("index_url"):
        fail("EDGAR fulltext missing index_url")
    ok(f"EDGAR fulltext: {len(hits)} hits with URLs")

    # Ownership stakes for controlling shareholder
    own = _fetch_ownership_stakes("Donald J. Trump", ticker="DJT", max_filings=3)
    if own["found"] < 1:
        fail(f"ownership stakes expected >=1, got {own['found']}")
    sym = own["transactions"][0].get("symbol")
    if sym != "DJT":
        fail(f"ownership ticker expected DJT, got {sym}")
    ok(f"ownership stakes: {own['found']} snapshot(s) for DJT")

    # 13F for AI-boom fund managers
    fund_cases = [
        ("Leopold Aschenbrenner", "Situational Awareness LP", {"NVDA", "SMH", "BE", "CRWV", "AMD", "AVGO"}),
        ("Cathie Wood", "ARK Investment Management LLC", {"TSLA", "ROKU", "XYZ", "COIN", "PLTR"}),
        ("Brad Gerstner", "Altimeter Capital Management, LP", {"NVDA", "TSM", "CRWV", "ARM", "AVGO"}),
        ("Philippe Laffont", "Coatue Management LLC", {"NVDA", "AVGO", "ASML", "MSFT", "META"}),
    ]
    for person, entity, expected_any in fund_cases:
        mapped = _known_filing_entity(person)
        if mapped != entity:
            fail(f"known entity for {person}: expected {entity}, got {mapped}")
        t0 = time.time()
        result = _fetch_institutional_holdings(entity, quarters=1)
        elapsed = time.time() - t0
        syms = {p.get("symbol") for p in result.get("positions", []) if p.get("symbol")}
        if len(syms) < 3:
            fail(f"{person}: only {len(syms)} resolved tickers from 13F")
        if not (syms & expected_any):
            fail(f"{person}: none of {expected_any} in {sorted(syms)[:10]}")
        ok(f"{person}: {len(syms)} tickers in {elapsed:.1f}s (e.g. {sorted(syms & expected_any)[:4]})")


def _parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip() or block.strip().startswith(":"):
            continue
        evt = "message"
        data = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                evt = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if data:
            try:
                events.append((evt, json.loads(data)))
            except json.JSONDecodeError:
                events.append((evt, {"text": data}))
    return events


def test_http_api() -> None:
    print("\n=== HTTP API ===")
    try:
        r = httpx.get(f"{BASE}/api/tracker/investors", timeout=15)
    except httpx.ConnectError:
        print("  SKIP HTTP tests — server not running at", BASE)
        return
    if r.status_code != 200:
        fail(f"GET investors: {r.status_code}")
    investors = r.json().get("investors", [])
    names = {i["name"] for i in investors}
    for required in ("Leopold Aschenbrenner", "Cathie Wood", "Brad Gerstner", "Philippe Laffont"):
        if required not in names:
            fail(f"missing investor profile: {required}")
    ok(f"{len(investors)} investors including AI profiles")

    # Tracker pages render
    for slug in ("LeopoldAschenbrenner", "CathieWood", "BradGerstner", "DonaldTrump"):
        pr = httpx.get(f"{BASE}/tracker/{slug}", timeout=15)
        if pr.status_code != 200:
            fail(f"GET /tracker/{slug}: {pr.status_code}")
    ok("tracker pages render for key slugs")

    # Research watch returns 204 when idle
    inv = next(i for i in investors if i["name"] == "Cathie Wood")
    wr = httpx.get(f"{BASE}/api/tracker/investors/{inv['id']}/research-watch", timeout=10)
    if wr.status_code != 204:
        fail(f"research-watch idle expected 204, got {wr.status_code}")
    ok("research-watch idle returns 204")


def test_live_research(name: str, min_txns: int = 1, timeout_s: int = 180) -> None:
    print(f"\n=== Live research: {name} (timeout {timeout_s}s) ===")
    try:
        inv_resp = httpx.get(f"{BASE}/api/tracker/investors", timeout=15)
    except httpx.ConnectError:
        print("  SKIP — server not running")
        return
    investor = next((i for i in inv_resp.json().get("investors", []) if i["name"] == name), None)
    if not investor:
        fail(f"investor not found: {name}")

    inv_id = investor["id"]
    before = len(investor.get("transactions") or [])

    with httpx.stream(
        "POST",
        f"{BASE}/api/tracker/investors/{inv_id}/research-stream",
        timeout=timeout_s,
    ) as resp:
        if resp.status_code == 409:
            print("  research already running — attaching watch")
            with httpx.stream(
                "GET",
                f"{BASE}/api/tracker/investors/{inv_id}/research-watch",
                timeout=timeout_s,
            ) as watch:
                body = watch.read().decode("utf-8", errors="replace")
        elif resp.status_code != 200:
            fail(f"research-stream: {resp.status_code} {resp.read().decode()[:200]}")
        else:
            body = resp.read().decode("utf-8", errors="replace")

    events = _parse_sse_events(body)
    types = [e[0] for e in events]
    if "error" in types:
        err = next(v for k, v in events if k == "error")
        fail(f"research error: {err.get('text', err)}")
    if "done" not in types:
        fail("research stream ended without done event")

    done = next(v for k, v in events if k == "done")
    added = done.get("total_found", 0)
    tool_errors = [v.get("summary", "") for k, v in events if k == "tool_result" and "tool error" in str(v)]
    if tool_errors:
        fail(f"tool errors during research: {tool_errors[:3]}")

    fresh = httpx.get(f"{BASE}/api/tracker/investors", timeout=15).json()
    after_inv = next(i for i in fresh["investors"] if i["id"] == inv_id)
    after = len(after_inv.get("transactions") or [])
    new_count = after - before

    if added < min_txns and new_count < min_txns:
        fail(f"expected >= {min_txns} new txns, agent reported {added}, db delta {new_count}")
    ok(f"research complete — +{max(added, new_count)} transactions, {len(events)} SSE events")


def main() -> None:
    print("Tracker research E2E")
    test_tool_layer()
    test_http_api()

    if "--live" in sys.argv:
        test_live_research("Cathie Wood", min_txns=3, timeout_s=240)
        test_live_research("Brad Gerstner", min_txns=2, timeout_s=240)
        test_live_research("Philippe Laffont", min_txns=2, timeout_s=240)
    else:
        print("\n(Pass --live to run LLM research-stream tests — requires OPENAI_API_KEY + server)")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
