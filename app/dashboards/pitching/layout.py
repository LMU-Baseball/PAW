"""The pitching dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from dash import dcc, html
from flask_login import current_user

from app.data import pitching as P
from app.dashboards.shell import CRIMSON, PHOTO_PLACEHOLDER, header, section
from app.dashboards.pitching import selectors

_BANNER = "rgba(154,0,33,0.82)"


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(pitcher_id) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    prof = P.pitcher_profile(int(pitcher_id))
    summ = P.season_summary(int(pitcher_id))
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Throws {prof['throws']}" if prof["throws"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("APP", summ["appearances"]), _tile("PITCHES", summ["pitches"]),
                  _tile("K", summ["k"]), _tile("BB", summ["bb"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Season totals = warehouse (provisional).",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id) -> html.Div:
    if not game_id:
        return html.Div()
    try:
        ctx = P.game_context(int(game_id))
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
    pitchers = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own)
    default_pitcher = selectors.resolve_pitcher(
        pitchers[0]["value"] if pitchers else None,
        is_coach=is_coach, own_trackman_id=own)
    outings = selectors.outing_options(default_pitcher)
    default_game = outings[0]["value"] if outings else None

    selector_row = html.Div([
        html.Div([
            html.Label("Pitcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="pitcher-dd", options=pitchers, value=default_pitcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Outing", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="outing-dd", options=outings, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": _BANNER})

    tabs = dcc.Tabs(id="tabs", value="breakdown", children=[
        dcc.Tab(label="Pitch Breakdown", value="breakdown"),
        dcc.Tab(label="Location / Movement", value="location"),
        dcc.Tab(label="RHH v. LHH", value="splits"),
        dcc.Tab(label="Last Outings", value="outings"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"pitcher_id": default_pitcher,
                                        "game_id": default_game}),
        dcc.Store(id="game-data"),
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div([
            html.Div(id="sidebar", children=sidebar(default_pitcher),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
