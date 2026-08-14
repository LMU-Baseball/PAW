"""Production WSGI entrypoint for gunicorn.

    gunicorn -c gunicorn.conf.py wsgi:app

Mirrors run.py's app construction but WITHOUT the Flask dev server / reloader
(gunicorn is the server in production). Warms the dashboard caches at startup
(PAW_WARM_CACHE) so the first open on each worker is fast. Secrets + DB creds
come from the gitignored .env on the host (see config.py / docs/DEPLOY.md).
"""
import os

# Warm caches at startup (per worker). Set before create_app so the app wires
# the warm thread. Override with PAW_WARM_CACHE="" to skip (e.g. a smoke import).
os.environ.setdefault("PAW_WARM_CACHE", "1")

from app import create_app  # noqa: E402

app = create_app()
