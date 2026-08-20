"""The bullpen dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import bullpen as B
from app.data import roster_media
from app.dashboards import date_range as dr
from app.dashboards.shell import BANNER, CRIMSON, PHOTO_PLACEHOLDER, header
from app.dashboards.bullpen import selectors

WINDOW_MIN = "2025-09-01"


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "13px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def _bullpen_anchor(pitcher_id):
    if pitcher_id is None:
        return date.today().isoformat()
    s = B.session_options(int(pitcher_id), WINDOW_MIN, date.today().isoformat())
    return str(s.iloc[0]["date"]) if not s.empty else date.today().isoformat()


def sidebar(pitcher_id, start, end) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    name = B.pitcher_name(int(pitcher_id)) or str(pitcher_id)
    summ = B.bullpen_session_summary(int(pitcher_id), start, end)
    media = roster_media.player_media_by_name(name)
    photo = media.get("photo_url") or PHOTO_PLACEHOLDER
    jersey = f"#{media['jersey']} · " if media.get("jersey") else ""
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{name}",
                 style={"fontSize": "24px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div([_tile("SESSIONS", summ["sessions"]), _tile("PITCHES", summ["pitches"]),
                  _tile("STRIKE %", "—" if summ["strike_pct"] is None else f"{summ['strike_pct']:.0f}%"),
                  _tile("AVG FB VELO", "—" if summ["avg_fb_velo"] is None else f"{summ['avg_fb_velo']:.1f}")],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Stats reflect the selected date range.",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "6px"}),
    ], style={"padding": "8px"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    pitchers_all = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own)
    default_pitcher = selectors.resolve_pitcher(
        pitchers_all[0]["value"] if pitchers_all else None, is_coach=is_coach, own_trackman_id=own)

    anchor = _bullpen_anchor(default_pitcher)
    s0, e0 = dr.preset_range("season", anchor)
    start_d, end_d = str(s0), str(e0)
    # WINDOW_MIN remains the calendar min; end bound = today
    cal_max = date.today().isoformat()

    # First-paint options scoped to that same season-default range (mirrors
    # the _on_daterange_pitchers callback) -- not every pitcher who's ever
    # thrown a bullpen.
    pitchers = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                         start=start_d, end=end_d)
    # Fallback mirrors _on_daterange_pitchers exactly (callbacks.py): if the
    # unscoped default isn't in the range-scoped options, fall back to the
    # first available option's value (or None). Team-transparent view: every
    # account (coach or player) sees the full roster and defaults to the first
    # roster pitcher, so this fallback fires uniformly regardless of role.
    pitcher_values = {p["value"] for p in pitchers}
    if default_pitcher not in pitcher_values:
        default_pitcher = pitchers[0]["value"] if pitchers else None
    sess = B.session_options(default_pitcher, start_d, end_d) if default_pitcher is not None else None
    session_opts = selectors.session_dropdown_options(sess)
    default_session = session_opts[0]["value"] if session_opts else None

    selector_row = html.Div([
        html.Div([
            html.Label("Pitcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="bp-pitcher-dd", options=pitchers, value=default_pitcher,
                         clearable=False, style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("bp", anchor, min_date=WINDOW_MIN, max_date=cal_max, preset="season"),
        ]),
        html.Div([
            html.Label("Session (detail)", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="bp-session-dd", options=session_opts, value=default_session,
                         clearable=False, style={"minWidth": "220px"}),
        ]),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "flexWrap": "wrap", "padding": "12px 16px", "backgroundColor": BANNER})

    tabs = dcc.Tabs(id="bp-tabs", value="session", children=[
        dcc.Tab(label="Session Detail", value="session"),
        dcc.Tab(label="Development Trends", value="trends"),
    ])

    return html.Div([
        dcc.Store(id="bp-selection", data={"pitcher_id": default_pitcher,
                                           "session_date": default_session,
                                           "start": start_d, "end": end_d}),
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div([
            html.Div(id="bp-sidebar", children=sidebar(default_pitcher, start_d, end_d),
                     className="paw-dash-sidebar", style={"width": "240px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="bp-tab-content", style={"padding": "8px 16px"})],
                     className="paw-dash-content", style={"flexGrow": "1"}),
        ], className="paw-dash-row", style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
