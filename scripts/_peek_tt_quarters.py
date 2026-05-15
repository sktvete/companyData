"""Print TT quarterly period keys from fundamentals cache."""
import json
import sqlite3
from pathlib import Path

db_path = Path(__file__).resolve().parents[1] / "outputs" / "fundamentals.db"
if not db_path.is_file():
    print("no fundamentals.db")
    raise SystemExit(0)

con = sqlite3.connect(db_path)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("tables:", tables)

row = None
for tbl in tables:
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({tbl})")]
    if "symbol" in cols:
        try:
            row = con.execute(
                f"SELECT * FROM {tbl} WHERE symbol='TT' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row:
                print("hit table", tbl, "cols", cols)
                data_col = None
                for i, c in enumerate(cols):
                    if c in ("payload", "data", "json", "fundamentals"):
                        data_col = i
                if data_col is None:
                    # try blob/text columns
                    for i, c in enumerate(cols):
                        if row[i] and isinstance(row[i], (str, bytes)):
                            try:
                                json.loads(row[i] if isinstance(row[i], str) else row[i].decode())
                                data_col = i
                                break
                            except Exception:
                                pass
                if data_col is not None:
                    raw = row[data_col]
                    fund = json.loads(raw if isinstance(raw, str) else raw.decode())
                    q = fund.get("Financials", {}).get("Income_Statement", {}).get("quarterly", {})
                    keys = sorted(q.keys(), reverse=True)[:4]
                    print("TTM quarters (income stmt keys, newest first):")
                    for k in keys:
                        print(" ", k)
                break
        except Exception as ex:
            print(tbl, ex)
con.close()
