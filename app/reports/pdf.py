"""Render HTML to PDF bytes using headless Chromium (Playwright)."""
from __future__ import annotations

import re

from playwright.sync_api import sync_playwright

_MARGIN = {"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"}


def _with_base(html: str, base_url: str | None) -> str:
    """Insert a <base> tag so relative asset URLs resolve against base_url.

    Playwright's Page.set_content() has no base_url parameter (installed
    version: 1.61.0), so the base is injected into the markup instead.
    """
    if not base_url:
        return html
    base_tag = f'<base href="{base_url}">'
    head_match = re.search(r"<head[^>]*>", html, flags=re.IGNORECASE)
    if head_match:
        idx = head_match.end()
        return html[:idx] + base_tag + html[idx:]
    html_match = re.search(r"<html[^>]*>", html, flags=re.IGNORECASE)
    if html_match:
        idx = html_match.end()
        return html[:idx] + f"<head>{base_tag}</head>" + html[idx:]
    return f"<head>{base_tag}</head>" + html


def html_to_pdf(html: str, base_url: str | None = None) -> bytes:
    """Convert a full HTML document to PDF bytes.

    Launches Chromium per call (simple; optimize with a shared browser later).
    `base_url` sets the document base so relative asset URLs resolve.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(_with_base(html, base_url), wait_until="networkidle")
            return page.pdf(
                format="Letter",
                print_background=True,
                margin=_MARGIN,
            )
        finally:
            browser.close()
