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
  body {
    margin: 0; min-height: 100vh;
    background-color: #f5f5f5;
    background-image: url('/static/brand/palms-grey.png');
    background-repeat: no-repeat; background-position: center bottom;
    background-size: cover; background-attachment: fixed;
    font-family: 'Teko', sans-serif;
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
        html.Span("The Paw", style={
            "fontFamily": "Teko, sans-serif", "fontWeight": "700", "fontSize": "30px",
            "lineHeight": "1", "letterSpacing": "1px", "textTransform": "uppercase",
            "color": "#fff"}),
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
        right = html.Span([
            f"{current_user.name} · {current_user.role} · ",
            html.A("Log out", href="/logout",
                   style={"color": "#fff", "textDecoration": "underline"}),
        ], style={"fontSize": "14px", "color": "rgba(255,255,255,.85)"})
    return html.Div([html.Div(left, style={"display": "flex", "alignItems": "center"}),
                     right], style={
        "background": BANNER, "color": "#fff", "padding": "0 20px", "height": "64px",
        "display": "flex", "alignItems": "center", "justifyContent": "space-between",
        "boxShadow": "0 2px 8px rgba(0,0,0,.15)"})


def section(title: str) -> html.H3:
    return html.H3(title, style={"color": CRIMSON})
