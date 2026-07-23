"""The catching dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from dash import dcc, html
from flask_login import current_user

from app.data import catching as C
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
    prof = C.catcher_profile(int(catcher_id))
    summ = C.season_summary(int(catcher_id))
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
                  _tile("CS%", summ["cs_pct"]), _tile("BLOCK%", summ["block_pct"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Season tiles = warehouse (provisional framing/block%).",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id) -> html.Div:
    if not game_id:
        return html.Div()
    try:
        ctx = C.game_context(int(game_id))
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
    games = selectors.game_options(default_catcher)
    default_game = games[0]["value"] if games else None

    selector_row = html.Div([
        html.Div([
            html.Label("Catcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="catcher-dd", options=catchers, value=default_catcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
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
        dcc.Tab(label="Framing", value="framing"),
        dcc.Tab(label="Blocking", value="blocking"),
        dcc.Tab(label="Throws", value="throws"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"catcher_id": default_catcher,
                                        "game_id": default_game}),
        dcc.Store(id="game-data"),
        header(back_href="/catching", back_label="← Catching"),
        html.Div([
            html.Div(id="sidebar", children=sidebar(default_catcher),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
