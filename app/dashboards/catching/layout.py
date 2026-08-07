"""The catching dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import catching_caps
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui
from app.dashboards.shell import BANNER, CRIMSON, PHOTO_PLACEHOLDER, header
from app.dashboards.catching import selectors


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(catcher_id) -> html.Div:
    if catcher_id is None:
        return html.Div("Select a catcher.", style={"padding": "12px"})
    prof = catching_caps.catcher_profile(int(catcher_id))
    summ = catching_caps.framing_season_tiles(int(catcher_id))
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"]) if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("GAMES", summ["games"]), _tile("PITCHES", summ["pitches"]),
                  _tile("NET STRIKES", summ["net_strikes"]),
                  _tile("STEAL%", summ["steal_pct"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Season framing tiles (provisional stolen/lost model).",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id, start=None, end=None, games_df=None) -> html.Div:
    if game_id == dr.ALL_IN_RANGE:
        return html.Div(dr.range_scoreboard_text(games_df, start, end),
                        style={"color": "white", "fontWeight": "bold",
                               "fontSize": "20px", "alignSelf": "center"})
    if not game_id:
        return html.Div()
    try:
        ctx = catching_caps.game_context(int(game_id))
    except Exception:
        return html.Div()
    opp = ctx["away_team"] if ctx["lmu_is_home"] else ctx["home_team"]
    loc = "vs" if ctx["lmu_is_home"] else "@"
    parts = [str(ctx["game_date"]), f"{loc} {opp}", ctx.get("game_type") or ""]
    return html.Div(" · ".join(p for p in parts if p),
                    style={"color": "white", "fontWeight": "bold",
                           "fontSize": "20px", "alignSelf": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    catchers = selectors.catcher_options(is_coach=is_coach, own_trackman_id=own)
    default_catcher = selectors.resolve_catcher(
        catchers[0]["value"] if catchers else None,
        is_coach=is_coach, own_trackman_id=own)
    games_df = catching_caps.games_for_catcher(default_catcher) if default_catcher else None
    if games_df is not None and not games_df.empty:
        min_bound = str(games_df["game_date"].min())
        max_bound = str(games_df["game_date"].max())
        games = dr.game_options(
            games_df, videodata.video_game_ids(games_df, catcher_id=default_catcher))
        default_game = int(games_df.iloc[0]["game_id"])
        anchor = max_bound
        s0, e0 = dr.preset_range("season", anchor)
        # DEFAULT selected range only -- the calendar's own min/max stay the
        # catcher's full history so Custom Range can reach out-of-season data.
        start_d = max(str(s0), min_bound)
        end_d = anchor
    else:
        min_bound = max_bound = None
        start_d = end_d = None
        games = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Catcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="catcher-dd", options=catchers, value=default_catcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("cat", (end_d or date.today().isoformat()),
                            min_date=min_bound, max_date=max_bound, preset="season"),
        ]),
        html.Div([
            html.Label("Game", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="game-dd", options=games, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": BANNER})

    tabs = dcc.Tabs(id="tabs", value="framing", children=[
        dcc.Tab(label="Overall Framing", value="framing"),
        dcc.Tab(label="Static Framing", value="static"),
        dcc.Tab(label="Caught Stealing", value="caught"),
        dcc.Tab(label="Outing Video", value="pitchlevel"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"catcher_id": default_catcher,
                                        "game_id": default_game,
                                        "start": start_d, "end": end_d}),
        dcc.Store(id="game-data"),
        header(back_href="/catching", back_label="← Catching"),
        html.Div([
            html.Div([
                html.Div(id="sidebar", children=sidebar(default_catcher)),
                notes_ui.note_card("catching"),
            ], style={"width": "260px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
