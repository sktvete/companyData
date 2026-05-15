"""Launcher for the web app on port 3000."""
import sys, os, io, traceback, subprocess, signal

if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

PORT = 3000

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
    app.run(host="0.0.0.0", port=3000, debug=True, use_reloader=False)
except Exception:
    traceback.print_exc()
    sys.exit(1)
