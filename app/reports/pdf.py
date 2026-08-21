"""Render HTML to PDF bytes using headless Chromium (Playwright).

A single headless Chromium is launched once and reused across calls: launching a
fresh browser per render cost ~1.5-2s each (the dominant miss-path cost).

Concurrency is the tricky part. The sync Playwright API is not merely
non-thread-safe -- it is pinned (via greenlet) to the exact OS thread that
created it: touching any Playwright object (even `browser.is_connected()`) from a
different thread raises `greenlet.error: cannot switch to a different thread`. A
mere `threading.Lock` does NOT help, because Werkzeug/Flask serve each request on
a fresh, unpooled thread that then dies -- so the thread that built the singleton
is gone by the next request, and every later report would 500.

The fix: ONE long-lived daemon "render thread" owns Playwright + Chromium, and
ALL Playwright calls execute on it. Callers submit the html to a queue and block
on a Future; the render thread does the actual rendering and hands bytes (or the
exception) back. Callers never touch a Playwright object, so it doesn't matter
which thread they run on.
"""
from __future__ import annotations

import atexit
import logging
import queue
import re
import threading
from concurrent.futures import Future, TimeoutError as FuturesTimeout
from html import escape

from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)


class ReportEngineError(RuntimeError):
    """The PDF engine itself failed -- Chromium could not launch, crashed, or
    timed out.

    Distinct from `ReportDataError` (there is no data to report on, a 404): this
    means the report COULD have been built but the renderer is broken, which is
    an infrastructure problem and a 503. Hosts that can't run headless Chromium
    -- too little RAM, or `playwright install` run without `--with-deps` so the
    browser's shared libraries are missing -- fail here on every request.
    """


_MARGIN = {"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"}

# How long a caller waits for its PDF before giving up (a stuck Chromium must not
# hang the request thread forever). Generous: cold launch + render is a few sec.
_RENDER_TIMEOUT = 60.0

_JOBS: "queue.Queue[tuple[str, Future] | None]" = queue.Queue()
_START_LOCK = threading.Lock()
_render_thread: threading.Thread | None = None
_SHUTDOWN = object()  # sentinel job: close browser + stop playwright, then exit


def _render_loop() -> None:
    """The render thread's body: own Playwright/Chromium; serve jobs one at a time.

    Everything Playwright here -- start, launch, new_page, set_content, pdf,
    page.close, and the final close/stop -- runs on THIS thread only.
    """
    playwright = None
    browser = None
    try:
        while True:
            job = _JOBS.get()
            if job is None or job[0] is _SHUTDOWN:
                break
            html, fut = job
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                if playwright is None:
                    playwright = sync_playwright().start()
                # Relaunch a browser that was never started or has since crashed.
                if browser is None or not browser.is_connected():
                    browser = playwright.chromium.launch()
                page = browser.new_page()
                try:
                    page.set_content(html, wait_until="load")
                    pdf = page.pdf(format="Letter", print_background=True,
                                   margin=_MARGIN)
                finally:
                    page.close()
                fut.set_result(pdf)
            except Exception as exc:  # surface real render failures to the caller
                # Drop a possibly-wedged browser so the next job relaunches clean.
                try:
                    if browser is not None and not browser.is_connected():
                        browser = None
                except Exception:
                    browser = None
                fut.set_exception(exc)
    finally:
        try:
            if browser is not None and browser.is_connected():
                browser.close()
        except Exception:
            pass
        try:
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass


def _ensure_render_thread() -> None:
    """Start the daemon render thread once (thread-safe lazy init)."""
    global _render_thread
    if _render_thread is not None and _render_thread.is_alive():
        return
    with _START_LOCK:
        if _render_thread is None or not _render_thread.is_alive():
            _render_thread = threading.Thread(
                target=_render_loop, name="pdf-render", daemon=True)
            _render_thread.start()


@atexit.register
def _shutdown() -> None:
    """Signal the render thread to tear down Chromium on its own thread, join.

    Fully guarded so it never raises at interpreter exit.
    """
    t = _render_thread
    if t is None or not t.is_alive():
        return
    try:
        _JOBS.put((_SHUTDOWN, Future()))
        t.join(timeout=5.0)
    except Exception:
        pass


def _with_base(html: str, base_url: str | None) -> str:
    """Insert a <base> tag so relative asset URLs resolve against base_url.

    Playwright's Page.set_content() has no base_url parameter (installed
    version: 1.61.0), so the base is injected into the markup instead.
    """
    if not base_url:
        return html
    base_tag = f'<base href="{escape(base_url, quote=True)}">'
    head_match = re.search(r"<head(?=[\s>])[^>]*>", html, flags=re.IGNORECASE)
    if head_match:
        idx = head_match.end()
        return html[:idx] + base_tag + html[idx:]
    html_match = re.search(r"<html(?=[\s>])[^>]*>", html, flags=re.IGNORECASE)
    if html_match:
        idx = html_match.end()
        return html[:idx] + f"<head>{base_tag}</head>" + html[idx:]
    return f"<head>{base_tag}</head>" + html


def html_to_pdf(html: str, base_url: str | None = None) -> bytes:
    """Convert a full HTML document to PDF bytes.

    Submits the render to a shared, long-lived Chromium owned by a dedicated
    render thread (see _render_loop) and blocks for the result -- safe to call
    from any thread (Werkzeug hands each request a fresh, unpooled thread).
    `base_url` sets the document base so relative asset URLs resolve.

    All report assets (fonts, logos, chart PNGs) are inlined as data: URIs, so
    there is no network to wait on -- wait_until="load" is correct and avoids
    the pointless idle wait "networkidle" imposed.
    """
    _ensure_render_thread()
    fut: Future = Future()
    _JOBS.put((_with_base(html, base_url), fut))
    try:
        return fut.result(timeout=_RENDER_TIMEOUT)
    except FuturesTimeout as exc:
        # A wedged Chromium must not read as a generic 500 with no explanation.
        log.exception("PDF render timed out after %ss", _RENDER_TIMEOUT)
        raise ReportEngineError(
            f"PDF rendering timed out after {_RENDER_TIMEOUT:.0f}s") from exc
    except Exception as exc:
        # Chromium failed to launch or died mid-render. Log the real cause HERE
        # -- it is the only place that sees it -- so the host's logs name the
        # missing library / OOM kill instead of swallowing it into a bare 500.
        log.exception("PDF render failed: %s", exc)
        raise ReportEngineError(str(exc) or exc.__class__.__name__) from exc
