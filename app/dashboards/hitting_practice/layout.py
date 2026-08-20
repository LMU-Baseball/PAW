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
    if not player:
        photo, name = PHOTO_PLACEHOLDER, "No players"
    else:
        media = roster_media.player_media_by_name(player)
        photo = media.get("photo_url") or PHOTO_PLACEHOLDER
        name = player
    d = pitch_df if (pitch_df is not None and not pitch_df.empty) else pd.DataFrame()
    if not d.empty:
        d = P.trim_to_first_contact(d)
    summ = P.contact_summary(d)
    sds = P.swing_decision_score(d)
    cq = P.contact_quality(d)

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
        html.Div("Contact Quality", style={"fontSize": "14px", "color": "#9A0021",
                                           "fontWeight": "bold", "marginTop": "10px"}),
        html.Div([_tile("HARD-HIT%", f(cq["hard_hit_pct"], "%")),
                  _tile("POP-UP%", f(cq["popup_pct"], "%"))],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"}),
    ], style={"padding": "8px"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own_name = getattr(current_user, "name", None)

    # Default view opens on the MOST RECENT session date (a single day), showing
    # the first-alphabetical player who had a session that day. Everything the
    # layout needs (bounds, names, latest date, players-on-latest) comes from ONE
    # sessions query -- not a full all-players pitch load -- then a single scoped
    # pitch load for the default player (2 round-trips, light render).
    from datetime import date as _date
    sessions = P.load_sessions()
    if sessions is not None and not sessions.empty:
        s = sessions.copy()
        s["player_name"] = s["player_name"].astype(str).str.strip()
        s = s[s["player_name"] != ""]
        min_d, max_d = s["session_date"].min(), s["session_date"].max()
        latest = max_d
        on_latest_all = sorted(s.loc[s["session_date"] == latest, "player_name"].unique(),
                               key=str.lower)
    else:
        min_d = max_d = latest = _date.today()
        on_latest_all = []

    # Default the date filter to "This Season" (same preset behavior as the game
    # dashboards) instead of a single day, clamped to the data's own bounds.
    s0, e0 = dr.preset_range("season", str(max_d))
    start_d, end_d = max(str(s0), str(min_d)), str(e0)

    # First paint's player list/options are scoped to that same season-default
    # range -- not every player who has EVER had a session -- so the dropdown
    # matches what _on_filters will show once the date-range callback fires.
    names = P.players_in_range(start_d, end_d)
    players = selectors.player_options(names, is_coach=is_coach, own_name=own_name)
    opt_values = {o["value"] for o in players}
    on_latest = [n for n in on_latest_all if n in opt_values]
    default_player = selectors.resolve_player(
        None, is_coach=is_coach, own_name=own_name, available=names,
        default=(on_latest[0] if on_latest else None))

    try:
        pitch0 = P.load_pitch_coords(player=default_player,
                                     start=_date.fromisoformat(start_d),
                                     end=_date.fromisoformat(end_d)) \
            if default_player else pd.DataFrame()
    except Exception:
        pitch0 = pd.DataFrame()

    filters = html.Div([
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("prac", str(max_d), min_date=str(min_d), max_date=str(max_d),
                            preset="season", start=start_d, end=end_d),
        ]),
        html.Div([
            html.Label("Player", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-player", options=players, value=default_player,
                         clearable=False,
                         style={"minWidth": "200px"}),
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
            "player": default_player,
            "session": "All session types", "exclude_test": True,
            "start": start_d, "end": end_d,
        }),
        dcc.Store(id="prac-pitch-data"),
        header(back_href="/hitting", back_label="← Hitting"),
        html.Div([
            html.Div(id="prac-sidebar", children=sidebar(pitch0, default_player),
                     className="paw-dash-sidebar", style={"width": "240px", "flexShrink": "0"}),
            html.Div([
                html.H2("HitTrax Practice Analytics",
                        style={"color": "#9A0021", "margin": "0 0 4px"}),
                html.Div("Ported from the Streamlit batting-practice dashboard. "
                         "Data refreshes via the HitTrax ELT pipeline (Mon–Sat).",
                         style={"color": "#555", "marginBottom": "8px"}),
                filters, tabs,
                html.Div(id="prac-tab-content", style={"padding": "8px 16px"}),
            ], className="paw-dash-content", style={"flexGrow": "1"}),
        ], className="paw-dash-row", style={"display": "flex", "gap": "16px", "padding": "16px", "alignItems": "flex-start"}),
    ])
