"""Hitting Practice (HitTrax) shell: filters + four Streamlit-parity tabs."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.data import practice as P
from app.dashboards.shell import BANNER, header
from app.dashboards.hitting_practice import selectors


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
        dcc.Tab(label="Contact Overview", value="contact"),
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
            html.H2("HitTrax Practice Analytics",
                    style={"color": "#9A0021", "margin": "0 0 4px"}),
            html.Div("Ported from the Streamlit batting-practice dashboard. "
                     "Data refreshes via the HitTrax ELT pipeline (Mon–Sat).",
                     style={"color": "#555", "marginBottom": "8px"}),
            filters, tabs,
            html.Div(id="prac-tab-content", style={"padding": "8px 16px"}),
        ], style={"padding": "16px"}),
    ])
