"""Hitting Practice (HitTrax) shell: filters + four Streamlit-parity tabs."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.data import practice as P
from app.data import roster_media
from app.dashboards import date_range as dr
from app.dashboards.shell import BANNER, PHOTO_PLACEHOLDER, header
from app.dashboards.hitting_practice import selectors


def _tile(label, value):
    from app.dashboards.shell import CRIMSON
    return html.Div([
        html.Div(str(value), style={"fontSize": "24px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "13px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 8px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px"})


def sidebar(pitch_df, player) -> html.Div:
    import pandas as pd
    from app.data import practice as P
    is_all = (not player) or player == "All Players"
    if is_all:
        photo, name = PHOTO_PLACEHOLDER, "All Players"
    else:
        media = roster_media.player_media_by_name(player)
        photo = media.get("photo_url") or PHOTO_PLACEHOLDER
        name = player
    d = pitch_df if (pitch_df is not None and not pitch_df.empty) else pd.DataFrame()
    if not d.empty:
        d = P.trim_to_first_contact(d)
    summ = P.contact_summary(d)
    sds = P.swing_decision_score(d)

    def f(v, s=""):
        return "—" if v is None else f"{v}{s}"

    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white", "background": "rgba(255,255,255,0.6)"}),
        html.Div(name, style={"fontSize": "22px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div("Swing Frequency", style={"fontSize": "14px", "color": "#9A0021",
                                            "fontWeight": "bold", "marginTop": "10px"}),
        html.Div([_tile("Pitches", summ["pitches"]), _tile("Contacts", summ["contacts"]),
                  _tile("Contact%", f(summ["contact_pct"], "%"))],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"}),
        html.Div("Swing Decision", style={"fontSize": "14px", "color": "#9A0021",
                                          "fontWeight": "bold", "marginTop": "10px"}),
        html.Div([_tile("In-Zone%", f(sds["in_zone_pct"], "%")),
                  _tile("Chase%", f(sds["chase_pct"], "%")),
                  _tile("SD Score", f(sds["score"]))],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"}),
    ], style={"padding": "8px"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own_name = getattr(current_user, "name", None)

    try:
        pitch_all = P.load_pitch_coords(exclude_test=True)
    except Exception:
        pitch_all = pd.DataFrame()

    start, end = P.preset_date_range("Custom")
    min_d, max_d = P.date_bounds()
    players = selectors.player_options(pitch_all, is_coach=is_coach, own_name=own_name)
    default_player = players[0]["value"] if players else "All Players"
    sessions = [{"label": s, "value": s} for s in P.session_options(pitch_all)]

    filters = html.Div([
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(
                id="prac-date-preset",
                options=[
                    {"label": "Custom (Swing Decision → today)", "value": "Custom"},
                    {"label": "Past Week", "value": "Past Week"},
                    {"label": "Past Month", "value": "Past Month"},
                    {"label": "Past 3 Months", "value": "Past 3 Months"},
                    {"label": "Past Year", "value": "Past Year"},
                ],
                value="Custom", clearable=False, style={"minWidth": "220px"},
            ),
        ]),
        html.Div([
            html.Label("Calendar", style={"color": "white", "fontWeight": "bold"}),
            dr.date_picker("prac", start.isoformat(), end.isoformat(),
                           min_date=str(min_d), max_date=str(max_d)),
        ]),
        html.Div([
            html.Label("Player", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-player", options=players, value=default_player,
                         clearable=False, disabled=not is_coach and len(players) <= 1,
                         style={"minWidth": "200px"}),
        ]),
        html.Div([
            html.Label("Session", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-session", options=sessions,
                         value="All session types", clearable=False,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Options", style={"color": "white", "fontWeight": "bold"}),
            dcc.Checklist(
                id="prac-exclude-test",
                options=[{"label": " Exclude test accounts", "value": "exclude"}],
                value=["exclude"],
                style={"color": "white"},
            ),
        ]),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "flexWrap": "wrap", "padding": "12px 16px", "backgroundColor": BANNER})

    tabs = dcc.Tabs(id="prac-tabs", value="zones", children=[
        dcc.Tab(label="Pitch Zones", value="zones"),
        dcc.Tab(label="Swing Frequency", value="swing"),
        dcc.Tab(label="Batted Ball", value="batted"),
        dcc.Tab(label="Session Tables", value="sessions"),
    ])

    return html.Div([
        dcc.Store(id="prac-filters", data={
            "player": default_player, "preset": "Custom",
            "session": "All session types", "exclude_test": True,
            "start": start.isoformat(), "end": end.isoformat(),
        }),
        dcc.Store(id="prac-pitch-data"),
        header(back_href="/hitting", back_label="← Hitting"),
        html.Div([
            html.Div(id="prac-sidebar", children=sidebar(pitch_all, default_player),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([
                html.H2("HitTrax Practice Analytics",
                        style={"color": "#9A0021", "margin": "0 0 4px"}),
                html.Div("Ported from the Streamlit batting-practice dashboard. "
                         "Data refreshes via the HitTrax ELT pipeline (Mon–Sat).",
                         style={"color": "#555", "marginBottom": "8px"}),
                filters, tabs,
                html.Div(id="prac-tab-content", style={"padding": "8px 16px"}),
            ], style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px", "alignItems": "flex-start"}),
    ])
