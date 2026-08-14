"""Gunicorn config for PAW on a Linux host (e.g. AWS Lightsail).

    gunicorn -c gunicorn.conf.py wsgi:app

Fronted by nginx (TLS termination + static files); gunicorn binds loopback
only. See docs/DEPLOY.md for the full runbook.
"""
import os

# nginx reverse-proxies :443 -> here. Bind loopback so gunicorn is never
# directly reachable from the internet.
bind = "127.0.0.1:8050"

# A ~30-50 user internal tool needs little. Each worker keeps its OWN in-process
# cache + background warm thread (PAW_WARM_CACHE); cross-process precalc
# invalidation (cache.configure in create_app) keeps workers consistent. So do
# NOT enable --preload: preloading forks AFTER app construction, so each
# worker's warm thread wouldn't start. gthread + a few threads absorbs the
# DB-wait / long-report concurrency without a worker-per-request blowup.
workers = int(os.getenv("WEB_CONCURRENCY", "3"))
threads = int(os.getenv("WEB_THREADS", "4"))
worker_class = "gthread"
preload_app = False

# Pitcher-report PDFs launch headless Chromium (~40s) -- far above gunicorn's
# 30s default; a slow download must not have its worker killed mid-build.
timeout = 180
graceful_timeout = 30
keepalive = 5

# Log to stdout/stderr so systemd/journald captures everything.
accesslog = "-"
errorlog = "-"
loglevel = "info"
