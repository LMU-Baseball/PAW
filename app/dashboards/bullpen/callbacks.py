"""Dash callbacks: selection -> stores -> reactive sidebar/session-dd/tab/trends."""
from __future__ import annotations

import pandas as pd
from dash import Input, Output, State, html
from flask_login import current_user

from app.data import bullpen as B
from app.dashboards import date_range as dr
from app.dashboards.bullpen import layout, selectors
from app.dashboards.bullpen.tabs import session_detail, trends


def _resolve(pitcher_id):
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    return selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)


def register_callbacks(dash_app) -> None:

    # Preset dropdown (or pitcher) change -> resolve the range + toggle the calendar.
    @dash_app.callback(
        Output("bp-daterange", "start_date"), Output("bp-daterange", "end_date"),
        Output("bp-cal-wrap", "style"),
        Input("bp-date-preset", "value"), Input("bp-pitcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset, pitcher_id):
        from dash import no_update
        show = {"display": "block" if preset == "custom" else "none", "marginTop": "6px"}
        if preset == "custom":
            return no_update, no_update, show
        pid = _resolve(pitcher_id)
        anchor = layout._bullpen_anchor(pid)
        s, e = dr.preset_range(preset, anchor)
        return max(str(s), layout.WINDOW_MIN), str(e), show

    # Pitcher or date-range change -> refresh session dropdown (default most-recent).
    @dash_app.callback(
        Output("bp-session-dd", "options"), Output("bp-session-dd", "value"),
        Input("bp-pitcher-dd", "value"),
        Input("bp-daterange", "start_date"), Input("bp-daterange", "end_date"),
        prevent_initial_call=True,
    )
    def _on_pitcher_or_range(pitcher_id, start, end):
        pid = _resolve(pitcher_id)
        if pid is None or not start or not end:
            return [], None
        opts = selectors.session_dropdown_options(B.session_options(pid, start, end))
        return opts, (opts[0]["value"] if opts else None)

    # Any selection change -> selection store + sidebar.
    @dash_app.callback(
        Output("bp-selection", "data"), Output("bp-sidebar", "children"),
        Input("bp-pitcher-dd", "value"), Input("bp-session-dd", "value"),
        Input("bp-daterange", "start_date"), Input("bp-daterange", "end_date"),
    )
    def _on_selection(pitcher_id, session_date, start, end):
        pid = _resolve(pitcher_id)
        data = {"pitcher_id": pid, "session_date": session_date, "start": start, "end": end}
        return data, layout.sidebar(pid, start, end)

    # Tab or selection change -> render the active tab.
    @dash_app.callback(
        Output("bp-tab-content", "children"),
        Input("bp-tabs", "value"), Input("bp-selection", "data"),
    )
    def _render_tab(tab, sel):
        sel = sel or {}
        pid = _resolve(sel.get("pitcher_id"))
        if tab == "trends":
            return trends.render(pid, sel.get("start"), sel.get("end"))
        return session_detail.render(pid, sel.get("session_date"))

    # Metric change -> re-render the trend body from the stored df.
    @dash_app.callback(
        Output("bp-trend-body", "children"),
        Input("bp-trend-metric", "value"), State("bp-trend-data", "data"),
        prevent_initial_call=True,
    )
    def _trend_body(metric, data_json):
        if not data_json:
            return html.Div("No bullpen data in this date range.",
                            style={"padding": "12px", "color": "#555"})
        import io
        df = pd.read_json(io.StringIO(data_json), orient="split")
        return trends.body(df, metric or "velocity")
