"""Development entry point:  python run.py  (or: flask --app run run)."""
import os

# Warm the dashboard caches at startup so even the first open is fast (see
# app/warmup.py). Set before create_app so the app wires the warm thread.
os.environ.setdefault("PAW_WARM_CACHE", "1")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    host, port = "127.0.0.1", 8050
    print(f"\n  PAW is running ->  http://{host}:{port}")
    print("  Open that EXACT address in your browser.")
    print("  (On Windows, 'localhost' can resolve to IPv6 and fail — use 127.0.0.1.)\n")
    # use_reloader=False is required: the pitcher report launches headless
    # Chromium via Playwright (~40s). With the auto-reloader on, a filesystem
    # event on any watched dependency (e.g. site-packages/flask_login,
    # site-packages/playwright) restarts the server mid-request and tears down
    # the in-flight PDF build -> Chromium's pipe breaks (EPIPE) and the browser
    # download hangs then disconnects. debug=True still gives the interactive
    # debugger and Jinja template auto-reload; only Python code edits now need a
    # manual restart.
    #
    # threaded=True: without it this single-threaded dev server serializes
    # EVERY request -- confirmed live (2026-09-22) that it made bullpen video
    # look broken, not just slow: Dash's own polling traffic held the one
    # worker busy while a ~3-4MB video clip (each fetch costs ~1.5-2s of real
    # DB round-trip, unrelated to threading) sat queued behind it, so Chrome's
    # <video> request could take 10s+ to even start and looked hung. Threads
    # are safe here -- SQLAlchemy's engine is pooled/thread-safe -- and
    # production never uses this path at all (gunicorn, multiple worker
    # processes, see docs/DEPLOY.md), so this only changes local dev.
    app.run(host=host, port=port, debug=True, use_reloader=False, threaded=True)
