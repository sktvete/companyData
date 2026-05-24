"""Launcher for the web app on port 3000."""
import sys, os, io, traceback, subprocess, signal

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

PORT = 3000
_ROOT = os.path.dirname(os.path.abspath(__file__))
_COMPOSE = "docker-compose.moonstocks.yml"


def _moonstocks_db_url() -> str:
    return (
        os.environ.get("MOONSTOCKS_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()


def _check_db() -> None:
    """Validate DB config and connect.

    Supports two modes:
    - Postgres (prod/native): MOONSTOCKS_DATABASE_URL=postgresql://...
    - SQLite (local no-Docker): MOONSTOCKS_DB_PATH=./moonstocks_local.db

    E2E tests bypass this entirely via _MOONSTOCKS_E2E=1.
    """
    if os.environ.get("_MOONSTOCKS_E2E") == "1":
        return

    db_path = (os.environ.get("MOONSTOCKS_DB_PATH") or "").strip()
    url = _moonstocks_db_url()

    if db_path and url:
        print(
            "ERROR: Both MOONSTOCKS_DB_PATH and MOONSTOCKS_DATABASE_URL are set — use one or the other.",
            flush=True,
        )
        sys.exit(1)

    if db_path:
        # SQLite local mode — no Postgres required.
        print(f"  [moonstocks] SQLite mode: {db_path}", flush=True)
        return

    if not url:
        print(
            "ERROR: Set MOONSTOCKS_DATABASE_URL (Postgres) or MOONSTOCKS_DB_PATH (SQLite) in .env.\n"
            "  Postgres example: MOONSTOCKS_DATABASE_URL=postgresql://moonstocks:moonstocks@127.0.0.1:5432/moonstocks\n"
            "  SQLite example:   MOONSTOCKS_DB_PATH=./moonstocks_local.db\n"
            f"  Start Postgres:   docker compose -f {_COMPOSE} up -d postgres",
            flush=True,
        )
        sys.exit(1)

    if not (url.startswith("postgresql://") or url.startswith("postgres://")):
        print(f"ERROR: MOONSTOCKS_DATABASE_URL must be postgresql://... (got {url[:40]}...)", flush=True)
        sys.exit(1)

    if any(h in url for h in ("@postgres:", "@postgres/", "host=postgres")):
        print(
            "ERROR: MOONSTOCKS_DATABASE_URL uses hostname 'postgres' (Docker network only).\n"
            "  For native run_server use 127.0.0.1 or set MOONSTOCKS_DB_PATH for SQLite.",
            flush=True,
        )
        sys.exit(1)

    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg is required (pip install 'psycopg[binary]').", flush=True)
        sys.exit(1)

    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        print(
            "ERROR: Cannot connect to Moonstocks Postgres.\n"
            f"  URL: {url.split('@')[-1] if '@' in url else url}\n"
            f"  {exc}\n"
            f"  Start DB:  docker compose -f {_COMPOSE} up -d postgres\n"
            "  Or use SQLite: set MOONSTOCKS_DB_PATH=./moonstocks_local.db in .env",
            flush=True,
        )
        sys.exit(1)

    print("  [moonstocks] Postgres OK", flush=True)


def _check_analyzer() -> None:
    """Warn (not error) when the analyzer is unreachable — screener works without it."""
    if os.environ.get("_MOONSTOCKS_E2E") == "1":
        return
    raw = (os.environ.get("MOONSTOCKS_ANALYZER_URL") or "").strip()
    if not raw:
        print("  [moonstocks] MOONSTOCKS_ANALYZER_URL not set — AI analysis triggers disabled.", flush=True)
        return
    if "://analyzer:" in raw or "://analyzer/" in raw:
        print(
            "ERROR: MOONSTOCKS_ANALYZER_URL uses hostname 'analyzer' (Docker network only).\n"
            "  For native run_server use: MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000",
            flush=True,
        )
        sys.exit(1)
    try:
        import urllib.request
        urllib.request.urlopen(raw.rstrip("/") + "/health", timeout=3)
        print(f"  [moonstocks] Analyzer OK ({raw})", flush=True)
    except Exception:
        print(
            f"  [moonstocks] Analyzer not reachable at {raw} — AI triggers will fail.\n"
            "  Start it: .\\scripts\\start-local-analyzer.ps1",
            flush=True,
        )


def _kill_port(port: int):
    """Kill every process listening on *port* (Windows-only)."""
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port}" | findstr "LISTEN"',
            shell=True, text=True, stderr=subprocess.DEVNULL,
        )
        pids = set()
        for line in out.strip().splitlines():
            parts = line.split()
            if parts:
                pids.add(int(parts[-1]))
        pids.discard(os.getpid())
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  Killed stale process PID {pid}", flush=True)
            except OSError:
                pass
        if pids:
            import time; time.sleep(1)
    except (subprocess.CalledProcessError, Exception):
        pass

print(f"[0/3] Clearing port {PORT}...", flush=True)
_kill_port(PORT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"), override=False)
except ImportError:
    pass
_check_db()
_check_analyzer()

os.chdir(os.path.join(os.path.dirname(__file__), "web"))
sys.path.insert(0, ".")

try:
    print("[1/3] Importing app...", flush=True)
    from app_enhanced import app, load_data
    print("[2/3] Loading company data + margin history...", flush=True)
    load_data()
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    print(f"[3/3] Starting server on http://localhost:3000", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
except Exception:
    traceback.print_exc()
    sys.exit(1)
