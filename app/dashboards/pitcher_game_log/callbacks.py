"""Pitching Game Log interactivity: season -> games, game -> filter options,
filters -> log + outing strip, row click -> pitch detail (video is the shared
component's)."""
from __future__ import annotations

from dash import Input, Output, State, no_update

from app.dashboards.game_log.layout import filter_options
from app.dashboards.pitcher_game_log import layout, tables
from app.dashboards.video import component as videotab
from app.data import pitcher_game_log as pgl
from app.data import seasons
from app.data import video as videodata


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("pgl-game", "options"), Output("pgl-game", "value"),
        Input("pgl-season", "value"), prevent_initial_call=True,
    )
    def _on_season(season):
        s, e = seasons.season_bounds(season)
        games = pgl.lmu_games(s, e)
        opts = [{"label": r.GameLabel, "value": str(r.game_id)} for r in games.itertuples()]
        return opts, (opts[0]["value"] if opts else None)

    @dash_app.callback(
        Output("pgl-batter", "options"), Output("pgl-batter", "value"),
        Output("pgl-pitcher", "options"), Output("pgl-pitcher", "value"),
        Output("pgl-inning", "options"), Output("pgl-inning", "value"),
        Output("pgl-ptype", "options"), Output("pgl-ptype", "value"),
        Output("pgl-show", "value"), Output("pgl-zone", "value"),
        Input("pgl-game", "value"), prevent_initial_call=True,
    )
    def _on_game(game):
        opts = filter_options(pgl.game_pitches(game, with_video=False) if game else None)
        return (opts["batter"], None, opts["pitcher"], None, opts["inning"], None,
                opts["ptype"], None, None, None)

    @dash_app.callback(
        Output("pgl-log", "children"), Output("pgl-count", "children"),
        Output("pgl-summary", "children"),
        Input("pgl-game", "value"), Input("pgl-batter", "value"), Input("pgl-pitcher", "value"),
        Input("pgl-inning", "value"), Input("pgl-ptype", "value"), Input("pgl-show", "value"),
        Input("pgl-zone", "value"),
        prevent_initial_call=True,
    )
    def _on_filters(game, batter, pitcher, innings, ptypes, show, zones):
        df = pgl.game_pitches(game) if game else None
        shown = pgl.filter_pitches(df, batter=batter, pitcher=pitcher, innings=innings,
                                   types=ptypes, show_only=show, zones=zones)
        who = df if not pitcher or df is None else df[df["Pitcher"] == pitcher]
        return (tables.pitch_log(shown), layout._count_text(shown, df),
                layout.summary_strip(who, pitcher or "LMU pitchers"))

    @dash_app.callback(
        Output("pgl-detail", "children"),
        Input(tables.TABLE_ID, "active_cell"),
        State(tables.TABLE_ID, "derived_viewport_data"),
        State("pgl-game", "value"),
    )
    def _on_select(active, rows, game):
        if not active or not rows or not game:
            return layout.play_detail(None, None)
        i = active.get("row")
        if i is None or i >= len(rows):
            return no_update
        return layout.play_detail(pgl.game_pitches(game, with_video=False), rows[i].get("PitchUID"))

    videotab.register_callbacks(dash_app, "pgl", default_angle="pitcher_side",
                                angles=videodata.PITCHER_ANGLES)
