"""Development entry point:  python run.py  (or: flask --app run run)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    host, port = "127.0.0.1", 8050
    print(f"\n  PAW is running →  http://{host}:{port}")
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
    app.run(host=host, port=port, debug=True, use_reloader=False)
