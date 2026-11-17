"""All Things Process dashboard shell: LMU banner, Season/Cycle/Game Type
filters, and the process leaderboard. Read-only for every logged-in user --
like the Velo Board, it's a team-transparent board, so there's no coach-only
section."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import process_board as PB
from app.data import seasons, velo_board
from app.dashboards import date_range as dr
from app.dashboards import shell
from app.dashboards.process_board import tables
from app.dashboards.velo_board.visual import MARQUEE_FONT

_LMU_ARCH_SRC = "/static/reports/lmu.png"
_BACKDROP = "/static/reports/velo-backdrop.png"

_LABEL_STYLE = {"color": shell.CRIMSON, "fontWeight": "bold", "fontSize": "13px",
                "textTransform": "uppercase", "letterSpacing": "1px",
                "display": "block", "marginBottom": "4px", "textAlign": "center"}


def process_header() -> html.Div:
    """Same contained-backdrop banner as the Velo Board (LMU arch on the
    spray-paint square, Alfa Slab marquee), titled for this board."""
    arch = html.Img(src=_LMU_ARCH_SRC, alt="LMU", className="paw-banner-crest",
                    style={"display": "block", "margin": "0 auto", "height": "104px",
                           "width": "auto"})
    title = html.Div("ALL THINGS PROCESS", className="paw-banner-title", style={
        "textAlign": "center", "color": "#ffffff", "fontFamily": MARQUEE_FONT,
        "fontSize": "40px", "letterSpacing": "6px", "marginTop": "16px",
        "lineHeight": "1.1",
    })
    subtitle = html.Div("Process Leaderboard", style={
        "textAlign": "center", "color": "#ffffff", "fontFamily": "Teko, Arial, sans-serif",
        "fontSize": "22px", "letterSpacing": "4px", "textTransform": "uppercase",
        "marginTop": "6px",
    })
    box = html.Div([arch, title, subtitle], style={
        "background": f"url({_BACKDROP}) center/cover no-repeat",
        "borderRadius": "10px", "textAlign": "center",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.18)", "padding": "18px 30px 22px",
        "maxWidth": "880px", "margin": "26px auto 10px",
    })
    return html.Div(box, style={"padding": "0 20px"})


DATE_PRESETS = [
    {"label": "Whole Cycle", "value": "cycle"},
    {"label": "Past Day", "value": "day"},
    {"label": "Past Week", "value": "week"},
    {"label": "Past Month", "value": "month"},
    {"label": "Custom Range", "value": "custom"},
]


def game_options(games_df) -> list[dict]:
    return [{"label": r.GameLabel, "value": r.game_id} for r in games_df.itertuples()]


def games_placeholder(games_df) -> str:
    return f"All {len(games_df)} games in range"


def filters(prefix: str, data, season: str, cycle: str) -> html.Div:
    """Season / Cycle / Game Type / Date / Games, shared by the pitcher and
    hitter boards (`data` is the board's app.data module; ids are
    f"{prefix}-season" etc.). Games starts empty = every game in range."""
    c_start, c_end = data.cycle_bounds(season, cycle)
    types = data.game_types(c_start, c_end)
    games_df = data.games(season, cycle)
    kinds = data.pitch_types(season, cycle)
    return html.Div([
        html.Div([
            html.Label("Season", style=_LABEL_STYLE),
            dcc.Dropdown(id=f"{prefix}-season",
                         options=[{"label": s, "value": s} for s in seasons.available_seasons()],
                         value=season, clearable=False, style={"minWidth": "150px"}),
        ]),
        html.Div([
            html.Label("Cycle", style=_LABEL_STYLE),
            dcc.Dropdown(id=f"{prefix}-cycle",
                         options=[{"label": c, "value": c} for c in data.CYCLES],
                         value=cycle, clearable=False, style={"minWidth": "130px"}),
        ]),
        html.Div([
            html.Label("Game Type", style=_LABEL_STYLE),
            dcc.Dropdown(id=f"{prefix}-game-types",
                         options=[{"label": t, "value": t} for t in types],
                         value=types, multi=True, placeholder="All game types",
                         style={"minWidth": "260px"}),
        ]),
        html.Div([
            html.Label("Dates", style=_LABEL_STYLE),
            dr.date_control(prefix, c_end, min_date=c_start, max_date=c_end, preset="cycle",
                            options=DATE_PRESETS),
        ]),
        html.Div([
            html.Label("Games", style=_LABEL_STYLE),
            dcc.Dropdown(id=f"{prefix}-games", options=game_options(games_df), value=[],
                         multi=True, placeholder=games_placeholder(games_df),
                         style={"minWidth": "320px", "maxWidth": "520px"}),
        ]),
        html.Div([
            html.Label(data.HAND_LABEL, style=_LABEL_STYLE),
            dcc.Dropdown(id=f"{prefix}-hand",
                         options=[{"label": lbl, "value": v} for v, lbl in data.HAND_OPTIONS],
                         value="all", clearable=False, style={"minWidth": "150px"}),
        ]),
        html.Div([
            html.Label("Pitch Type", style=_LABEL_STYLE),
            dcc.Dropdown(id=f"{prefix}-pitch-types",
                         options=[{"label": k, "value": k} for k in kinds], value=[],
                         multi=True, placeholder="All pitch types",
                         style={"minWidth": "220px", "maxWidth": "420px"}),
        ]),
    ], style={"display": "flex", "gap": "28px", "justifyContent": "center",
              "alignItems": "flex-start", "flexWrap": "wrap", "padding": "12px 16px"})


def _swatch(color: str, label: str) -> html.Span:
    return html.Span([
        html.Span(style={"display": "inline-block", "width": "14px", "height": "14px",
                         "backgroundColor": color, "border": "1px solid #bbb",
                         "verticalAlign": "middle", "marginRight": "6px"}),
        label,
    ], style={"marginRight": "18px", "whiteSpace": "nowrap"})


def legend() -> html.Div:
    return html.Div([
        _swatch(tables.LEADER, "Team leader"),
        _swatch(tables.MEETS, "Meets LMU Baseline"),
        _swatch(tables.MISSES, "Below LMU Baseline"),
        html.Span("Lower is better for Barrel% and BB%. Click a column header to sort.",
                  style={"color": "#555"}),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px", "fontSize": "14px",
              "padding": "8px 20px", "justifyContent": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    season = seasons.season_label_for(date.today().isoformat())
    cycle = velo_board.velo_cycle_for_date(date.today())
    board = PB.board(season, cycle)
    return html.Div([
        shell.header(back_href="/pitching", back_label="← Pitching"),
        process_header(),
        html.Div(filters("process", PB, season, cycle),
                 style={"borderBottom": f"2px solid {shell.CRIMSON}",
                        "backgroundColor": "rgba(255,255,255,0.55)"}),
        legend(),
        html.Div(tables.process_table(board), id="process-board",
                 style={"padding": "0 20px 30px"}),
    ])
