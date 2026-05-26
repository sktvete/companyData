"""
Seed Leopold Aschenbrenner's tracker with his real 13F holdings.
Data source: Situational Awareness LP 13F-HR filed 2026-05-18 (Q1 2026, period ending 2026-03-31)
SEC EDGAR Accession: 0002045724-26-000008
"""
import requests
import json
import sys

BASE = "http://localhost:3000"

# ── Q1 2026 13F positions ─────────────────────────────────────────────────────
# Using 2026-03-31 as the "as of" date (period of report)
# Long equity = buy, Put options = sell (bearish hedge), Call options = buy (bullish leverage)

Q1_2026 = [
    # LONG EQUITY (bullish)
    ("BE",   "buy",  "2026-03-31", 6485408,  135.50, "13F Q1 2026 — Bloom Energy; on-site fuel cells for AI data center power"),
    ("SNDK", "buy",  "2026-03-31", 1140119,  635.33, "13F Q1 2026 — SanDisk; NAND storage for AI workloads"),
    ("CRWV", "buy",  "2026-03-31", 7177919,   77.47, "13F Q1 2026 — CoreWeave; GPU cloud platform"),
    ("IREN", "buy",  "2026-03-31", 11698835,  34.28, "13F Q1 2026 — IREN Ltd; Bitcoin miner pivoting to AI hosting"),
    ("CORZ", "buy",  "2026-03-31", 26008473,  14.96, "13F Q1 2026 — Core Scientific; BTC miner / AI hosting (trimmed)"),
    ("APLD", "buy",  "2026-03-31", 13478438,  23.74, "13F Q1 2026 — Applied Digital; AI infrastructure & HPC data centers"),
    ("RIOT", "buy",  "2026-03-31", 11502137,  12.36, "13F Q1 2026 — Riot Platforms; Bitcoin miner with stranded power assets"),
    ("CLSK", "buy",  "2026-03-31", 12276139,   8.51, "13F Q1 2026 — CleanSpark; BTC miner pivoting to AI hosting (+648%)"),
    ("SEI",  "buy",  "2026-03-31", 1105551,   56.50, "13F Q1 2026 — Solaris Energy Infrastructure; mobile turbine/on-site power for data centers"),
    ("TE",   "buy",  "2026-03-31", 10000000,   4.39, "13F Q1 2026 — T1 Energy; solar/battery manufacturer NEW"),
    ("BITF", "buy",  "2026-03-31", 19875840,   1.95, "13F Q1 2026 — Bitfarms/Keel Infrastructure; rebranded April 2026 (+188%)"),
    ("BTDR", "buy",  "2026-03-31", 3439450,    8.65, "13F Q1 2026 — Bitdeer Technologies; mining and AI compute hosting"),
    ("PSIX", "buy",  "2026-03-31", 432300,    60.89, "13F Q1 2026 — Power Solutions International; industrial/on-site power"),
    ("WYFI", "buy",  "2026-03-31", 1757600,   11.91, "13F Q1 2026 — WhiteFiber; IT services"),
    ("BW",   "buy",  "2026-03-31", 1353900,   14.69, "13F Q1 2026 — Babcock & Wilcox; power equipment/heating"),
    ("SHAZ", "buy",  "2026-03-31", 796108,    22.74, "13F Q1 2026 — SharonAI Holdings; AI infrastructure services NEW"),
    ("PUMP", "buy",  "2026-03-31", 910300,    14.41, "13F Q1 2026 — ProPetro Holding; oil & gas field services"),
    ("HIVE", "buy",  "2026-03-31", 3391547,    1.90, "13F Q1 2026 — Hive Digital Technologies; crypto mining → AI/HPC hosting NEW"),

    # LONG CALL OPTIONS (bullish leverage)
    ("MU",   "buy",  "2026-03-31", 1250000,  None,   "13F Q1 2026 — Micron calls $422M notional; two-way vol bet (also holds puts)"),
    ("SNDK", "buy",  "2026-03-31", 611900,   None,   "13F Q1 2026 — SanDisk calls $389M notional; additional leverage on top of $724M common"),
    ("TSM",  "buy",  "2026-03-31", 1050000,  None,   "13F Q1 2026 — Taiwan Semi calls $355M notional; two-way vol bet (also holds puts)"),
    ("CRWV", "buy",  "2026-03-31", 1814500,  None,   "13F Q1 2026 — CoreWeave calls $141M notional (reduced 83%; rotated to common)"),
    ("BE",   "buy",  "2026-03-31", 408500,   None,   "13F Q1 2026 — Bloom Energy calls $55M notional; bullish leverage on $878M common"),

    # PUT OPTIONS (bearish hedges — entered as 'sell' to indicate bearish positioning)
    ("SMH",  "sell", "2026-03-31", 5327900,  None,   "13F Q1 2026 — VanEck Semiconductor ETF PUTS $2.04B notional; portfolio-level semiconductor hedge NEW"),
    ("NVDA", "sell", "2026-03-31", 8992300,  None,   "13F Q1 2026 — Nvidia PUTS $1.57B notional; bearish on dominant AI chip name NEW"),
    ("ORCL", "sell", "2026-03-31", 7293000,  None,   "13F Q1 2026 — Oracle PUTS $1.07B notional; AI cloud premium overpriced NEW"),
    ("AVGO", "sell", "2026-03-31", 3251100,  None,   "13F Q1 2026 — Broadcom PUTS $1.01B notional; hedge on AI ASIC/networking NEW"),
    ("AMD",  "sell", "2026-03-31", 4764100,  None,   "13F Q1 2026 — AMD PUTS $969M notional; net negative on AMD despite small common NEW"),
    ("MU",   "sell", "2026-03-31", 1727700,  None,   "13F Q1 2026 — Micron PUTS $584M notional; volatility play (also holds calls)"),
    ("TSM",  "sell", "2026-03-31", 1583400,  None,   "13F Q1 2026 — Taiwan Semi PUTS $535M notional; volatility + geopolitics NEW"),
    ("ASML", "sell", "2026-03-31", 374100,   None,   "13F Q1 2026 — ASML PUTS $494M notional; sole EUV maker valuation hedge NEW"),
    ("INTC", "sell", "2026-03-31", 3605400,  None,   "13F Q1 2026 — Intel PUTS $159M notional; net negative after unwinding prior call options NEW"),
    ("GLW",  "sell", "2026-03-31", 154600,   None,   "13F Q1 2026 — Corning PUTS $21M notional; optical fiber chip-adjacent hedge NEW"),
    ("INFY", "sell", "2026-03-31", 500000,   None,   "13F Q1 2026 — Infosys PUTS $6.76M notional; bearish on Indian IT exposure to AI displacement"),
]

# Q4 2025 positions that were EXITED in Q1 2026 — mark as sells on exit date
Q1_2026_EXITS = [
    ("LITE", "sell", "2026-03-31", 1298400, None, "13F Q1 2026 EXIT — Lumentum Holdings; optical comms; full exit (was 8.68%)"),
    ("COHR", "sell", "2026-03-31", 480300,  None, "13F Q1 2026 EXIT — Coherent Corp; optical transceivers; full exit"),
    ("HUT",  "sell", "2026-03-31", 860200,  None, "13F Q1 2026 EXIT — Hut 8 Corp; crypto miner; full exit"),
    ("TSEM", "sell", "2026-03-31", 723004,  None, "13F Q1 2026 EXIT — Tower Semiconductor; specialty foundry; full exit"),
    ("CIFR", "sell", "2026-03-31", 10469093,None, "13F Q1 2026 EXIT — Cipher Mining; crypto miner; full exit"),
    ("EQT",  "sell", "2026-03-31", 2482225, None, "13F Q1 2026 EXIT — EQT Corporation; natural gas producer; full exit"),
    ("KRC",  "sell", "2026-03-31", 1327700, None, "13F Q1 2026 EXIT — Kilroy Realty; REIT; full exit"),
    ("LBRT", "sell", "2026-03-31", 567200,  None, "13F Q1 2026 EXIT — Liberty Energy; oilfield services; full exit"),
]

# Q4 2025 initial positions (from the $5.52B filing — founding positions, opened Sep–Dec 2024)
Q4_2024_FOUNDING = [
    # These are approximate; using Sep 2024 as launch date
    ("BE",   "buy",  "2024-09-01", None, None, "Initial position — Bloom Energy; fund launch Sept 2024 (grew to 15.87% of Q4 2025 book)"),
    ("CRWV", "buy",  "2024-09-01", None, None, "Initial position — CoreWeave; GPU cloud; calls position at fund launch"),
    ("INTC", "buy",  "2024-09-01", None, None, "Initial position — Intel calls $747M notional; contrarian CHIPS Act bet (fully exited Q1 2026)"),
    ("CORZ", "buy",  "2024-09-01", None, None, "Initial position — Core Scientific; BTC miner turned AI hosting"),
    ("LITE", "buy",  "2024-09-01", None, None, "Initial position — Lumentum Holdings; optical comms (exited Q1 2026)"),
    ("COHR", "buy",  "2024-10-01", None, None, "Initial position — Coherent Corp; optical transceivers (exited Q1 2026)"),
]

def ensure_investor(name: str, bio: str) -> str:
    """Find or create investor, return ID."""
    r = requests.get(f"{BASE}/api/tracker/investors")
    data = r.json()
    existing = next((i for i in data.get("investors", []) if i["name"] == name), None)
    if existing:
        print(f"Found existing investor: {existing['id']}")
        return existing["id"]
    r2 = requests.post(f"{BASE}/api/tracker/investors", json={"name": name, "bio": bio})
    inv = r2.json()
    print(f"Created investor: {inv['id']}")
    return inv["id"]

def add_txn(inv_id: str, symbol: str, action: str, date: str, shares, price, notes: str):
    body = {"symbol": symbol, "action": action, "date": date, "notes": notes}
    if shares is not None:
        body["shares"] = shares
    if price is not None:
        body["price"] = price
    r = requests.post(f"{BASE}/api/tracker/investors/{inv_id}/transactions",
                      json=body, headers={"Content-Type": "application/json"})
    if r.status_code in (200, 201):
        t = r.json()
        print(f"  + {action.upper():4} {symbol:6} {date}  {notes[:55]}")
        return True
    else:
        print(f"  ! FAIL {symbol}: {r.status_code} {r.text[:80]}")
        return False

def main():
    name = "Leopold Aschenbrenner"
    bio  = ("Founder & CIO of Situational Awareness LP ($13.7B). Former OpenAI Superalignment researcher. "
            "Author of 'Situational Awareness: The Decade Ahead' (2024). "
            "Thesis: AI capex bottleneck is electricity and physical infrastructure, not chips. "
            "Fund backed by Patrick & John Collison (Stripe), Nat Friedman, Daniel Gross. "
            "Co-managed with Carl Shulman (Director of Research).")

    inv_id = ensure_investor(name, bio)

    # Check what's already there
    r = requests.get(f"{BASE}/api/tracker/investors")
    data = r.json()
    inv = next((i for i in data["investors"] if i["id"] == inv_id), None)
    existing_txns = inv.get("transactions", []) if inv else []

    def already_exists(symbol, action, date):
        return any(t["symbol"] == symbol and t["action"] == action and t["date"] == date
                   for t in existing_txns)

    print(f"\n=== Seeding {name} ===")
    added = 0

    print("\n--- Founding positions (Q4 2024) ---")
    for sym, action, date, shares, price, notes in Q4_2024_FOUNDING:
        if not already_exists(sym, action, date):
            if add_txn(inv_id, sym, action, date, shares, price, notes):
                added += 1

    print("\n--- Q1 2026 13F Holdings (as of 2026-03-31) ---")
    for sym, action, date, shares, price, notes in Q1_2026:
        if not already_exists(sym, action, date):
            if add_txn(inv_id, sym, action, date, shares, price, notes):
                added += 1

    print("\n--- Q1 2026 Exits ---")
    for sym, action, date, shares, price, notes in Q1_2026_EXITS:
        if not already_exists(sym, action, date):
            if add_txn(inv_id, sym, action, date, shares, price, notes):
                added += 1

    print(f"\nDone. {added} transactions added.")
    print(f"View at: http://localhost:3000/tracker")

if __name__ == "__main__":
    main()
