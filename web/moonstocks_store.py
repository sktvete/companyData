"""Moonstocks AI analysis storage (PostgreSQL or SQLite)."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional until postgres URL set
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore


@dataclass(frozen=True)
class AnalysisRow:
    ticker_and_exchange_code: str
    json_report: str
    generated_time: int


def _database_url() -> str:
    return (
        os.environ.get("MOONSTOCKS_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()


def uses_postgres() -> bool:
    # MOONSTOCKS_DB_PATH enables SQLite — valid for local dev without Docker and for E2E tests.
    if (os.environ.get("MOONSTOCKS_DB_PATH") or "").strip():
        return False
    url = _database_url()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _sqlite_path(project_root: Path) -> Path:
    raw = (os.environ.get("MOONSTOCKS_DB_PATH") or "").strip()
    if raw:
        return Path(raw)
    return project_root / "outputs" / "moonstocks_analyses.db"


_store_ready = False


def ensure_store(project_root: Path) -> None:
    """Create schema once (lazy — avoids import-time Postgres when .env targets Docker)."""
    global _store_ready
    if _store_ready:
        return
    init_store(project_root)
    _store_ready = True


def init_store(project_root: Path) -> None:
    if uses_postgres():
        if psycopg is None:
            raise RuntimeError("psycopg is required when MOONSTOCKS_DATABASE_URL is set")
        with _pg_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    ticker_and_exchange_code TEXT PRIMARY KEY,
                    json_report TEXT NOT NULL,
                    generated_time BIGINT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_triggers (
                    ticker_and_exchange_code TEXT PRIMARY KEY,
                    triggered_at BIGINT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    email TEXT,
                    created_at BIGINT NOT NULL,
                    last_login_at BIGINT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    PRIMARY KEY (user_id, kind, item_key)
                )
            """)
            conn.commit()
        return

    db_path = _sqlite_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            ticker_and_exchange_code TEXT PRIMARY KEY,
            json_report TEXT NOT NULL,
            generated_time INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_triggers (
            ticker_and_exchange_code TEXT PRIMARY KEY,
            triggered_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT,
            email TEXT,
            created_at INTEGER NOT NULL,
            last_login_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            item_key TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, kind, item_key)
        )
    """)
    conn.commit()
    conn.close()
    global _store_ready
    _store_ready = True


def reset_store() -> None:
    """Test helper: allow re-init after env change."""
    global _store_ready
    _store_ready = False


@contextmanager
def _pg_conn():
    assert psycopg is not None
    with psycopg.connect(_database_url(), connect_timeout=5, row_factory=dict_row) as conn:
        yield conn


@contextmanager
def _sqlite_conn(project_root: Path):
    conn = sqlite3.connect(_sqlite_path(project_root))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_analysis(project_root: Path, ticker: str) -> AnalysisRow | None:
    ensure_store(project_root)
    key = ticker.upper()
    if uses_postgres():
        with _pg_conn() as conn:
            row = conn.execute(
                "SELECT ticker_and_exchange_code, json_report, generated_time "
                "FROM analyses WHERE ticker_and_exchange_code = %s",
                (key,),
            ).fetchone()
    else:
        with _sqlite_conn(project_root) as conn:
            row = conn.execute(
                "SELECT ticker_and_exchange_code, json_report, generated_time "
                "FROM analyses WHERE ticker_and_exchange_code = ?",
                (key,),
            ).fetchone()
    if not row:
        return None
    return AnalysisRow(
        ticker_and_exchange_code=row["ticker_and_exchange_code"],
        json_report=row["json_report"],
        generated_time=int(row["generated_time"]),
    )


def list_analyses(project_root: Path) -> list[AnalysisRow]:
    ensure_store(project_root)
    if uses_postgres():
        with _pg_conn() as conn:
            rows = conn.execute(
                "SELECT ticker_and_exchange_code, json_report, generated_time "
                "FROM analyses ORDER BY generated_time DESC"
            ).fetchall()
    else:
        with _sqlite_conn(project_root) as conn:
            rows = conn.execute(
                "SELECT ticker_and_exchange_code, json_report, generated_time "
                "FROM analyses ORDER BY generated_time DESC"
            ).fetchall()
    return [
        AnalysisRow(
            ticker_and_exchange_code=r["ticker_and_exchange_code"],
            json_report=r["json_report"],
            generated_time=int(r["generated_time"]),
        )
        for r in rows
    ]


def upsert_analysis(project_root: Path, ticker: str, json_report: str, generated_time: int) -> None:
    ensure_store(project_root)
    key = ticker.upper()
    if uses_postgres():
        with _pg_conn() as conn:
            conn.execute(
                """
                INSERT INTO analyses (ticker_and_exchange_code, json_report, generated_time)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker_and_exchange_code) DO UPDATE SET
                    json_report = EXCLUDED.json_report,
                    generated_time = EXCLUDED.generated_time
                """,
                (key, json_report, generated_time),
            )
            conn.commit()
        return

    with _sqlite_conn(project_root) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO analyses (ticker_and_exchange_code, json_report, generated_time)
            VALUES (?, ?, ?)
            """,
            (key, json_report, generated_time),
        )
        conn.commit()


def upsert_trigger(project_root: Path, ticker: str, triggered_at: int) -> None:
    """Record when an analysis was last triggered (persists across refreshes)."""
    ensure_store(project_root)
    key = ticker.upper()
    if uses_postgres():
        with _pg_conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_triggers (ticker_and_exchange_code, triggered_at)
                VALUES (%s, %s)
                ON CONFLICT (ticker_and_exchange_code) DO UPDATE SET triggered_at = EXCLUDED.triggered_at
                """,
                (key, triggered_at),
            )
            conn.commit()
        return
    with _sqlite_conn(project_root) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_triggers (ticker_and_exchange_code, triggered_at) VALUES (?, ?)",
            (key, triggered_at),
        )
        conn.commit()


def delete_trigger(project_root: Path, ticker: str) -> None:
    """Remove a pending trigger entry (e.g. after analysis completes or expires)."""
    ensure_store(project_root)
    key = ticker.upper()
    if uses_postgres():
        with _pg_conn() as conn:
            conn.execute(
                "DELETE FROM pending_triggers WHERE ticker_and_exchange_code = %s", (key,)
            )
            conn.commit()
        return
    with _sqlite_conn(project_root) as conn:
        conn.execute(
            "DELETE FROM pending_triggers WHERE ticker_and_exchange_code = ?", (key,)
        )
        conn.commit()


def get_trigger(project_root: Path, ticker: str) -> int | None:
    """Return the last triggered_at ms timestamp for a ticker, or None."""
    ensure_store(project_root)
    key = ticker.upper()
    if uses_postgres():
        with _pg_conn() as conn:
            row = conn.execute(
                "SELECT triggered_at FROM pending_triggers WHERE ticker_and_exchange_code = %s", (key,)
            ).fetchone()
    else:
        with _sqlite_conn(project_root) as conn:
            row = conn.execute(
                "SELECT triggered_at FROM pending_triggers WHERE ticker_and_exchange_code = ?", (key,)
            ).fetchone()
    return int(row["triggered_at"]) if row else None


def row_to_moonstocks_json(row: AnalysisRow) -> dict[str, Any]:
    return {
        "tickerAndExchangeCode": row.ticker_and_exchange_code,
        "generatedTime": row.generated_time,
        "report": json.loads(row.json_report) if row.json_report else None,
    }


def row_to_compat_json(row: AnalysisRow) -> dict[str, Any]:
    return {
        "tickerAndExchangeCode": row.ticker_and_exchange_code,
        "jsonReport": row.json_report,
        "generatedTime": row.generated_time,
    }


def upsert_user(project_root: Path, user_id: str, *, display_name: str | None = None, email: str | None = None) -> None:
    ensure_store(project_root)
    now = int(time.time() * 1000)
    uid = (user_id or "").strip()
    if not uid:
        return
    label = (display_name or "").strip() or f"User {uid[:8]}"
    if uses_postgres():
        with _pg_conn() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, display_name, email, created_at, last_login_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                    email = COALESCE(EXCLUDED.email, users.email),
                    last_login_at = EXCLUDED.last_login_at
                """,
                (uid, label, email, now, now),
            )
            conn.commit()
        return
    with _sqlite_conn(project_root) as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, display_name, email, created_at, last_login_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, users.display_name),
                email = COALESCE(excluded.email, users.email),
                last_login_at = excluded.last_login_at
            """,
            (uid, label, email, now, now),
        )
        conn.commit()


def get_user(project_root: Path, user_id: str) -> dict[str, Any] | None:
    ensure_store(project_root)
    uid = (user_id or "").strip()
    if not uid:
        return None
    if uses_postgres():
        with _pg_conn() as conn:
            row = conn.execute(
                "SELECT user_id, display_name, email, created_at, last_login_at FROM users WHERE user_id = %s",
                (uid,),
            ).fetchone()
    else:
        with _sqlite_conn(project_root) as conn:
            row = conn.execute(
                "SELECT user_id, display_name, email, created_at, last_login_at FROM users WHERE user_id = ?",
                (uid,),
            ).fetchone()
    if not row:
        return None
    return dict(row)


def list_favorites(project_root: Path, user_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    ensure_store(project_root)
    uid = (user_id or "").strip()
    if not uid:
        return []
    if uses_postgres():
        with _pg_conn() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT kind, item_key, created_at FROM favorites WHERE user_id = %s AND kind = %s ORDER BY created_at DESC",
                    (uid, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT kind, item_key, created_at FROM favorites WHERE user_id = %s ORDER BY created_at DESC",
                    (uid,),
                ).fetchall()
    else:
        with _sqlite_conn(project_root) as conn:
            if kind:
                rows = conn.execute(
                    "SELECT kind, item_key, created_at FROM favorites WHERE user_id = ? AND kind = ? ORDER BY created_at DESC",
                    (uid, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT kind, item_key, created_at FROM favorites WHERE user_id = ? ORDER BY created_at DESC",
                    (uid,),
                ).fetchall()
    return [dict(r) for r in rows]


def add_favorite(project_root: Path, user_id: str, kind: str, item_key: str) -> bool:
    ensure_store(project_root)
    uid = (user_id or "").strip()
    k = (kind or "").strip().lower()
    key = (item_key or "").strip()
    if not uid or not k or not key:
        return False
    if k == "symbol":
        key = key.upper()
    now = int(time.time() * 1000)
    if uses_postgres():
        with _pg_conn() as conn:
            conn.execute(
                """
                INSERT INTO favorites (user_id, kind, item_key, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, kind, item_key) DO NOTHING
                """,
                (uid, k, key, now),
            )
            conn.commit()
        return True
    with _sqlite_conn(project_root) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO favorites (user_id, kind, item_key, created_at) VALUES (?, ?, ?, ?)",
            (uid, k, key, now),
        )
        conn.commit()
    return True


def remove_favorite(project_root: Path, user_id: str, kind: str, item_key: str) -> bool:
    ensure_store(project_root)
    uid = (user_id or "").strip()
    k = (kind or "").strip().lower()
    key = (item_key or "").strip()
    if k == "symbol":
        key = key.upper()
    if not uid or not k or not key:
        return False
    if uses_postgres():
        with _pg_conn() as conn:
            conn.execute(
                "DELETE FROM favorites WHERE user_id = %s AND kind = %s AND item_key = %s",
                (uid, k, key),
            )
            conn.commit()
        return True
    with _sqlite_conn(project_root) as conn:
        conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND kind = ? AND item_key = ?",
            (uid, k, key),
        )
        conn.commit()
    return True


def is_favorite(project_root: Path, user_id: str, kind: str, item_key: str) -> bool:
    ensure_store(project_root)
    uid = (user_id or "").strip()
    k = (kind or "").strip().lower()
    key = (item_key or "").strip()
    if k == "symbol":
        key = key.upper()
    if not uid or not k or not key:
        return False
    if uses_postgres():
        with _pg_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE user_id = %s AND kind = %s AND item_key = %s",
                (uid, k, key),
            ).fetchone()
    else:
        with _sqlite_conn(project_root) as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE user_id = ? AND kind = ? AND item_key = ?",
                (uid, k, key),
            ).fetchone()
    return bool(row)
