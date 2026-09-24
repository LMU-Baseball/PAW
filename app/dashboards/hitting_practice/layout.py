"""Hitting Practice (HitTrax) shell: filters + four Streamlit-parity tabs."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.data import practice as P
from app.data import practice_plans as PP
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

    # Everything the layout needs (bounds, names, latest date, players-on-latest)
    # comes from ONE sessions query -- not a full all-players pitch load -- then
    # a single scoped pitch load for the default player (2 round-trips, light
    # render).
    from datetime import date as _date
    today = _date.today()
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
        min_d = max_d = today
        latest = today
        on_latest_all = []

    # Default the date filter to "This Season" anchored on TODAY's real calendar
    # date, not the latest practice session -- so a new season with no HitTrax
    # data ingested yet shows an honest empty view instead of a frozen prior-
    # season snapshot (same fix/rationale as the 2026-08-26 season-default
    # change to the game dashboards). Clamped only at the data's own earliest
    # bound; the calendar's own max (below) is likewise not capped at old data.
    cal_max = max(str(max_d), str(today))
    s0, e0 = dr.preset_range("season", str(today))
    start_d, end_d = max(str(s0), str(min_d)), str(e0)

    # First paint's player list/options are scoped to that same season-default
    # range -- not every player who has EVER had a session -- so the dropdown
    # matches what _on_filters will show once the date-range callback fires.
    names = P.players_in_range(start_d, end_d)
    players = selectors.player_options(names, is_coach=is_coach, own_name=own_name)
    plan_rows = PP.list_plans()
    plan_options = [{"label": p.name, "value": p.name} for p in plan_rows]
    available_dates = P.practice_dates(start_d, end_d, exclude_test=True)
    assignments0 = PP.assignments_for_dates(available_dates)
    _, session_options = selectors.session_date_options(available_dates, assignments0)
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
            dr.date_control("prac", str(today), min_date=str(min_d), max_date=cal_max,
                            preset="season", start=start_d, end=end_d),
        ]),
        html.Div([
            html.Label("Player", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-player", options=players, value=default_player,
                         clearable=False, style={"minWidth": "200px"}),
        ]),
        html.Div([
            html.Label("Practice sessions", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-session-dates", options=session_options,
                         value="__all_sessions__", multi=False, clearable=False,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Practice plans", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-plan-filter", options=plan_options, value=[],
                         multi=True, placeholder="All plans", style={"minWidth": "200px"}),
        ]),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "flexWrap": "wrap", "padding": "12px 16px", "backgroundColor": BANNER})

    # ALWAYS rendered (never conditionally omitted), visibility toggled via
    # style instead -- this used to be `if is_coach else html.Div()`, which
    # dropped prac-plan-assignment-dates/-values and prac-plan-manage-select
    # from the layout entirely for non-coach accounts. `_on_filters` below
    # unconditionally targets those ids as Outputs; Dash has no way to write
    # to an Output that doesn't exist in the CURRENT client's layout, so it
    # threw a ReferenceError and aborted the whole callback for every
    # non-coach session -- including its OTHER outputs (prac-filters, which
    # every player's pitch-data load depends on), which is why the practice
    # board showed "no data" for every player under a player-role account
    # while a coach account was unaffected (2026-09-24, Brad: "LMU Team"
    # account). Same fix idiom already used in splash_report/layout.py for
    # this exact class of bug.
    coach_editor = html.Details([
        html.Summary("Manage practice plans", style={"cursor": "pointer", "fontWeight": "bold"}),
        html.Div([
            html.Div("Assignments apply to every player on the selected dates. Saving replaces the selected dates' plan assignments."),
            dcc.Dropdown(id="prac-plan-assignment-dates",
                         options=[{"label": d, "value": d} for d in available_dates],
                         value=[], multi=True, placeholder="Select dates to assign"),
            dcc.Dropdown(id="prac-plan-assignment-values", options=plan_options,
                         value=[], multi=True, placeholder="Select plans"),
            html.Div([
                html.Button("Save assignments", id="prac-plan-save", n_clicks=0,
                            style={"width": "auto", "maxWidth": "fit-content", "display": "inline-block", "justifySelf": "start"}),
            ], style={"display": "flex", "justifyContent": "flex-start"}),
            html.Div(id="prac-plan-status"),
            html.Div(id="prac-plan-manage-list"),
            html.Div([
                dcc.Dropdown(id="prac-plan-manage-select", options=plan_options,
                             value=None, placeholder="Select plan to rename/archive",
                             style={"minWidth": "240px"}),
                dcc.Input(id="prac-plan-rename", type="text", placeholder="Replacement name",
                          style={"width": "180px"}),
                html.Button("Rename", id="prac-plan-rename-button", n_clicks=0,
                            style={"width": "auto", "maxWidth": "fit-content", "display": "inline-block"}),
                html.Button("Archive", id="prac-plan-archive", n_clicks=0,
                            style={"width": "auto", "maxWidth": "fit-content", "display": "inline-block"}),
            ], style={"display": "flex", "gap": "6px", "alignItems": "center",
                      "justifyContent": "flex-start", "flexWrap": "wrap"}),
            html.Div([
                dcc.Input(id="prac-plan-new-name", type="text", placeholder="New plan name",
                          style={"width": "180px"}),
                html.Button("Add plan", id="prac-plan-add", n_clicks=0,
                            style={"width": "auto", "maxWidth": "fit-content", "display": "inline-block"}),
            ], style={"display": "flex", "gap": "6px", "justifyContent": "flex-start"}),
        ], style={"display": "grid", "gap": "8px", "padding": "10px 0"}),
    ], style={"padding": "8px 16px", "borderBottom": "1px solid #ddd",
              "display": "block" if is_coach else "none"})


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
            "session_dates": "__all_sessions__", "plans": [],
        }),
        dcc.Store(id="prac-pitch-data"),
        header(back_href="/hitting", back_label="← Hitting"),
        html.Div([
            html.Div(id="prac-sidebar", children=sidebar(pitch0, default_player),
                     className="paw-dash-sidebar"),
            html.Div([
                html.H2("HitTrax Practice Analytics",
                        style={"color": "#9A0021", "margin": "0 0 4px"}),
                html.Div("Ported from the Streamlit batting-practice dashboard. "
                         "Data refreshes via the HitTrax ELT pipeline (Mon–Sat).",
                         style={"color": "#555", "marginBottom": "8px"}),
                filters,
                coach_editor,
            ], className="paw-dash-filters"),
            html.Div([tabs,
                      html.Div(id="prac-tab-content", style={"padding": "8px 16px"})],
                     className="paw-dash-content"),
        ], className="paw-dash-row", style={"gridTemplateColumns": "240px 1fr"}),
    ])
