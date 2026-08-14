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
from dash import dash_table, html

from app.dashboards import shell

# LMU brand blue -- shell.py only defines the crimson/banner tokens (this
# board is the first thing in the Dash layer to need the blue half of the
# palette), so it's defined here rather than invented ad hoc per call site.
BLUE = "#2864A8"


# =============================== LMU VELO HEADER =============================
#
# A contained box backed by an opaque spray-paint square (velo-backdrop.png,
# replacing the old flat translucent-crimson box), holding the real LMU arch
# logo up top, the keyed-transparent Top Gun LIONS mark (whitespace-trimmed to
# its content bounds) centered beneath it, and a "VELO BOARD" marquee. The mark
# sits directly on the backdrop (its own negative space shows the backdrop
# through); the tagline uses "Alfa Slab One", the same beefy marquee font the
# home hero uses.

MARQUEE_FONT = "'Alfa Slab One', Georgia, serif"
_LMU_ARCH_SRC = "/static/reports/lmu.png"
_TOP_GUN_SRC = "/static/reports/top-gun-lions.png"  # keyed-transparent LIONS mark
# Opaque spray-paint square behind the crest (replaced the flat crimson box);
# `cover` fills the box, crimson fallback shows only if the image 404s.
_VELO_BACKDROP = "/static/reports/velo-backdrop.png"


def top_gun_header() -> html.Div:
    """The velo board's branded header: a contained crimson box with the LMU
    arch logo on top, the transparent Top Gun wings mark centered beneath, and
    a "VELO BOARD" marquee. Pure presentation -- no data dependency."""
    lmu_logo = html.Img(
        src=_LMU_ARCH_SRC, alt="LMU",
        # Identical to the cauldron header's LMU arch (same 104px size, cleanly
        # centered via auto side-margins).
        style={"display": "block", "margin": "0 auto", "height": "104px",
               "width": "auto"},
    )
    top_gun = html.Img(
        src=_TOP_GUN_SRC, alt="LIONS",
        # Negative top margin nests the LIONS mark up under LMU, overlapping the
        # transparent padding beneath the LMU arch to close the gap between them.
        style={"display": "block", "margin": "-48px auto 0", "width": "100%",
               "maxWidth": "500px", "height": "auto"},
    )
    subtitle = html.Div("VELO BOARD", style={
        "textAlign": "center", "color": "#ffffff", "fontFamily": MARQUEE_FONT,
        "fontSize": "34px", "letterSpacing": "10px", "marginTop": "-14px",
        "textTransform": "uppercase", "lineHeight": "1",
    })
    box = html.Div([lmu_logo, top_gun, subtitle], style={
        # Semi-transparent backdrop (alpha baked into the PNG) with NO opaque fill
        # behind it, so the page's palm background shows through the panel.
        "background": f"url({_VELO_BACKDROP}) center/cover no-repeat",
        "borderRadius": "10px", "textAlign": "center",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.18)", "padding": "18px 30px 20px",
        "maxWidth": "880px", "margin": "26px auto 10px",
    })
    return html.Div(box, style={"padding": "0 20px"})


# ============================ FORMATTING HELPERS ============================


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


# ===================== UNIFIED EDITABLE BOARD (DataTable) ====================
#
# One table for everyone: read-only heat leaderboard by default; a coach's Edit
# unlocks exactly the four editable columns IN PLACE (Season Max / Season Avg to
# correct bad readings, plus Velo Goal / Assessment), Save re-locks. Same heat
# gradient as `leaderboard_view`, ported to `style_data_conditional` by rank.

_EDITABLE_IDS = ("season_max", "season_avg", "velo_goal", "assessment")

# (label, id, type). Editable columns are numeric with NO per-column `editable`
# flag, so they inherit the table's `editable` (toggled by the Edit button); the
# rest are pinned read-only.
_BOARD_TABLE_COLUMNS = [
    ("Pitcher", "pitcher_name", "text"), ("Season Max", "season_max", "numeric"),
    ("Max Date", "season_max_date", "text"), ("Season Avg", "season_avg", "numeric"),
    ("Last Outing", "last_velo", "text"), ("Date", "last_date", "text"),
    ("Versus", "versus", "text"), ("Trend", "trend", "text"),
    ("Velo Goal", "velo_goal", "numeric"), ("Assessment", "assessment", "numeric"),
]

_DT_HEADER = {
    "backgroundColor": "#161616", "color": "#fff", "fontWeight": "bold",
    "textTransform": "uppercase", "letterSpacing": "1px", "border": "none",
    "borderBottom": f"2px solid {BLUE}",
}


def _trend_str(t) -> str:
    if _is_missing(t):
        return ""
    t = float(t)
    return f"{'▲' if t >= 0 else '▼'} {abs(t):.1f}"


def _num1(v):
    return None if _is_missing(v) else round(float(v), 1)


def _board_record(row) -> dict:
    """One board_rows row -> a DataTable record: editable velos/goal/assessment
    stay NUMERIC; read-only cells are pre-formatted strings; pitcher_id rides
    along (hidden from the columns) for save-mapping."""
    return {
        "pitcher_id": int(row["pitcher_id"]),
        "pitcher_name": _fmt_text(row["pitcher_name"]),
        "season_max": _num1(row["season_max"]),
        "season_max_date": _fmt_date(row["season_max_date"]),
        "season_avg": _num1(row["season_avg"]),
        "last_velo": _fmt_velo(row["last_velo"]),
        "last_date": _fmt_date(row["last_date"]),
        "versus": _fmt_text(row["versus"]),
        "trend": _trend_str(row["trend"]),
        "velo_goal": _num1(row["velo_goal"]),
        "assessment": _num1(row["assessment"]),
    }


def board_records(board_df: pd.DataFrame) -> list[dict]:
    """The DataTable `data` records for `board_df` (shared by `board_table` and
    the refresh callbacks so both format identically)."""
    df = (board_df if board_df is not None else pd.DataFrame()).reset_index(drop=True)
    return [_board_record(r) for _, r in df.iterrows()]


def board_table(board_df: pd.DataFrame) -> dash_table.DataTable:
    """The unified velo table (id `velo-grid`): read-only heat leaderboard that
    a coach edits in place. Always a DataTable (even empty) so the refresh /
    edit-toggle callbacks always find `velo-grid`."""
    df = (board_df if board_df is not None else pd.DataFrame()).reset_index(drop=True)
    total = len(df)
    data = board_records(df)

    columns = []
    for label, cid, ctype in _BOARD_TABLE_COLUMNS:
        col = {"name": label, "id": cid, "type": ctype}
        if cid not in _EDITABLE_IDS:
            col["editable"] = False           # pinned read-only
        columns.append(col)

    # Heat gradient by rank (row 0 = crimson -> last = blue), white text.
    heat = [{"if": {"row_index": i}, "backgroundColor": _row_color(i, total),
             "color": "#fff"} for i in range(total)]
    # Faint divider so a coach sees which columns are editable.
    edges = [{"if": {"column_id": cid}, "borderLeft": "1px solid rgba(255,255,255,0.28)"}
             for cid in _EDITABLE_IDS]

    return dash_table.DataTable(
        id="velo-grid",
        columns=columns,
        data=data,
        editable=False,
        style_table={"overflowX": "auto"},
        style_header=_DT_HEADER,
        style_cell={"fontFamily": "Teko, Arial, sans-serif", "fontSize": "17px",
                    "padding": "8px 12px", "textAlign": "center", "border": "none"},
        style_cell_conditional=[{"if": {"column_id": "pitcher_name"},
                                 "textAlign": "left", "fontWeight": "700"}],
        style_data_conditional=heat + edges,
    )
