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
# A contained translucent-crimson box (mirroring the home page's `.home-hero`
# and the velo board's header), holding a strip of LMU logos -- the white
# transparent sun-lion flanked by two LMU arch marks -- above a spiced-up,
# two-tone "COMPETITIVE CAULDRON" marquee in "Alfa Slab One" (the home hero's
# font). The white lion (`lion-white.png`) has a transparent background so it
# sits cleanly on the crimson box -- no white halo.

BANNER_BOX = "rgba(154, 0, 33, 0.82)"   # == base.html --banner (home-hero box)
MARQUEE_FONT = "'Alfa Slab One', Georgia, serif"
_WORD_BLUE = "#5B9BD5"                    # light blue that reads on the crimson box
_LION_WHITE_SRC = "/static/reports/lion-white.png"
_LMU_ARCH_SRC = "/static/reports/lmu.png"


def cauldron_header() -> html.Div:
    """The branded header: a contained crimson box with a strip of LMU logos
    (white sun-lion flanked by LMU arch marks) above a two-tone "COMPETITIVE
    CAULDRON" marquee + "DAILY TEAM COMPETITION" subtitle. Pure presentation
    -- no data dependency."""
    def _arch():
        return html.Img(src=_LMU_ARCH_SRC, alt="LMU",
                        style={"height": "44px", "width": "auto"})

    logos = html.Div([
        _arch(),
        html.Img(src=_LION_WHITE_SRC, alt="LMU lion",
                 style={"height": "84px", "width": "auto"}),
        _arch(),
    ], style={"display": "flex", "justifyContent": "center", "alignItems": "center",
              "gap": "26px", "flexWrap": "wrap", "marginBottom": "6px"})

    wordmark = html.Div([
        html.Span("COMPETITIVE ", style={"color": "#ffffff"}),
        html.Span("CAULDRON", style={"color": _WORD_BLUE}),
    ], style={
        "textAlign": "center", "fontFamily": MARQUEE_FONT, "fontSize": "46px",
        "letterSpacing": "2px", "lineHeight": "1", "textTransform": "uppercase",
    })
    subtitle = html.Div("DAILY TEAM COMPETITION", style={
        "textAlign": "center", "color": "rgba(255,255,255,0.9)",
        "fontFamily": "Teko, Arial, sans-serif", "fontWeight": "700",
        "fontSize": "24px", "letterSpacing": "10px", "marginTop": "6px",
        "textTransform": "uppercase",
    })
    box = html.Div([logos, wordmark, subtitle], style={
        "background": BANNER_BOX, "borderRadius": "10px",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.18)", "padding": "22px 30px 20px",
        "maxWidth": "900px", "margin": "26px auto 10px",
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

        pids = sorted(players_by_team[team],
                      key=lambda p: (-_player_total(p), _display_name(p, roster_names)))
        team_total = 0
        for pid in pids:
            total = _player_total(pid)
            team_total += total
            cells = [html.Td(_display_name(pid, roster_names), style=_CELL_STYLE_LEFT)]
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
    return html.Div(table, style={"padding": "12px", "overflowX": "auto"})
