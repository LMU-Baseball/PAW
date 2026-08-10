"""Render HTML to PDF bytes using headless Chromium (Playwright)."""
from __future__ import annotations

import atexit
import re
import threading
from html import escape

from playwright.sync_api import sync_playwright

_MARGIN = {"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"}

# A single headless Chromium is launched once and reused across calls: launching
# a fresh browser per render cost ~1.5-2s each (the dominant miss-path cost). The
# sync Playwright API is NOT thread-safe, so every Playwright call (browser
# launch, page create/render, shutdown) is serialized under _LOCK -- Flask serves
# on multiple threads, and the report ZIP route renders pitchers back-to-back.
# Serializing renders is fine: it still beats relaunching Chromium every time.
_LOCK = threading.Lock()
_playwright = None  # the started sync_playwright() driver
_browser = None     # the shared Chromium instance


def _ensure_browser():
    """Return the shared Chromium, launching (or relaunching) it if needed.

    Must be called with _LOCK held. Relaunches when the browser was never
    started or has since crashed/disconnected.
    """
    global _playwright, _browser
    if _playwright is None:
        _playwright = sync_playwright().start()
    if _browser is None or not _browser.is_connected():
        _browser = _playwright.chromium.launch()
    return _browser


@atexit.register
def _shutdown() -> None:
    """Close the browser and stop Playwright at interpreter exit.

    Guarded so it never raises during shutdown (the driver may already be gone).
    """
    global _playwright, _browser
    with _LOCK:
        try:
            if _browser is not None and _browser.is_connected():
                _browser.close()
        except Exception:
            pass
        try:
            if _playwright is not None:
                _playwright.stop()
        except Exception:
            pass
        _browser = None
        _playwright = None


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

    Reuses a shared headless Chromium across calls (see _LOCK/_ensure_browser).
    `base_url` sets the document base so relative asset URLs resolve.

    All report assets (fonts, logos, chart PNGs) are inlined as data: URIs, so
    there is no network to wait on -- wait_until="load" is correct and avoids
    the pointless idle wait "networkidle" imposed.
    """
    with _LOCK:
        browser = _ensure_browser()
        page = browser.new_page()
        try:
            page.set_content(_with_base(html, base_url), wait_until="load")
            return page.pdf(
                format="Letter",
                print_background=True,
                margin=_MARGIN,
            )
        finally:
            page.close()
