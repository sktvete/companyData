"""End-to-end smoke test for the research stream endpoint."""
import json
import sys
import requests

BASE = "http://localhost:3000"

# Create investor
r = requests.post(f"{BASE}/api/tracker/investors", json={"name": "Leopold Aschenbrenner", "bio": "Former OpenAI researcher"})
print("Create:", r.status_code)
if r.status_code not in (200, 201):
    print("FAIL:", r.text)
    sys.exit(1)
inv_id = r.json()["id"]
print("Investor ID:", inv_id)

# Stream research
r2 = requests.post(f"{BASE}/api/tracker/investors/{inv_id}/research-stream", stream=True, timeout=180)
print("Stream status:", r2.status_code)
if r2.status_code != 200:
    print("FAIL:", r2.text)
    requests.delete(f"{BASE}/api/tracker/investors/{inv_id}")
    sys.exit(1)

evt_type = "message"
for raw_line in r2.iter_lines(decode_unicode=True):
    if not raw_line:
        evt_type = "message"
        continue
    if raw_line.startswith("event:"):
        evt_type = raw_line[6:].strip()
    elif raw_line.startswith("data:"):
        data = raw_line[5:].strip()
        if not data or data.startswith(":"):
            continue
        try:
            payload = json.loads(data)
        except Exception:
            continue

        if evt_type == "status":
            print(f"  [status] {payload.get('text', '')}")
        elif evt_type == "tool":
            sym = payload.get("symbol", "")
            sym_str = f" [{sym}]" if sym else ""
            print(f"  [tool]   {payload.get('tool', '')}{sym_str}")
        elif evt_type == "txn_added":
            t = payload.get("txn", {})
            print(f"  [added]  {t.get('action','').upper()} {t.get('symbol','')} {t.get('date','')} notes={t.get('notes','')[:40]}")
        elif evt_type == "txn_removed":
            print(f"  [removed] {payload.get('txn_id', '')}")
        elif evt_type == "token":
            pass  # skip verbose token lines
        elif evt_type == "done":
            print(f"  [DONE] total_found={payload.get('total_found', 0)}")
            break
        elif evt_type == "error":
            print(f"  [ERROR] {payload.get('text', '')}")
            break

r2.close()

# Verify persistence
r3 = requests.get(f"{BASE}/api/tracker/investors")
investors = r3.json().get("investors", [])
inv = next((i for i in investors if i["id"] == inv_id), None)
txns = inv.get("transactions", []) if inv else []
print(f"\nPersisted transactions: {len(txns)}")
for t in txns[:10]:
    print(f"  {t.get('date','')}  {t.get('action','').upper():4}  {t.get('symbol',''):8}  {t.get('notes','')[:50]}")

# Cleanup
requests.delete(f"{BASE}/api/tracker/investors/{inv_id}")
print("\nCleaned up. Test PASSED." if r2.status_code == 200 else "\nTest FAILED.")
