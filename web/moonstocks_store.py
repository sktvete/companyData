"""Moonstocks AI analysis storage (PostgreSQL or SQLite)."""
from __future__ import annotations

import json
import os
import sqlite3
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
    # MOONSTOCKS_DB_PATH is for unit/E2E tests only — not run_server.py or production.
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
