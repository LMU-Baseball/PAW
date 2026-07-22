"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import Input, Output, State, html
from flask_login import current_user

from app.data import pitching as P
from app.dashboards.pitching import layout, selectors
from app.dashboards.pitching.tabs import location_movement, pitch_breakdown


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
        df = P.game_pitches(int(sel["game_id"]), int(sel["pitcher_id"]))
        return None if df.empty else df.to_json(orient="split")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "breakdown":
            return pitch_breakdown.render(df)
        if tab == "location":
            return location_movement.render(df)
        # Tabs wired in Tasks 5-8.
        return html.Div(f"[{tab}] {len(df)} pitches", style={"padding": "12px"})
