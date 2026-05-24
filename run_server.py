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


def _require_postgres_for_native_dev() -> None:
    """Fail fast when DB config does not match production (Postgres on host or in compose)."""
    if (os.environ.get("MOONSTOCKS_DB_PATH") or "").strip():
        print(
            "ERROR: MOONSTOCKS_DB_PATH is for unit tests only. "
            "Unset it and set MOONSTOCKS_DATABASE_URL (see .env.native.example).",
            flush=True,
        )
        sys.exit(1)

    url = _moonstocks_db_url()
    if not url:
        print(
            "ERROR: MOONSTOCKS_DATABASE_URL is required for run_server.py.\n"
            "  Native: copy .env.native.example → .env, then:\n"
            f"    docker compose -f {_COMPOSE} up -d postgres\n"
            "  Full stack: docker compose -f docker-compose.moonstocks.yml up -d",
            flush=True,
        )
        sys.exit(1)

    if not (url.startswith("postgresql://") or url.startswith("postgres://")):
        print(f"ERROR: MOONSTOCKS_DATABASE_URL must be postgres://… (got {url[:40]}…)", flush=True)
        sys.exit(1)

    if any(h in url for h in ("@postgres:", "@postgres/", "host=postgres")):
        print(
            "ERROR: MOONSTOCKS_DATABASE_URL uses hostname 'postgres' (Docker network only).\n"
            "  For native run_server on the host, use 127.0.0.1 — see .env.native.example:\n"
            "    MOONSTOCKS_DATABASE_URL=postgresql://moonstocks:moonstocks@127.0.0.1:5432/moonstocks\n"
            f"  Then start Postgres: docker compose -f {_COMPOSE} up -d postgres",
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
            f"  Start DB: docker compose -f {_COMPOSE} up -d postgres",
            flush=True,
        )
        sys.exit(1)

    print("  [moonstocks] Postgres OK", flush=True)


def _require_analyzer_for_native_dev() -> None:
    """Native Flask must call analyzer on localhost, not Docker service name 'analyzer'."""
    raw = (os.environ.get("MOONSTOCKS_ANALYZER_URL") or "").strip()
    if not raw:
        print(
            "ERROR: MOONSTOCKS_ANALYZER_URL is required.\n"
            "  Set MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000 in .env\n"
            "  Start analyzer: .\\scripts\\start-local-analyzer.ps1",
            flush=True,
        )
        sys.exit(1)
    if "://analyzer:" in raw or "://analyzer/" in raw:
        print(
            "ERROR: MOONSTOCKS_ANALYZER_URL uses hostname 'analyzer' (Docker network only).\n"
            "  For native run_server use: MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000\n"
            "  Start analyzer: .\\scripts\\start-local-analyzer.ps1\n"
            "  Or run full stack: docker compose -f docker-compose.moonstocks.yml up -d",
            flush=True,
        )
        sys.exit(1)
    try:
        import urllib.request

        urllib.request.urlopen(raw.rstrip("/") + "/health", timeout=3)
        print(f"  [moonstocks] Analyzer OK ({raw})", flush=True)
    except Exception as exc:
        print(
            f"ERROR: Moonstocks analyzer not reachable at {raw}\n"
            f"  {exc}\n"
            "  Start in another terminal: .\\scripts\\start-local-analyzer.ps1",
            flush=True,
        )
        sys.exit(1)


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
    load_dotenv(os.path.join(_ROOT, ".env"), override=True)
except ImportError:
    pass
_require_postgres_for_native_dev()
_require_analyzer_for_native_dev()

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
