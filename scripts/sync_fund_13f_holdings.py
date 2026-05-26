#!/usr/bin/env python3
"""Sync latest 13F holdings into tracker.json for known fund managers."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.tracker_research_agent import _fetch_institutional_holdings, _known_filing_entity

TRACKER_FILE = ROOT / "outputs" / "tracker.json"
MAX_POSITIONS = 15
_13F_NOTE_MARKERS = ("13F-HR", "13F-HR/A", "13F holdings")


def _load() -> dict:
    return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    tmp = TRACKER_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(TRACKER_FILE)


def _txn_key(t: dict) -> tuple:
    return (
        (t.get("symbol") or "").upper(),
        (t.get("action") or "buy").lower(),
        (t.get("date") or "")[:10],
    )


def _is_13f_txn(t: dict) -> bool:
    notes = (t.get("notes") or "").upper()
    return any(m.upper() in notes for m in _13F_NOTE_MARKERS)


def sync_investor(investor: dict, replace_13f: bool = False) -> int:
    entity = _known_filing_entity(investor["name"])
    if not entity:
        print(f"  skip {investor['name']}: no known 13F entity")
        return 0

    result = _fetch_institutional_holdings(entity, quarters=1)
    positions = [p for p in result.get("positions", []) if p.get("symbol")][:MAX_POSITIONS]
    if not positions:
        print(f"  skip {investor['name']}: no 13F positions ({result.get('message', '')})")
        return 0

    existing = investor.get("transactions") or []
    if replace_13f:
        existing = [t for t in existing if not _is_13f_txn(t)]
    seen = {_txn_key(t) for t in existing}
    seen_symbols = {(t.get("symbol") or "").upper() for t in existing if _is_13f_txn(t) or replace_13f}
    added = 0

    for p in positions:
        sym = p["symbol"].upper()
        date = (p.get("date") or "")[:10]
        key = (sym, p.get("action") or "buy", date)
        if key in seen:
            continue
        # One 13F row per symbol — skip if we already have this symbol from an earlier pass.
        if sym in seen_symbols:
            continue
        existing.append({
            "id": str(uuid.uuid4()),
            "symbol": sym,
            "action": p.get("action") or "buy",
            "date": date,
            "shares": p.get("shares"),
            "price": p.get("price"),
            "notes": (p.get("source") or f"13F-HR — {entity}")[:500],
            "position_type": p.get("position_type") or "long",
        })
        seen.add(key)
        seen_symbols.add(sym)
        added += 1

    investor["transactions"] = existing
    print(f"  {investor['name']}: +{added} positions (total {len(existing)})")
    return added


def main() -> None:
    # Replace stale/wrong 13F rows (duplicates, bad tickers from old LLM batch).
    names_replace_13f = {
        "Brad Gerstner",
        "Cathie Wood",
        "Leopold Aschenbrenner",
        "Philippe Laffont",
        "Warren Buffet",
    }
    data = _load()
    total = 0
    for inv in data.get("investors", []):
        if not _known_filing_entity(inv.get("name", "")):
            continue
        total += sync_investor(inv, replace_13f=inv["name"] in names_replace_13f)
    _save(data)
    print(f"Done. Added {total} transactions.")


if __name__ == "__main__":
    main()
