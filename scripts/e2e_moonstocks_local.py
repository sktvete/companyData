#!/usr/bin/env python3
"""Local Moonstocks stack smoke test (no Docker, no Claude).

Starts a mock analyzer, exercises equity-os API on :3000.

Usage:
  python scripts/e2e_moonstocks_local.py --start-server
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:3000"
TICKER = "E2E.US"
PORT = 3000


def _kill_port(port: int) -> None:
    """Free the port before starting equity-os (Windows)."""
    if sys.platform != "win32":
        return
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port}" | findstr "LISTEN"',
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        pids = set()
        for line in out.strip().splitlines():
            parts = line.split()
            if parts:
                pids.add(int(parts[-1]))
        pids.discard(os.getpid())
        for proc_id in pids:
            try:
                os.kill(proc_id, signal.SIGTERM)
                print(f"  Freed port {port} (PID {proc_id})")
            except OSError:
                pass
        if pids:
            time.sleep(1)
    except (subprocess.CalledProcessError, OSError):
        pass


def _http(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: float = 30) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})} if body is not None else dict(headers or {})
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def _get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    return _http(url, "GET", timeout=timeout)


def _post(url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 30) -> tuple[int, bytes]:
    return _http(url, "POST", body=body, headers=headers, timeout=timeout)


def _wait_equity_os_ready(seconds: float = 180) -> None:
    """Wait until load_data() finished (health alone returns before universe is ready)."""
    _wait_http(f"{BASE}/health", "equity-os health", seconds=seconds)
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            status, body = _get(f"{BASE}/api/companies?limit=1", timeout=10)
            if status == 200:
                payload = json.loads(body)
                items = payload if isinstance(payload, list) else payload.get("companies") or payload.get("items") or []
                if items:
                    print(f"  OK equity-os universe loaded ({len(items)}+ companies)")
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Timeout waiting for equity-os universe")


def _wait_http(url: str, label: str, seconds: float = 180) -> None:
    deadline = time.time() + seconds
    last_err = ""
    while time.time() < deadline:
        try:
            status, _ = _get(url, timeout=3)
            if status == 200:
                print(f"  OK {label} ({url})")
                return
        except URLError as exc:
            last_err = str(exc)
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"Timeout waiting for {label}: {last_err}")


class MockAnalyzerHandler(BaseHTTPRequestHandler):
    callback_base = BASE

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        ticker = self.path.lstrip("/")
        if not ticker or "." not in ticker:
            self.send_error(400)
            return
        report = {
            "ticker": ticker.split(".")[0],
            "exchange": ticker.split(".", 1)[1],
            "recommendation": "watchlist",
            "confidence": "medium",
            "overall_score": 55,
            "analysis_date": "2026-05-20",
            "scores": {"quality_score": 6, "growth_score": 5},
            "decision_summary": {
                "main_reason_for_recommendation": "E2E mock analysis.",
                "bull_case": ["Automated test"],
                "bear_case": ["Not real AI"],
            },
        }
        payload = json.dumps({"jsonReport": json.dumps(report)}).encode()
        url = f"{self.callback_base}/api/analysis/{ticker}"
        req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=15) as resp:
                ok = 200 <= resp.status < 300
        except URLError as exc:
            self._json(502, {"error": f"callback failed: {exc}"})
            return
        if ok:
            self._json(202, {"status": "accepted", "ticker_exchange": ticker})
        else:
            self._json(502, {"error": "callback non-2xx"})

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_mock_analyzer(port: int) -> HTTPServer:
    MockAnalyzerHandler.callback_base = BASE
    srv = HTTPServer(("127.0.0.1", port), MockAnalyzerHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def run_checks() -> None:
    print("[1/7] Health")
    status, body = _get(f"{BASE}/health")
    assert status == 200, body
    assert json.loads(body)["service"] == "equity-os"

    print("[2/7] GET missing analysis -> 404")
    status, _ = _get(f"{BASE}/api/moonstocks/{TICKER}")
    assert status == 404, f"expected 404, got {status}"

    print("[3/7] POST ingest (direct)")
    report = {"recommendation": "buy", "overall_score": 80, "confidence": "high"}
    status, body = _post(
        f"{BASE}/api/analysis/{TICKER}",
        {"jsonReport": json.dumps(report)},
    )
    assert status == 200, body

    print("[4/7] GET analysis after ingest")
    status, body = _get(f"{BASE}/api/moonstocks/{TICKER}")
    assert status == 200, body
    data = json.loads(body)
    assert data["report"]["recommendation"] == "buy"

    print("[5/7] GET /api/analysis list (compat)")
    status, body = _get(f"{BASE}/api/analysis")
    assert status == 200
    rows = json.loads(body)
    assert any(r["tickerAndExchangeCode"] == TICKER for r in rows)

    print("[6/7] Trigger -> mock analyzer -> callback -> fresh report")
    status, body = _post(f"{BASE}/api/moonstocks/{TICKER}/trigger")
    assert status == 202, body
    deadline = time.time() + 15
    while time.time() < deadline:
        status, body = _get(f"{BASE}/api/moonstocks/{TICKER}")
        if status == 200:
            data = json.loads(body)
            if data["report"].get("recommendation") == "watchlist":
                print("  OK trigger round-trip (watchlist from mock)")
                break
        time.sleep(0.3)
    else:
        raise RuntimeError("Trigger did not update DB with mock watchlist report")

    print("[7/7] Company page includes Moonstocks UI")
    html = ""
    for attempt in range(5):
        try:
            status, body = _get(f"{BASE}/company/DECK", timeout=60)
            if status == 200:
                html = body.decode("utf-8", errors="replace")
                break
        except (URLError, ConnectionResetError, OSError) as exc:
            if attempt == 4:
                raise RuntimeError(f"company page failed: {exc}") from exc
            time.sleep(2)
    assert "msSection" in html and "msTriggerBtn" in html, "Moonstocks section missing on company page"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-server", action="store_true", help="Start run_server.py (recommended)")
    parser.add_argument("--mock-port", type=int, default=8765)
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="moonstocks_e2e_")
    db_path = str(Path(tmp) / "e2e.db")
    mock_url = f"http://127.0.0.1:{args.mock_port}"

    server_proc = None
    if args.start_server:
        _kill_port(PORT)
        env = os.environ.copy()
        env["MOONSTOCKS_ANALYZER_URL"] = mock_url
        env["MOONSTOCKS_DB_PATH"] = db_path
        # Avoid inheriting prod analyzer URL from shell/.env
        env.pop("MOONSTOCKS_API_URL", None)
        print("Starting equity-os on :3000 (may take ~60s for load_data)...")
        server_proc = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "run_server.py")],
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        _wait_equity_os_ready(seconds=180)
    else:
        print("Use --start-server so equity-os uses the local mock analyzer.", file=sys.stderr)
        return 1

    print(f"Starting mock analyzer on :{args.mock_port} ...")
    _run_mock_analyzer(args.mock_port)
    _wait_http(f"{mock_url}/health", "mock analyzer", seconds=10)

    try:
        run_checks()
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()

    print("\nAll Moonstocks local E2E checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
