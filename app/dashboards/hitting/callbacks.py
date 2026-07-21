"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import pandas as pd
from dash import Input, Output, State, dcc, html
from flask_login import current_user

from app.data import hitting_wh
from app.dashboards.hitting import layout, selectors
from app.dashboards.hitting.tabs import game_level, plate_appearances as pa, zone_location as zl


def _load_game_df(store) -> pd.DataFrame:
    if not store or store.get("game_id") is None or store.get("batter_id") is None:
        return pd.DataFrame()
    return hitting_wh.wh_game_pitches(int(store["game_id"]), int(store["batter_id"]))


def register_callbacks(dash_app) -> None:

    # Coach picks a hitter -> refresh that hitter's game options (players locked).
    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("hitter-dd", "value"),
    )
    def _on_hitter(batter_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        opts = selectors.game_options(bid)
        return opts, (opts[0]["value"] if opts else None)

    # Selection -> selection store + sidebar + scoreboard.
    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("hitter-dd", "value"), Input("game-dd", "value"),
    )
    def _on_selection(batter_id, game_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        return ({"batter_id": bid, "game_id": game_id},
                layout.sidebar(bid), layout.scoreboard(game_id))

    # Selection -> load the game pitch df into the game-data store.
    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        df = _load_game_df(sel)
        return None if df.empty else df.to_json(orient="split")

    # Tab or data change -> render the active tab.
    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        df = pd.read_json(data_json, orient="split") if data_json else pd.DataFrame()
        if tab == "game":
            # Coach notes are legacy-keyed (NOTES.GAME_ID) and don't match warehouse
            # game_ids yet; wiring notes to warehouse games is a deferred follow-up.
            return game_level.render(df, note="")
        if tab == "pa":
            choices = pa.pa_choices(df)
            return html.Div([
                dcc.Dropdown(id="pa-dd", options=choices,
                             value=(choices[0]["value"] if choices else None),
                             clearable=False, style={"maxWidth": "260px"}),
                html.Div(id="pa-breakdown"),
                html.H3("All Plate Appearances", style={"color": "#9A0021"}),
                pa.render_all_pas(df),
            ])
        if tab == "zone":
            return html.Div([
                dcc.Dropdown(id="zone-dd", options=zl.ZONE_FILTER_OPTIONS,
                             value="All Swings", clearable=False,
                             style={"maxWidth": "220px"}),
                html.Div(id="zone-body"),
            ])
        return html.Div()

    # PA dropdown -> per-PA breakdown.
    @dash_app.callback(
        Output("pa-breakdown", "children"),
        Input("pa-dd", "value"), State("game-data", "data"),
    )
    def _pa_breakdown(pa_value, data_json):
        df = pd.read_json(data_json, orient="split") if data_json else pd.DataFrame()
        return pa.render_breakdown(df, pa_value)

    # Zone dropdown -> filtered zone body.
    @dash_app.callback(
        Output("zone-body", "children"),
        Input("zone-dd", "value"), State("game-data", "data"),
    )
    def _zone_body(zone_choice, data_json):
        df = pd.read_json(data_json, orient="split") if data_json else pd.DataFrame()
        return zl.render(df, zone_choice or "All Swings")
