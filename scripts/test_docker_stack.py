#!/usr/bin/env python3
"""Smoke test against running Docker stack (localhost:3000 + :8000)."""
from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:3000"
ANALYZER = "http://127.0.0.1:8000"
TICKER = "DOCKER.TEST"


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=15) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read()


def _post(url: str, body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body or {}).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read()


def main() -> int:
    print("[1] equity-os /health")
    st, body = _get(f"{BASE}/health")
    assert st == 200, body
    health = json.loads(body)
    assert health["status"] == "ok"
    assert health.get("moonstocks_storage") == "postgres", health
    print(f"    storage={health.get('moonstocks_storage')}")

    print("[2] analyzer /health")
    st, body = _get(f"{ANALYZER}/health")
    assert st == 200, body
    assert json.loads(body).get("llm_provider") in ("openai", "anthropic")
    print(f"    {body.decode()}")

    print("[3] ingest + read")
    report = {"recommendation": "watchlist", "overall_score": 50, "confidence": "medium"}
    st, _ = _post(f"{BASE}/api/analysis/{TICKER}", {"jsonReport": json.dumps(report)})
    assert st == 200, st
    st, body = _get(f"{BASE}/api/moonstocks/{TICKER}")
    assert st == 200, body
    assert json.loads(body)["report"]["recommendation"] == "watchlist"

    print("[4] company page")
    st, body = _get(f"{BASE}/company/DECK")
    assert st == 200
    html = body.decode("utf-8", errors="replace")
    assert "msTriggerBtn" in html

    print("[5] trigger (analyzer accepts)")
    st, body = _post(f"{BASE}/api/moonstocks/DECK.US/trigger")
    assert st in (200, 202), (st, body[:200])

    print("\nAll Docker stack checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
