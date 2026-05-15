#!/usr/bin/env python3
"""Deep smoke of app_enhanced: all main routes via Flask test_client (no port required)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

os.chdir(PROJECT_ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app_enhanced as ae  # noqa: E402


def main() -> int:
    ae.load_data()
    client = ae.app.test_client()
    failures: list[str] = []

    def ok(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            failures.append(f"{name}: {detail}")

    def get(path: str) -> tuple[int, bytes]:
        r = client.get(path)
        return r.status_code, r.data

    def post_json(path: str, body: dict) -> tuple[int, dict | str]:
        r = client.post(path, json=body, content_type="application/json")
        if r.is_json:
            return r.status_code, r.get_json()
        return r.status_code, r.get_data(as_text=True)

    for path, needles in [
        ("/", ("Equity", "Universe scan", "SNAPSHOT")),
        ("/sectors", ("Sector",)),
    ]:
        code, body = get(path)
        text = body.decode("utf-8", errors="replace")
        ok(f"GET {path} 200", code == 200, str(code))
        for needle in needles:
            ok(f"GET {path} has {needle!r}", needle in text)

    code, body = get("/api/summary")
    ok("summary 200", code == 200)
    sym = "AAPL"
    if code == 200:
        sj = json.loads(body)
        ok("summary.total_companies", sj.get("total_companies", 0) > 0)
        ok("summary.data_universe_file", bool(sj.get("data_universe_file")))
        sym = sj.get("top_overall", {}).get("symbol") or "AAPL"

    code, body = get("/api/companies?limit=5&offset=0")
    ok("companies 200", code == 200)
    if code == 200:
        cj = json.loads(body)
        ok("companies.companies", isinstance(cj.get("companies"), list))

    code, body = get("/api/companies?sector=Technology&limit=5&offset=0")
    ok("companies sector filter 200", code == 200)
    if code == 200:
        ts = json.loads(body)
        ok("companies sector json", isinstance(ts.get("companies"), list) and "total" in ts)

    code, body = get("/api/companies?search=AAPL&limit=5&offset=0")
    ok("companies search 200", code == 200)
    if code == 200:
        sj = json.loads(body)
        ok("companies search json", isinstance(sj.get("companies"), list))

    code, body = get("/api/top/5")
    ok("top5 200", code == 200)

    code, body = get("/api/sectors")
    ok("sectors api 200", code == 200)
    if code == 200:
        se = json.loads(body)
        ok("sectors non-empty", isinstance(se, list) and len(se) > 0)

    qs = quote(sym, safe="")
    code, body = get(f"/api/company/{qs}")
    ok(f"api company {sym}", code == 200)
    if code == 200:
        co = json.loads(body)
        ok("company.symbol", co.get("symbol") == sym)

    code, body = get(f"/api/company/{qs}/history")
    ok(f"history {sym}", code == 200)
    if code == 200:
        hj = json.loads(body)
        ok("history.shape", "history" in hj and "partial" in hj)

    code, body = get(f"/company/{qs}")
    ok(f"HTML company {sym}", code == 200)
    if code == 200:
        ht = body.decode("utf-8", errors="replace")
        ok("company Ask AI", "Ask AI" in ht)

    code, body = get("/api/analysis/progress")
    ok("progress 200", code == 200)

    arun_code, arun_body = post_json(
        "/api/analysis/run", {"symbols_file": "scaled/../../../outside"}
    )
    ok("analysis run rejects traversal 400", arun_code == 400)

    ccode, cbody = post_json(f"/api/company/{qs}/chat", {"message": "ping"})
    ok("chat status", ccode in (200, 502, 503), str(cbody)[:200])

    sr = client.post(
        f"/api/company/{qs}/chat/stream",
        json={"message": "ping"},
        content_type="application/json",
    )
    ok("chat stream status", sr.status_code in (200, 503), str(sr.status_code))

    ic, _ = get("/api/company/%20/history")
    ok("invalid history 400", ic == 400)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" ", f)
        return 1
    print(f"All route checks passed (sample symbol {sym}, n={len(ae.companies)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
