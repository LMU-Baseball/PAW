"""Dash callbacks: selection -> stores -> reactive sidebar/session-dd/tab/trends."""
from __future__ import annotations

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import bullpen as B
from app.dashboards.bullpen import layout, selectors
from app.dashboards.bullpen.tabs import session_detail, trends
from app.reports.plots import color_for


def _resolve(pitcher_id):
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    return selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)


def register_callbacks(dash_app) -> None:

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
        State("bp-daterange", "start_date"), State("bp-daterange", "end_date"),
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
        pid = sel.get("pitcher_id")
        if tab == "trends":
            return trends.render(pid, sel.get("start"), sel.get("end"))
        return session_detail.render(pid, sel.get("session_date"))

    # Trend chip click -> toggle the pitch type in the active-set store.
    @dash_app.callback(
        Output("bp-trend-active", "data"),
        Input({"type": "bp-trend-chip", "index": ALL}, "n_clicks"),
        State("bp-trend-active", "data"), prevent_initial_call=True,
    )
    def _trend_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]
        active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    # Metric / active-set change -> re-render the trend body from the stored df.
    @dash_app.callback(
        Output("bp-trend-body", "children"),
        Input("bp-trend-metric", "value"), Input("bp-trend-active", "data"),
        State("bp-trend-data", "data"), prevent_initial_call=True,
    )
    def _trend_body(metric, active, data_json):
        if not data_json:
            return html.Div("No bullpen data in this date range.",
                            style={"padding": "12px", "color": "#555"})
        import io
        df = pd.read_json(io.StringIO(data_json), orient="split")
        return trends.body(df, metric or "velocity", active or [])

    # Dim deselected chips.
    @dash_app.callback(
        Output({"type": "bp-trend-chip", "index": ALL}, "style"),
        Input("bp-trend-active", "data"),
        State({"type": "bp-trend-chip", "index": ALL}, "id"),
    )
    def _trend_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = color_for(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out
