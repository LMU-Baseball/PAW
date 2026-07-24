"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import Input, Output, State, html
from flask_login import current_user

from app.data import catching as C
from app.dashboards.catching import layout, selectors
from app.dashboards.catching.tabs import framing, static_framing, caught_stealing


def _read_game_df(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("catcher-dd", "value"),
    )
    def _on_catcher(catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        opts = selectors.game_options(cid)
        return opts, (opts[0]["value"] if opts else None)

    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("catcher-dd", "value"), Input("game-dd", "value"),
    )
    def _on_selection(catcher_id, game_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        return ({"catcher_id": cid, "game_id": game_id},
                layout.sidebar(cid), layout.scoreboard(game_id))

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("game_id") is None or sel.get("catcher_id") is None:
            return None
        df = C.game_pitches_for(int(sel["game_id"]), int(sel["catcher_id"]))
        return None if df.empty else df.to_json(orient="split")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
    )
    def _render_tab(tab, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "framing":
            return framing.render(df)
        if tab == "static":
            return static_framing.render(df)
        if tab == "caught":
            return caught_stealing.render(df)
        return html.Div()

    @dash_app.callback(
        Output("fr-body", "children"),
        Input("fr-bat", "value"), Input("fr-throws", "value"),
        Input("fr-speed", "value"), Input("fr-zone", "value"),
        State("game-data", "data"),
    )
    def _framing_body(bat, throws, speed, zone, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        return framing.body(df, bat_side=bat or "All", pitcher_throws=throws or "All",
                            pitch_speed=speed or "All", zone=zone or "All")
