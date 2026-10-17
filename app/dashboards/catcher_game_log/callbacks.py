"""Catching Game Log interactivity: season -> games, game -> filter options,
filters -> log + receiving strip, row click -> receiving detail (video is the
shared component's)."""
from __future__ import annotations

from dash import Input, Output, State, no_update

from app.dashboards.catcher_game_log import layout, tables
from app.dashboards.game_log.layout import filter_options
from app.dashboards.video import component as videotab
from app.data import catcher_game_log as cgl
from app.data import seasons
from app.data import video as videodata


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("cgl-game", "options"), Output("cgl-game", "value"),
        Input("cgl-season", "value"), prevent_initial_call=True,
    )
    def _on_season(season):
        s, e = seasons.season_bounds(season)
        games = cgl.lmu_games(s, e)
        opts = [{"label": r.GameLabel, "value": str(r.game_id)} for r in games.itertuples()]
        return opts, (opts[0]["value"] if opts else None)

    @dash_app.callback(
        Output("cgl-catcher", "options"), Output("cgl-catcher", "value"),
        Output("cgl-batter", "options"), Output("cgl-batter", "value"),
        Output("cgl-pitcher", "options"), Output("cgl-pitcher", "value"),
        Output("cgl-inning", "options"), Output("cgl-inning", "value"),
        Output("cgl-ptype", "options"), Output("cgl-ptype", "value"),
        Output("cgl-show", "value"), Output("cgl-zone", "value"),
        Input("cgl-game", "value"), prevent_initial_call=True,
    )
    def _on_game(game):
        df = cgl.game_pitches(game) if game else None
        opts = filter_options(df)
        return (layout.catcher_options(df), None, opts["batter"], None, opts["pitcher"], None,
                opts["inning"], None, opts["ptype"], None, None, None)

    @dash_app.callback(
        Output("cgl-log", "children"), Output("cgl-count", "children"),
        Output("cgl-summary", "children"),
        Input("cgl-game", "value"), Input("cgl-catcher", "value"), Input("cgl-batter", "value"),
        Input("cgl-pitcher", "value"), Input("cgl-inning", "value"), Input("cgl-ptype", "value"),
        Input("cgl-show", "value"), Input("cgl-zone", "value"),
        prevent_initial_call=True,
    )
    def _on_filters(game, catcher, batter, pitcher, innings, ptypes, show, zones):
        df = cgl.game_pitches(game) if game else None
        shown = cgl.filter_pitches(df, catcher=catcher, batter=batter, pitcher=pitcher,
                                   innings=innings, types=ptypes, show_only=show, zones=zones)
        who = df if not catcher or df is None else df[df["Catcher"] == catcher]
        return (tables.pitch_log(shown), layout._count_text(shown, df),
                layout.summary_strip(who, catcher or "LMU catchers"))

    @dash_app.callback(
        Output("cgl-detail", "children"),
        Input(tables.TABLE_ID, "active_cell"),
        State(tables.TABLE_ID, "derived_viewport_data"),
        State("cgl-game", "value"),
    )
    def _on_select(active, rows, game):
        if not active or not rows or not game:
            return layout.play_detail(None, None)
        i = active.get("row")
        if i is None or i >= len(rows):
            return no_update
        return layout.play_detail(cgl.game_pitches(game), rows[i].get("PitchUID"))

    videotab.register_callbacks(dash_app, "cgl", default_angle="HomeBehind",
                                angles=videodata.CATCHER_ANGLES)
