"""Competitive Cauldron -- player-facing visual: LMU-branded header + the
team scoreboard.

Two pieces, both pure functions of data (no callbacks, no state), mirroring
`app.dashboards.velo_board.visual`'s shapes:

- `cauldron_header()`: the branded banner. Built as a single inline SVG (a
  cauldron/flame motif in crimson + blue flanking a bold "COMPETITIVE
  CAULDRON" wordmark) embedded via a `data:image/svg+xml` URI on an
  `html.Img` -- no extra dependency, no dash `dangerously_allow_html` escape
  hatch. The wordmark also lives in the `alt` text so it's present in the
  component tree even before the browser decodes the image (accessibility
  bonus, and what lets a plain `str(component)` assertion find it).
- `scoreboard_view(daily_df, teams_df, scoring_df, roster_names)`: an
  `html.Table` grouped by team -- a team header row, that team's player rows
  (points pivoted player x metric, columns ordered by `scoring_df.sort_order`),
  and a team-total row -- with each point cell colored green (met/positive),
  red (missed/negative), or neutral (no data yet).
"""
from __future__ import annotations

import base64
import os

import pandas as pd
from dash import html

from app.dashboards import shell

# LMU brand tokens. shell.py's CRIMSON (#9A0021) is the site's primary
# banner crimson; the brief also calls out the deeper #8C1D40 crimson and
# the blue #2864A8 the velo board introduced -- neither lives in shell.py
# yet, so (like velo_board) they're defined here rather than invented ad hoc
# per call site.
CRIMSON = shell.CRIMSON
CRIMSON_DEEP = "#8C1D40"
BLUE = "#2864A8"

_MET_COLOR = "#3ad16f"     # background tint's foreground text -- positive/met
_MISSED_COLOR = "#ff5c5c"  # negative/missed
_MET_BG = "rgba(58,209,111,0.18)"
_MISSED_BG = "rgba(255,92,92,0.18)"

_UNASSIGNED_TEAM = "Unassigned"


# ============================ CAULDRON HEADER =================================
#
# A contained box backed by an opaque crimson-with-blue-palms square
# (cauldron-backdrop.png, the coach's throwback beach feel; replaced the old
# crimson->blue gradient wash). Crest: the LMU arch logo top-center, then a big
# "COMPETITIVE Cauldron" wordmark set on an UPWARD-bowing arc that nests into
# the arch's underbelly, over a "COMPETE EVERYDAY" tagline. "COMPETITIVE" is
# white in Alfa Slab One; "Cauldron" is blue in a skinny cursive script. The
# curved wordmark is a single inline SVG embedded via a `data:` URI on an
# `html.Img`; because an <img>-embedded SVG can't reach system or page fonts,
# both fonts are base64-embedded INSIDE the SVG (read from `app/static/brand/`),
# which keeps the mark self-contained and pixel-identical everywhere.
# "COMPETITIVE CAULDRON" also lives in the img `alt` text so it's in the
# component tree for accessibility + `str()` assertions.

# Opaque crimson-with-blue-palms square behind the crest (replaced the old
# blue->crimson gradient wash); `cover` fills the box, crimson fallback shows
# only if the image 404s.
_CAULDRON_BACKDROP = "/static/reports/cauldron-backdrop.png"
_WORD_BLUE = "#5B9BD5"                    # light blue that reads on the backdrop
_LMU_ARCH_SRC = "/static/reports/lmu.png"

_BRAND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static", "brand")
_ALFA_TTF = os.path.join(_BRAND_DIR, "AlfaSlabOne-Regular.ttf")
_SCRIPT_TTF = os.path.join(_BRAND_DIR, "CauldronScript.ttf")  # Kaushan Script (OFL) -- embeddable/redistributable; swap w/ any script TTF


def _font_face(family: str, ttf_path: str) -> str:
    """An @font-face rule with the TTF base64-embedded as a data: URI, so the
    font travels inside the SVG (an <img>-embedded SVG can't load external
    font files or use system fonts)."""
    with open(ttf_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return (f"@font-face{{font-family:'{family}';"
            f"src:url(data:font/ttf;base64,{b64}) format('truetype');}}")


def _wordmark_svg() -> str:
    """"COMPETITIVE" (white, Alfa Slab One) + "Cauldron" (blue, skinny script)
    set on an UPWARD-bowing arc (peak in the middle) so the wordmark nests into
    the LMU arch's underbelly above it. The chord (~900px) is sized well wider
    than the rendered text (~710px at these sizes) so no glyph runs off the path
    ends and gets clipped -- SVG drops any character that falls past a textPath."""
    w, h = 1040, 250
    # Upward bow: endpoints low, control point high-center (peak in the middle).
    # Deepened bow (peak raised from y=92 to y=60) for a more pronounced smile.
    arc = "M 70,190 Q 520,60 970,190"
    faces = _font_face("CauldronAlfa", _ALFA_TTF) + _font_face("CauldronScript", _SCRIPT_TTF)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <style>{faces}</style>
    <path id="arc" d="{arc}" fill="none"/>
  </defs>
  <text text-anchor="middle">
    <textPath href="#arc" startOffset="50%">
      <tspan font-family="CauldronAlfa" font-size="60" letter-spacing="1" fill="#ffffff">COMPETITIVE </tspan><tspan font-family="CauldronScript" font-size="84" fill="{_WORD_BLUE}">Cauldron</tspan>
    </textPath>
  </text>
</svg>'''


def cauldron_header() -> html.Div:
    """The branded header crest: LMU arch top-center, then a big "COMPETITIVE
    Cauldron" wordmark on an upward-bowing arc nesting into the arch's
    underbelly, all on an opaque crimson-with-blue-palms backdrop (anchored to
    the bottom so the palms show). Pure presentation -- no data dependency."""
    arch = html.Img(src=_LMU_ARCH_SRC, alt="LMU", className="paw-banner-crest", style={
        "display": "block", "margin": "0 auto", "height": "104px", "width": "auto",
    })
    wordmark = html.Img(
        src="data:image/svg+xml;base64," + base64.b64encode(
            _wordmark_svg().encode("utf-8")).decode("ascii"),
        alt="COMPETITIVE CAULDRON",
        style={"display": "block", "margin": "-24px auto 0", "width": "100%",
               "maxWidth": "760px", "height": "auto"},
    )
    box = html.Div([arch, wordmark], style={
        # `center bottom` anchors the crop to the bottom of the square backdrop
        # so its palm trees stay in view in this wide, short box. Semi-transparent
        # backdrop (alpha in the PNG) with NO opaque fill behind it, so the page's
        # palm background shows through the panel.
        "background": f"url({_CAULDRON_BACKDROP}) center bottom/cover no-repeat",
        "borderRadius": "10px",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.18)", "padding": "18px 30px 22px",
        "maxWidth": "880px", "margin": "26px auto 10px",
    })
    return html.Div(box, style={"padding": "0 20px"})


# =============================== SCOREBOARD ====================================

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
_TOTAL_CELL_STYLE = {**_CELL_STYLE, "fontWeight": "700", "borderLeft": f"2px solid {BLUE}"}
_TEAM_HEADER_STYLE = {
    "padding": "10px 14px", "textAlign": "left", "backgroundColor": CRIMSON_DEEP,
    "color": "#fff", "fontWeight": "700", "fontSize": "20px",
    "textTransform": "uppercase", "letterSpacing": "1px",
}
_TEAM_TOTAL_ROW_STYLE = {"backgroundColor": "rgba(40,100,168,0.35)", "color": "#fff"}
_PLAYER_ROW_STYLE = {"backgroundColor": "rgba(255,255,255,0.04)", "color": "#fff"}


def _is_missing(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _fmt_points(v) -> str:
    if _is_missing(v):
        return "—"
    v = int(v)
    return f"+{v}" if v > 0 else str(v)


def _points_cell_style(v) -> dict:
    if _is_missing(v) or v == 0:
        return _CELL_STYLE
    if v > 0:
        return {**_CELL_STYLE, "backgroundColor": _MET_BG, "color": _MET_COLOR, "fontWeight": "700"}
    return {**_CELL_STYLE, "backgroundColor": _MISSED_BG, "color": _MISSED_COLOR, "fontWeight": "700"}


def _display_name(player_id, roster_names) -> str:
    if roster_names:
        name = roster_names.get(player_id) or roster_names.get(int(player_id))
        if name:
            return str(name)
    return str(player_id)


def scoreboard_view(daily_df: pd.DataFrame, teams_df: pd.DataFrame,
                     scoring_df: pd.DataFrame, roster_names: dict | None = None) -> html.Div:
    """Team-grouped scoreboard: player rows (points pivoted player x metric,
    columns ordered by `scoring_df.sort_order`) under each team's header row,
    followed by a team-total row. Gracefully renders a placeholder message
    when there's no roster/scoring config to build the table from."""
    if (teams_df is None or teams_df.empty
            or scoring_df is None or scoring_df.empty):
        return html.Div("No data yet -- assign teams and configure scoring to light the Cauldron.", style={
            "color": "#fff", "background": shell.BANNER, "padding": "18px",
            "textAlign": "center", "fontFamily": "Teko, sans-serif", "fontSize": "20px",
        })

    scoring = scoring_df.sort_values("sort_order", kind="mergesort").reset_index(drop=True)
    metrics = list(scoring["metric"])
    labels = {row["metric"]: row["label"] for _, row in scoring.iterrows()}

    daily = daily_df if daily_df is not None else pd.DataFrame(
        columns=["player_id", "play_date", "metric", "points", "source"])
    points_by_player_metric: dict[tuple[int, str], int] = {}
    if not daily.empty:
        summed = daily.groupby(["player_id", "metric"])["points"].sum()
        for (pid, metric), pts in summed.items():
            points_by_player_metric[(int(pid), metric)] = pts

    teams = teams_df.copy()
    teams["player_id"] = teams["player_id"].astype(int)
    team_by_player = dict(zip(teams["player_id"], teams["team"]))

    # Team captains float to the top of their team and render with a ★.
    if "is_captain" in teams.columns:
        captain_ids = set(teams.loc[
            teams["is_captain"].fillna(0).astype(int) == 1, "player_id"].astype(int))
    else:
        captain_ids = set()

    # Players present in the daily results but not rostered onto any team
    # this cycle fall under an "Unassigned" group (rather than being
    # silently dropped) so a coach notices a missing roster assignment.
    all_player_ids = set(team_by_player.keys())
    if not daily.empty:
        all_player_ids |= set(daily["player_id"].astype(int))

    players_by_team: dict[str, list[int]] = {}
    for pid in all_player_ids:
        team = team_by_player.get(pid, _UNASSIGNED_TEAM)
        players_by_team.setdefault(team, []).append(pid)

    def _player_total(pid: int) -> int:
        return sum(points_by_player_metric.get((pid, m), 0) for m in metrics)

    team_names = sorted(t for t in players_by_team if t != _UNASSIGNED_TEAM)
    if _UNASSIGNED_TEAM in players_by_team:
        team_names.append(_UNASSIGNED_TEAM)

    header_cells = ([html.Th("Player", style={**_HEADER_CELL_STYLE, "textAlign": "left"})]
                     + [html.Th(labels[m], style=_HEADER_CELL_STYLE) for m in metrics]
                     + [html.Th("Total", style=_HEADER_CELL_STYLE)])
    header_row = html.Tr(header_cells)

    n_cols = len(metrics) + 2
    body_rows = []
    for team in team_names:
        body_rows.append(html.Tr(
            html.Td(team, colSpan=n_cols, style=_TEAM_HEADER_STYLE)
        ))

        # Captain first (0 sorts before 1), then by points desc, then name.
        pids = sorted(players_by_team[team],
                      key=lambda p: (0 if p in captain_ids else 1,
                                     -_player_total(p), _display_name(p, roster_names)))
        team_total = 0
        for pid in pids:
            total = _player_total(pid)
            team_total += total
            name = _display_name(pid, roster_names)
            if pid in captain_ids:
                name = f"★ {name}"
            cells = [html.Td(name, style=_CELL_STYLE_LEFT)]
            for m in metrics:
                pts = points_by_player_metric.get((pid, m))
                cells.append(html.Td(_fmt_points(pts), style=_points_cell_style(pts)))
            cells.append(html.Td(_fmt_points(total), style=_TOTAL_CELL_STYLE))
            body_rows.append(html.Tr(cells, style=_PLAYER_ROW_STYLE))

        total_cells = ([html.Td(f"{team} Total", style={**_CELL_STYLE_LEFT, "fontWeight": "700"})]
                       + [html.Td("", style=_CELL_STYLE) for _ in metrics]
                       + [html.Td(_fmt_points(team_total), style={**_TOTAL_CELL_STYLE, "fontSize": "18px"})])
        body_rows.append(html.Tr(total_cells, style=_TEAM_TOTAL_ROW_STYLE))

    table = html.Table([html.Thead(header_row), html.Tbody(body_rows)], style={
        "width": "100%", "borderCollapse": "collapse",
        "fontFamily": "Teko, Arial, sans-serif", "fontSize": "18px", "color": "#fff",
    })
    # Solid dark background: the table's text is white, so on the site's light
    # page the neutral values/names were white-on-white -- the dark ground fixes
    # readability while green/red point tints keep their meaning.
    return html.Div(table, style={"padding": "12px", "overflowX": "auto",
                                   "backgroundColor": "#161616", "borderRadius": "8px"})
