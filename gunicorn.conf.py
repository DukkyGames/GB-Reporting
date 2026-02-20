"""
Gunicorn config. Use with: gunicorn -c gunicorn.conf.py app:app

The when_ready hook starts the scheduler (nightly refresh at CACHE_HOUR:CACHE_MINUTE,
incremental refresh every 5 min). Without this, the scheduler never runs under gunicorn.
"""
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "sync"
timeout = 300  # Allow long-running refresh requests
preload = True  # Load app in master so scheduler runs in one process only


def when_ready(server):
    """Start the cache refresh scheduler in the master process."""
    from app import _bootstrap
    _bootstrap()
