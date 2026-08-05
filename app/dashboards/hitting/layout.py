"""The hitting dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import hitting_wh
from app.dashboards import date_range as dr, notes_ui
from app.dashboards.hitting import selectors
from app.dashboards.shell import (
    BANNER as _BANNER,
    CRIMSON as _CRIMSON,
    PHOTO_PLACEHOLDER as _PHOTO_PLACEHOLDER,
    header,
)


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold",
                               "color": _CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(batter_id) -> html.Div:
    if batter_id is None:
        return html.Div("Select a hitter.", style={"padding": "12px"})
    prof = hitting_wh.wh_player_profile(int(batter_id))
    qab = hitting_wh.wh_season_qab_rate(int(batter_id))
    qab_txt = f"{round(qab * 100, 1)}%" if qab is not None else "—"
    slash = hitting_wh.wh_slash_line(int(batter_id))
    photo = prof["photo"] or _PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Bats {prof['bats']}" if prof["bats"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("QAB%", qab_txt), _tile("BA", slash["BA"]),
                  _tile("SLG", slash["SLG"]), _tile("OBP", slash["OBP"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Slash line = warehouse game data (provisional).",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id, start=None, end=None, games_df=None) -> html.Div:
    if game_id == dr.ALL_IN_RANGE:
        return html.Div(dr.range_scoreboard_text(games_df, start, end),
                        style={"color": "white", "fontWeight": "bold",
                               "fontSize": "20px", "alignSelf": "center"})
    if not game_id:
        return html.Div()
    sb = hitting_wh.wh_scoreboard(int(game_id))
    parts = [p for p in (sb["date"], f"{sb['loc']} {sb['opp']}".strip(),
                         sb["game_type"]) if p]
    return html.Div(" · ".join(parts),
                    style={"color": "white", "fontWeight": "bold",
                           "fontSize": "20px", "alignSelf": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    hitters = selectors.hitter_options(is_coach=is_coach, own_trackman_id=own)
    default_batter = selectors.resolve_batter(
        hitters[0]["value"] if hitters else None,
        is_coach=is_coach, own_trackman_id=own)
    games_df = hitting_wh.wh_games_for_batter(default_batter) if default_batter else None
    if games_df is not None and not games_df.empty:
        min_bound = str(games_df["game_date"].min())
        max_bound = str(games_df["game_date"].max())
        games = dr.game_options(games_df)
        default_game = int(games_df.iloc[0]["game_id"])
        anchor = max_bound
        s0, e0 = dr.preset_range("season", anchor)
        # DEFAULT selected range only -- the calendar's own min/max stay the
        # batter's full history so Custom Range can reach out-of-season data.
        start_d = max(str(s0), min_bound)
        end_d = anchor
    else:
        min_bound = max_bound = None
        start_d = end_d = None
        games = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Hitter", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="hitter-dd", options=hitters, value=default_batter,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("hit", (end_d or date.today().isoformat()),
                            min_date=min_bound, max_date=max_bound, preset="season"),
        ]),
        html.Div([
            html.Label("Game", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="game-dd", options=games, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": _BANNER})

    tabs = dcc.Tabs(id="tabs", value="game", children=[
        dcc.Tab(label="Game Level", value="game"),
        dcc.Tab(label="Video", value="video"),
        dcc.Tab(label="Balls in Play", value="bip"),
        dcc.Tab(label="Last 27 PA", value="last27"),
        dcc.Tab(label="Dev Plan", value="devplan"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"batter_id": default_batter,
                                        "game_id": default_game,
                                        "start": start_d, "end": end_d}),
        dcc.Store(id="game-data"),
        header(back_href="/hitting", back_label="← Hitting"),
        html.Div([
            html.Div([
                html.Div(id="sidebar", children=sidebar(default_batter)),
                notes_ui.note_card("hitting"),
            ], style={"width": "260px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
