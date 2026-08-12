"""The catching dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import catching_caps, seasons
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


def sidebar(catcher_id, season=None, start=None, end=None) -> html.Div:
    if catcher_id is None:
        return html.Div("Select a catcher.", style={"padding": "12px"})
    prof = catching_caps.catcher_profile(int(catcher_id))
    summ = catching_caps.framing_season_tiles(int(catcher_id), season, start, end)
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
        html.Div([_tile("GAMES", summ["games"]), _tile("STRIKES", summ["strikes"]),
                  _tile("STRIKES LOST", summ["strikes_lost"]),
                  _tile("STEAL%", summ["cs_pct"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Stats reflect the selected date range.",
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
        ctx = catching_caps.game_context(str(game_id))
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
    season = seasons.current_season()
    s_bound, e_bound = seasons.season_bounds(season)
    catchers_all = selectors.catcher_options(is_coach=is_coach, own_trackman_id=own,
                                             season=season)
    default_catcher = selectors.resolve_catcher(
        catchers_all[0]["value"] if catchers_all else None,
        is_coach=is_coach, own_trackman_id=own)
    # Season is the OUTER scope; the date range + calendar nest inside the
    # selected academic year (Aug 1 -> Jul 31). Default range = the whole season.
    min_bound, max_bound = s_bound, e_bound
    start_d, end_d = s_bound, e_bound

    # First-paint options scoped to that same season-default range (mirrors
    # the _on_daterange_catchers callback) -- not every catcher in the season.
    # Fallback mirrors _on_daterange_catchers exactly: if the unscoped default
    # isn't in the range-scoped options, fall back to the first available
    # option's value (or None) -- NOT resolve_catcher(), which would force a
    # player-role user back to their own id even when it's not among `catchers`.
    catchers = selectors.catcher_options(is_coach=is_coach, own_trackman_id=own,
                                         season=season, start=start_d, end=end_d)
    catcher_values = {c["value"] for c in catchers}
    if default_catcher not in catcher_values:
        default_catcher = catchers[0]["value"] if catchers else None

    games_df = (catching_caps.games_for_catcher(default_catcher, s_bound, e_bound)
                if default_catcher else None)
    if games_df is not None and not games_df.empty:
        games = dr.game_options(
            games_df, videodata.video_game_ids(games_df, catcher_id=default_catcher))
        default_game = str(games_df.iloc[0]["game_id"])
    else:
        games = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Season", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="cat-season",
                         options=[{"label": s, "value": s}
                                  for s in seasons.available_seasons()],
                         value=season, clearable=False,
                         style={"minWidth": "130px"}),
        ]),
        html.Div([
            html.Label("Catcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="catcher-dd", options=catchers, value=default_catcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("cat", (end_d or date.today().isoformat()),
                            min_date=min_bound, max_date=max_bound, preset="season",
                            start=start_d, end=end_d),
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
                                        "season": season,
                                        "start": start_d, "end": end_d}),
        dcc.Store(id="game-data"),
        header(back_href="/catching", back_label="← Catching"),
        html.Div([
            html.Div([
                html.Div(id="sidebar", children=sidebar(default_catcher, season, start_d, end_d)),
                notes_ui.note_card("catching"),
            ], style={"width": "260px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
