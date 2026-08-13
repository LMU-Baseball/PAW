"""Top Gun Velo Board — player-facing visual: LMU-recolored Top Gun header +
ranked heat leaderboard.

Two pieces, both pure functions of data (no callbacks, no state):

- `top_gun_header()`: the branded banner. Built as a single inline SVG (wings
  fanning out from a bold "TOP GUN" wordmark, a star beneath) embedded via a
  `data:image/svg+xml` URI on an `html.Img` -- no extra dependency (no
  `dash_svg`), and no dash `dangerously_allow_html` escape hatch needed. The
  wordmark also lives in the `alt` text so it's present in the component tree
  even before the browser decodes the image (accessibility bonus, and what
  lets a plain `str(component)` assertion find "TOP GUN").
- `leaderboard_view(lb_df)`: an `html.Table` ranked by `season_max` (desc,
  matching `velo_board.leaderboard`'s own sort -- re-sorted here too so the
  view is correct even if a caller hands in an unsorted frame), with each
  row's background interpolated along a crimson (rank 0, hardest throwers) ->
  blue (last rank, softest) heat gradient.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from dash import html

from app.dashboards import shell

# LMU brand blue -- shell.py only defines the crimson/banner tokens (this
# board is the first thing in the Dash layer to need the blue half of the
# palette), so it's defined here rather than invented ad hoc per call site.
BLUE = "#2864A8"

_UP_COLOR = "#3ad16f"    # trend improved since last outing
_DOWN_COLOR = "#ff5c5c"  # trend dropped since last outing


# =============================== LMU VELO HEADER =============================
#
# A contained translucent-crimson box (mirroring the home page's `.home-hero`:
# rgba crimson, rounded corners, palms showing through), holding the real LMU
# arch logo up top, the Top Gun wings mark (transparent PNG, whitespace-trimmed
# to its content bounds) centered beneath it, and a "VELO BOARD" marquee. The
# logo sits directly on the crimson box (no white plate) per the coach's ask;
# the tagline uses "Alfa Slab One", the same beefy marquee font the home hero
# uses.

BANNER_BOX = "rgba(154, 0, 33, 0.82)"   # == base.html --banner (home-hero box)
MARQUEE_FONT = "'Alfa Slab One', Georgia, serif"
_LMU_ARCH_SRC = "/static/reports/lmu.png"
_TOP_GUN_SRC = "/static/reports/top-gun-logo-trim.png"  # alpha-trimmed, no padding


def top_gun_header() -> html.Div:
    """The velo board's branded header: a contained crimson box with the LMU
    arch logo on top, the transparent Top Gun wings mark centered beneath, and
    a "VELO BOARD" marquee. Pure presentation -- no data dependency."""
    lmu_logo = html.Img(
        src=_LMU_ARCH_SRC, alt="LMU",
        style={"display": "block", "margin": "0 auto 18px", "height": "72px",
               "width": "auto"},
    )
    top_gun = html.Img(
        src=_TOP_GUN_SRC, alt="TOP GUN",
        style={"display": "block", "margin": "0 auto", "width": "100%",
               "maxWidth": "480px", "height": "auto"},
    )
    subtitle = html.Div("VELO BOARD", style={
        "textAlign": "center", "color": "#ffffff", "fontFamily": MARQUEE_FONT,
        "fontSize": "34px", "letterSpacing": "10px", "marginTop": "18px",
        "textTransform": "uppercase", "lineHeight": "1",
    })
    box = html.Div([lmu_logo, top_gun, subtitle], style={
        "background": BANNER_BOX, "borderRadius": "10px", "textAlign": "center",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.18)", "padding": "24px 30px 22px",
        "maxWidth": "900px", "margin": "26px auto 10px",
    })
    return html.Div(box, style={"padding": "0 20px"})


# ============================== HEAT LEADERBOARD =============================

_COLUMNS = ["Pitcher", "Season Max", "Max Date", "Season Avg",
            "Last Outing", "Date", "Versus", "Trend"]

_HEADER_CELL_STYLE = {
    "padding": "10px 14px", "textAlign": "center", "backgroundColor": "#161616",
    "color": "#fff", "textTransform": "uppercase", "letterSpacing": "1px",
    "fontSize": "15px", "borderBottom": f"2px solid {BLUE}",
}
_CELL_STYLE = {
    "padding": "8px 14px", "textAlign": "center",
    "borderBottom": "1px solid rgba(255,255,255,0.15)",
}
_CELL_STYLE_LEFT = {**_CELL_STYLE, "textAlign": "left", "fontWeight": "700"}


def _is_missing(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _fmt_velo(v) -> str:
    return "—" if _is_missing(v) else f"{float(v):.1f}"


def _fmt_date(d) -> str:
    if _is_missing(d):
        return "—"
    try:
        dt = datetime.strptime(str(d)[:10], "%Y-%m-%d")
    except ValueError:
        return "—"
    return f"{dt.month}/{dt.day}"


def _fmt_text(v) -> str:
    return "—" if _is_missing(v) else str(v)


def _trend_cell(t) -> html.Span:
    if _is_missing(t):
        return html.Span("")
    t = float(t)
    up = t >= 0
    arrow = "▲" if up else "▼"
    color = _UP_COLOR if up else _DOWN_COLOR
    return html.Span(f"{arrow} {abs(t):.1f}", style={"color": color, "fontWeight": "700"})


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _row_color(rank: int, total: int) -> str:
    """Crimson (rank 0) -> blue (last rank) heat gradient, linear in RGB."""
    t = 0.0 if total <= 1 else rank / (total - 1)
    r1, g1, b1 = _hex_to_rgb(shell.CRIMSON)
    r2, g2, b2 = _hex_to_rgb(BLUE)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"rgb({r},{g},{b})"


def leaderboard_view(lb_df: pd.DataFrame) -> html.Div:
    """Ranked heat-gradient table matching `velo_board.leaderboard`'s
    columns. Gracefully renders a placeholder message for an empty frame."""
    if lb_df is None or lb_df.empty:
        return html.Div("No pitchers on the board yet.", style={
            "color": "#fff", "background": shell.BANNER, "padding": "18px",
            "textAlign": "center", "fontFamily": "Teko, sans-serif", "fontSize": "20px",
        })

    df = lb_df.sort_values(
        "season_max", ascending=False, na_position="last", kind="mergesort"
    ).reset_index(drop=True)
    total = len(df)

    header_row = html.Tr([html.Th(col, style=_HEADER_CELL_STYLE) for col in _COLUMNS])

    body_rows = []
    for rank, row in df.iterrows():
        cells = [
            html.Td(_fmt_text(row["pitcher_name"]), style=_CELL_STYLE_LEFT),
            html.Td(_fmt_velo(row["season_max"]), style=_CELL_STYLE),
            html.Td(_fmt_date(row["season_max_date"]), style=_CELL_STYLE),
            html.Td(_fmt_velo(row["season_avg"]), style=_CELL_STYLE),
            html.Td(_fmt_velo(row["last_velo"]), style=_CELL_STYLE),
            html.Td(_fmt_date(row["last_date"]), style=_CELL_STYLE),
            html.Td(_fmt_text(row["versus"]), style=_CELL_STYLE),
            html.Td(_trend_cell(row["trend"]), style=_CELL_STYLE),
        ]
        body_rows.append(html.Tr(cells, style={
            "backgroundColor": _row_color(rank, total), "color": "#fff",
        }))

    table = html.Table([html.Thead(header_row), html.Tbody(body_rows)], style={
        "width": "100%", "borderCollapse": "collapse",
        "fontFamily": "Teko, Arial, sans-serif", "fontSize": "18px", "color": "#fff",
    })
    return html.Div(table, style={"padding": "12px", "overflowX": "auto"})
