"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import pitching as P
from app.dashboards.pitching import layout, selectors
from app.dashboards.pitching.tabs import last_outings, location_movement, pitch_breakdown, rhh_lhh


def _read_game_df(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("outing-dd", "options"), Output("outing-dd", "value"),
        Input("pitcher-dd", "value"),
    )
    def _on_pitcher(pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        opts = selectors.outing_options(pid)
        return opts, (opts[0]["value"] if opts else None)

    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("pitcher-dd", "value"), Input("outing-dd", "value"),
    )
    def _on_selection(pitcher_id, game_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        return ({"pitcher_id": pid, "game_id": game_id},
                layout.sidebar(pid), layout.scoreboard(game_id))

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("game_id") is None or sel.get("pitcher_id") is None:
            return None
        df = P.game_pitches_for(int(sel["game_id"]), int(sel["pitcher_id"]))
        return None if df.empty else df.to_json(orient="split")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        if tab == "outings":
            sel = sel or {}
            return last_outings.render(sel.get("pitcher_id"), sel.get("game_id"), 5)
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "breakdown":
            return pitch_breakdown.render(df)
        if tab == "location":
            return location_movement.render(df)
        if tab == "splits":
            return rhh_lhh.render(df)
        return html.Div()

    # Chip click -> toggle the pitch type in the active-set store.
    @dash_app.callback(
        Output("lm-active", "data"),
        Input({"type": "lm-chip", "index": ALL}, "n_clicks"),
        State("lm-active", "data"),
        prevent_initial_call=True,
    )
    def _lm_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]
        active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    # Active-set (or new data) -> re-render movement + location + table, filtered.
    @dash_app.callback(
        Output("lm-body", "children"),
        Input("lm-active", "data"), State("game-data", "data"),
    )
    def _lm_body(active, data_json):
        df = _read_game_df(data_json)
        if not df.empty and active is not None:
            df = df[P.pitch_type(df).isin(active)]
        return location_movement.body(df)

    # Give the active chips a visual "off" state: dim deselected chips.
    @dash_app.callback(
        Output({"type": "lm-chip", "index": ALL}, "style"),
        Input("lm-active", "data"),
        State({"type": "lm-chip", "index": ALL}, "id"),
    )
    def _lm_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = P.pitch_color(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out
