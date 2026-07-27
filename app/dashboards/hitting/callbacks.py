"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import Input, Output, State, dcc, html
from flask_login import current_user

from app.data import hitting_wh
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.dashboards.hitting import layout, selectors
from app.dashboards.hitting.tabs import game_level, plate_appearances as pa, zone_location as zl


def _load_game_df(store) -> pd.DataFrame:
    if not store or store.get("batter_id") is None:
        return pd.DataFrame()
    gid = store.get("game_id")
    if gid == dr.ALL_IN_RANGE:
        if not store.get("start") or not store.get("end"):
            return pd.DataFrame()
        return hitting_wh.wh_range_pitches(int(store["batter_id"]),
                                           store["start"], store["end"])
    if gid is None:
        return pd.DataFrame()
    return hitting_wh.wh_game_pitches(int(gid), int(store["batter_id"]))


def _read_game_df(data_json):
    """Deserialize a game-data store payload back to a DataFrame (empty if None)."""
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    # Coach picks a hitter -> refresh the date range to that hitter's season span.
    @dash_app.callback(
        Output("hit-daterange", "start_date"), Output("hit-daterange", "end_date"),
        Input("hitter-dd", "value"), prevent_initial_call=True,
    )
    def _on_hitter_range(batter_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        g = hitting_wh.wh_games_for_batter(bid) if bid else None
        if g is None or g.empty:
            return None, None
        return str(g["game_date"].min()), str(g["game_date"].max())

    # Date range change -> refresh the game options within that range (players locked).
    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("hit-daterange", "start_date"), Input("hit-daterange", "end_date"),
        State("hitter-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, batter_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        if not bid or not start or not end:
            return [], None
        g = hitting_wh.wh_games_for_batter(bid, start=start, end=end)
        opts = dr.game_options(g)
        value = int(g.iloc[0]["game_id"]) if not g.empty else None  # empty range -> no value (sentinel isn't an option when 0 games)
        return opts, value

    # Selection -> selection store + sidebar + scoreboard.
    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("hitter-dd", "value"), Input("game-dd", "value"),
        State("hit-daterange", "start_date"), State("hit-daterange", "end_date"),
    )
    def _on_selection(batter_id, game_id, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = hitting_wh.wh_games_for_batter(bid, start=start, end=end) if bid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"batter_id": bid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(bid), sb)

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
        if tab == "video":
            sel = sel or {}
            bid = sel.get("batter_id")
            if bid is None:
                return html.Div("Select a hitter.", style={"padding": "12px", "color": "#555"})
            gid = sel.get("game_id")
            if gid == dr.ALL_IN_RANGE:
                g = hitting_wh.wh_games_for_batter(int(bid), start=sel.get("start"), end=sel.get("end"))
                gids = [int(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select a game.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [int(gid)]
            vdf = videodata.pitch_video_df(gids, batter_id=int(bid))
            return videotab.render(vdf, prefix="hit", default_angle="batter_side")
        df = _read_game_df(data_json)
        if tab == "game":
            return game_level.render(df)
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
        df = _read_game_df(data_json)
        return pa.render_breakdown(df, pa_value)

    # Zone dropdown -> filtered zone body.
    @dash_app.callback(
        Output("zone-body", "children"),
        Input("zone-dd", "value"), State("game-data", "data"),
    )
    def _zone_body(zone_choice, data_json):
        df = _read_game_df(data_json)
        return zl.render(df, zone_choice or "All Swings")

    videotab.register_callbacks(dash_app, "hit", default_angle="batter_side")
    notes_ui.register_note_callbacks(dash_app, "hitting", "batter_id")
