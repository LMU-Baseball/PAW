"""Shared Dash shell: brand index_string, crimson header, constants, section helper.

A Dash page does not extend base.html, so the site's grey+palms background and
lion favicon live here (hardcoded — a Dash index_string cannot read base.html CSS
tokens; keep in sync with the site brand). See Memory §3c. This is the single
source for these values across ALL Dash dashboards (hitting, pitching, ...).
"""
from __future__ import annotations

from dash import html
from flask_login import current_user

CRIMSON = "#9A0021"
BANNER = "rgba(154,0,33,0.82)"
PHOTO_PLACEHOLDER = "/static/reports/lion.png"

_INDEX_STRING = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{%title%}</title>
<link rel="icon" type="image/png" href="/static/reports/lion.png">
{%css%}
<style>
  @font-face {
    font-family: "Teko"; font-weight: 400; font-display: swap;
    src: url("/static/reports/Teko-Regular.ttf") format("truetype");
  }
  @font-face {
    font-family: "Teko"; font-weight: 600; font-display: swap;
    src: url("/static/reports/Teko-SemiBold.ttf") format("truetype");
  }
  @font-face {
    font-family: "Teko"; font-weight: 700; font-display: swap;
    src: url("/static/reports/Teko-Bold.ttf") format("truetype");
  }
  @font-face {
    font-family: "Alfa Slab One"; font-weight: 400; font-display: swap;
    src: url("/static/brand/AlfaSlabOne-Regular.ttf") format("truetype");
  }
  body {
    margin: 0; min-height: 100vh;
    background-color: #f5f5f5;
    background-image: url('/static/brand/palms-grey.png');
    background-repeat: no-repeat; background-position: center bottom;
    background-size: cover; background-attachment: fixed;
    font-family: 'Teko', sans-serif;
  }
  /* Phone-only overrides (tablet/laptop/desktop untouched). The dashboards'
     sidebar+content shell is a fixed-width flex row with no wrap, which just
     squeezes on a phone instead of reflowing -- stack it, and let the fixed-
     width sidebar go full width. Banner crest/title get a touch smaller so
     the branded headers don't overflow a narrow box. */
  @media (max-width: 720px) {
    /* Filters/tabs first, profile+KPIs below -- opening a dashboard on a
       phone should show what to pick, not a face. */
    .paw-dash-row { flex-direction: column !important; align-items: stretch !important; }
    .paw-dash-sidebar { width: 100% !important; order: 2; }
    .paw-dash-content { order: 1; }
    .paw-banner-crest { height: 72px !important; }
    .paw-banner-title { font-size: 20px !important; letter-spacing: 4px !important; }
    /* Site header: let the user-info block drop to its own row instead of
       squeezing the wordmark into a mid-word wrap. */
    .paw-header { flex-wrap: wrap; height: auto !important; min-height: 64px;
                  row-gap: 4px; padding: 10px 14px !important; }
    .paw-header-user { width: 100%; text-align: right; font-size: 12px !important; }
    .paw-header-brand-text { font-size: 22px !important; }
    /* Video tab: clip above the pitch table instead of a forced side-by-side
       row that needs horizontal scrolling to see either one. */
    .paw-video-row { flex-direction: column !important; }
    .paw-video-media, .paw-video-table { min-width: 0 !important; width: 100%; }
  }
</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


def index_string() -> str:
    return _INDEX_STRING


def header(back_href: str | None = None, back_label: str | None = None) -> html.Div:
    """Site header (matches base.html): logo -> home, wordmark, optional back-link,
    user + logout."""
    brand_children = [
        html.Img(src="/static/reports/lmu.png",
                 style={"height": "40px", "width": "auto", "display": "block"}),
        html.Span("The Paw", className="paw-header-brand-text", style={
            "fontFamily": "Teko, sans-serif", "fontWeight": "700", "fontSize": "30px",
            "lineHeight": "1", "letterSpacing": "1px", "textTransform": "uppercase",
            "color": "#fff", "whiteSpace": "nowrap"}),
    ]
    brand = html.A(brand_children, href="/",
                   style={"display": "flex", "alignItems": "center", "gap": "12px",
                          "textDecoration": "none"})
    left = [brand]
    if back_href:
        left.append(html.A(back_label or "← Back", href=back_href, style={
            "color": "#fff", "textDecoration": "underline", "fontSize": "14px",
            "marginLeft": "18px"}))
    right = html.Span()
    if current_user.is_authenticated:
        # Change-password link is coach-only (the player login is shared).
        pw_link = ([html.A("Change password", href="/change-password",
                           style={"color": "#fff", "textDecoration": "underline"}),
                    " · "] if getattr(current_user, "is_coach", False) else [])
        right = html.Span([
            f"{current_user.name} · {current_user.role} · ",
            *pw_link,
            html.A("Log out", href="/logout",
                   style={"color": "#fff", "textDecoration": "underline"}),
        ], className="paw-header-user", style={"fontSize": "14px", "color": "rgba(255,255,255,.85)"})
    return html.Div([html.Div(left, style={"display": "flex", "alignItems": "center"}),
                     right], className="paw-header", style={
        "background": BANNER, "color": "#fff", "padding": "0 20px", "height": "64px",
        "display": "flex", "alignItems": "center", "justifyContent": "space-between",
        "boxShadow": "0 2px 8px rgba(0,0,0,.15)"})


def section(title: str) -> html.H3:
    return html.H3(title, style={"color": CRIMSON})


BLUE = "#0076A5"  # site brand blue (base.html --blue)


def _btn_style(bg: str) -> dict:
    return {"backgroundColor": bg, "color": "#fff", "border": "none",
            "borderRadius": "4px", "padding": "10px 26px", "fontWeight": "bold",
            "fontSize": "15px", "cursor": "pointer", "textTransform": "uppercase",
            "letterSpacing": "1px"}


def edit_save_buttons(edit_id: str, save_id: str, status_id: str,
                      extra: list | None = None) -> html.Div:
    """A centered row of coach controls: an "Edit" button (unlocks the grid),
    a "Save" button (persists + re-locks), any `extra` buttons, and a status
    line beneath. Shared by the velo board and cauldron so both read the same.
    The Edit/Save wiring (toggling the grid's `editable`) lives in each board's
    callbacks."""
    row = [
        html.Button("Edit", id=edit_id, n_clicks=0, style=_btn_style(BLUE)),
        html.Button("Save", id=save_id, n_clicks=0, style=_btn_style(CRIMSON)),
    ]
    if extra:
        row.extend(extra)
    return html.Div([
        html.Div(row, style={"display": "flex", "justifyContent": "center",
                             "gap": "12px", "flexWrap": "wrap"}),
        html.Div(id=status_id, style={"color": CRIMSON, "fontSize": "14px",
                                      "fontWeight": "bold", "marginTop": "8px"}),
    ], style={"padding": "14px 16px 20px", "textAlign": "center"})
