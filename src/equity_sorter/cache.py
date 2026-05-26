"""SQLite-backed fundamentals cache.

Single file replaces 5,000+ individual JSON files.
Provides instant key-value lookups and bulk iteration.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Iterator


_DEFAULT_DB = Path(__file__).resolve().parents[2] / "outputs" / "fundamentals.db"


class FundamentalsCache:
    """Thread-safe SQLite cache for EODHD fundamentals JSON."""

    def __init__(self, db_path: Path | str = _DEFAULT_DB, ttl_hours: float = 24.0):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_hours * 3600
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64MB page cache
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                symbol TEXT PRIMARY KEY,
                data BLOB NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.commit()

    def get(self, symbol: str, ignore_ttl: bool = False) -> dict | None:
        """Get cached fundamentals. Returns None if missing or stale."""
        row = self._conn.execute(
            "SELECT data, updated_at FROM fundamentals WHERE symbol = ?",
            (symbol.upper(),)
        ).fetchone()
        if row is None:
            return None
        if not ignore_ttl and (time.time() - row[1]) > self.ttl_seconds:
            return None
        try:
            return json.loads(zlib.decompress(row[0]))
        except Exception:
            return None

    def put(self, symbol: str, data: dict) -> None:
        """Store fundamentals (compressed)."""
        blob = zlib.compress(
            json.dumps(data, separators=(",", ":")).encode("utf-8"), level=1
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO fundamentals (symbol, data, updated_at) VALUES (?, ?, ?)",
            (symbol.upper(), blob, time.time())
        )
        self._conn.commit()

    def put_many(self, items: list[tuple[str, dict]]) -> None:
        """Bulk insert/update (much faster than individual puts)."""
        now = time.time()
        rows = []
        for sym, data in items:
            blob = zlib.compress(
                json.dumps(data, separators=(",", ":")).encode("utf-8"), level=1
            )
            rows.append((sym.upper(), blob, now))
        self._conn.executemany(
            "INSERT OR REPLACE INTO fundamentals (symbol, data, updated_at) VALUES (?, ?, ?)",
            rows
        )
        self._conn.commit()

    def get_all(self, ignore_ttl: bool = True) -> Iterator[tuple[str, dict]]:
        """Iterate all cached entries. Yields (symbol, data) pairs."""
        cursor = self._conn.execute("SELECT symbol, data, updated_at FROM fundamentals")
        now = time.time()
        for sym, blob, updated_at in cursor:
            if not ignore_ttl and (now - updated_at) > self.ttl_seconds:
                continue
            try:
                yield sym, json.loads(zlib.decompress(blob))
            except Exception:
                continue

    def get_all_raw(self) -> list[tuple[str, bytes]]:
        """Return all (symbol, compressed_blob) pairs for parallel decompression."""
        return self._conn.execute("SELECT symbol, data FROM fundamentals").fetchall()

    def symbols(self) -> list[str]:
        """List all cached symbols."""
        rows = self._conn.execute("SELECT symbol FROM fundamentals").fetchall()
        return [r[0] for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()
        return row[0] if row else 0

    def stale_symbols(self) -> list[str]:
        """Return symbols whose cache is older than TTL."""
        cutoff = time.time() - self.ttl_seconds
        rows = self._conn.execute(
            "SELECT symbol FROM fundamentals WHERE updated_at < ?", (cutoff,)
        ).fetchall()
        return [r[0] for r in rows]

    def missing_symbols(self, wanted: list[str]) -> list[str]:
        """Return symbols from `wanted` that are not in cache at all."""
        if not wanted:
            return []
        wanted_u = [s.upper() for s in wanted]
        have: set[str] = set()
        chunk = 400
        for i in range(0, len(wanted_u), chunk):
            part = wanted_u[i : i + chunk]
            ph = ",".join("?" * len(part))
            rows = self._conn.execute(
                f"SELECT symbol FROM fundamentals WHERE symbol IN ({ph})", part
            ).fetchall()
            have.update(r[0] for r in rows)
        return [s for s in wanted_u if s not in have]

    def close(self):
        self._conn.close()


class PriceStore:
    """Persistent price history: L1 memory -> L2 SQLite -> L3 EODHD API.

    First load fetches full history from EODHD and stores to SQLite.
    Subsequent loads read from SQLite (instant) and only fetch new days.
    """

    def __init__(self, db_path: Path | str = _DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                symbol TEXT PRIMARY KEY,
                data BLOB NOT NULL,
                last_date TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.commit()
        self._mem: dict[str, list] = {}

    def _decompress(self, blob: bytes) -> list:
        return json.loads(zlib.decompress(blob))

    def _compress(self, prices: list) -> bytes:
        return zlib.compress(
            json.dumps(prices, separators=(",", ":")).encode("utf-8"), level=1
        )

    def get(self, symbol: str) -> list:
        """Get full price history for symbol. Returns from memory, then SQLite."""
        sym = symbol.upper()
        if sym in self._mem:
            return self._mem[sym]
        with self._lock:
            row = self._conn.execute(
                "SELECT data, last_date FROM price_history WHERE symbol = ?", (sym,)
            ).fetchone()
        if row is not None:
            try:
                prices = self._decompress(row[0])
                self._mem[sym] = prices
                return prices
            except Exception:
                pass
        return []

    def get_last_date(self, symbol: str) -> str | None:
        """Get the last stored date for a symbol."""
        with self._lock:
            row = self._conn.execute(
                "SELECT last_date FROM price_history WHERE symbol = ?",
                (symbol.upper(),)
            ).fetchone()
        return row[0] if row else None

    def put(self, symbol: str, prices: list) -> None:
        """Store full price history to SQLite + memory."""
        sym = symbol.upper()
        if not prices:
            return
        self._mem[sym] = prices
        last_date = prices[-1]["date"] if prices else ""
        blob = self._compress(prices)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO price_history (symbol, data, last_date, updated_at) VALUES (?, ?, ?, ?)",
                (sym, blob, last_date, time.time())
            )
            self._conn.commit()

    def append(self, symbol: str, new_prices: list) -> list:
        """Append new price points to existing data and persist."""
        sym = symbol.upper()
        existing = self.get(sym)
        if not new_prices:
            return existing
        last_existing = existing[-1]["date"] if existing else ""
        fresh = [p for p in new_prices if p["date"] > last_existing]
        if not fresh:
            return existing
        merged = existing + fresh
        self.put(sym, merged)
        return merged

    def close(self):
        self._conn.close()


def migrate_json_to_sqlite(
    json_dir: Path | str,
    db_path: Path | str = _DEFAULT_DB,
    batch_size: int = 200,
) -> int:
    """Import all JSON cache files into SQLite. Returns count imported."""
    json_dir = Path(json_dir)
    if not json_dir.is_dir():
        return 0

    cache = FundamentalsCache(db_path)
    files = [f for f in json_dir.iterdir() if f.suffix == ".json"]
    imported = 0
    batch: list[tuple[str, dict]] = []

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data and isinstance(data, dict):
                batch.append((f.stem, data))
                if len(batch) >= batch_size:
                    cache.put_many(batch)
                    imported += len(batch)
                    batch = []
        except Exception:
            continue

    if batch:
        cache.put_many(batch)
        imported += len(batch)

    cache.close()
    return imported
