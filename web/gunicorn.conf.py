"""Gunicorn production configuration for equity-os.

Workers share the loaded universe via COW memory after on_starting forks.
All settings are overridable via environment variables so the same image
works in every environment (local Docker, ECS Fargate, etc.).
"""

import multiprocessing
import os

# ---------------------------------------------------------------------------
# Workers & concurrency
# ---------------------------------------------------------------------------
# Cap at 4: each worker holds the in-memory universe (can be 500 MB+ at scale).
# gthread handles SSE streams and regular requests on the same worker.
_cpu = multiprocessing.cpu_count()
workers = int(os.environ.get("GUNICORN_WORKERS", min(_cpu * 2 + 1, 4)))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"

# ---------------------------------------------------------------------------
# Memory hygiene
# ---------------------------------------------------------------------------
# Recycle workers periodically to prevent gradual memory growth.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 500))
max_requests_jitter = 100

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
# SSE streams (AI analysis) and long EODHD fetches can run for minutes.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 300))
graceful_timeout = 30
keepalive = 5

# ---------------------------------------------------------------------------
# Logging — stdout/stderr only so CloudWatch / ECS captures everything
# ---------------------------------------------------------------------------
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ---------------------------------------------------------------------------
# Bind
# ---------------------------------------------------------------------------
bind = f"0.0.0.0:{os.environ.get('PORT', '3000')}"

# ---------------------------------------------------------------------------
# Startup hook — load universe ONCE in the master process.
# Workers fork afterwards and inherit the loaded data via copy-on-write,
# so the expensive load_data() call is paid only once regardless of workers.
# ---------------------------------------------------------------------------
def on_starting(server):
    from app_enhanced import load_data
    load_data()
