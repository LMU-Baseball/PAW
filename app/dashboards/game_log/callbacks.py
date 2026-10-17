"""Game Log interactivity: season -> games, game -> filter options, filters ->
log + summary, row click -> play detail (video is the shared component's)."""
from __future__ import annotations

from dash import Input, Output, State, no_update

from app.dashboards.game_log import layout, tables
from app.dashboards.video import component as videotab
from app.data import game_log, seasons
from app.data import video as videodata


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("gl-game", "options"), Output("gl-game", "value"),
        Input("gl-season", "value"), prevent_initial_call=True,
    )
    def _on_season(season):
        s, e = seasons.season_bounds(season)
        games = game_log.lmu_games(s, e)
        opts = [{"label": r.GameLabel, "value": str(r.game_id)} for r in games.itertuples()]
        return opts, (opts[0]["value"] if opts else None)

    @dash_app.callback(
        Output("gl-batter", "options"), Output("gl-batter", "value"),
        Output("gl-pitcher", "options"), Output("gl-pitcher", "value"),
        Output("gl-inning", "options"), Output("gl-inning", "value"),
        Output("gl-ptype", "options"), Output("gl-ptype", "value"),
        Output("gl-show", "value"), Output("gl-zone", "value"),
        Input("gl-game", "value"), prevent_initial_call=True,
    )
    def _on_game(game):
        opts = layout.filter_options(game_log.game_pitches(game, with_video=False) if game else None)
        return (opts["batter"], None, opts["pitcher"], None, opts["inning"], None,
                opts["ptype"], None, None, None)

    @dash_app.callback(
        Output("gl-log", "children"), Output("gl-count", "children"),
        Output("gl-summary", "children"),
        Input("gl-game", "value"), Input("gl-batter", "value"), Input("gl-pitcher", "value"),
        Input("gl-inning", "value"), Input("gl-ptype", "value"), Input("gl-show", "value"),
        Input("gl-zone", "value"),
        prevent_initial_call=True,
    )
    def _on_filters(game, batter, pitcher, innings, ptypes, show, zones):
        df = game_log.game_pitches(game) if game else None
        shown = game_log.filter_pitches(df, batter=batter, pitcher=pitcher, innings=innings,
                                        types=ptypes, show_only=show, zones=zones)
        who = df if not batter or df is None else df[df["Batter"] == batter]
        return (tables.pitch_log(shown), layout._count_text(shown, df),
                layout.summary_strip(who, batter or "LMU hitters"))

    @dash_app.callback(
        Output("gl-detail", "children"),
        Input(tables.TABLE_ID, "active_cell"),
        State(tables.TABLE_ID, "derived_viewport_data"),
        State("gl-game", "value"),
    )
    def _on_select(active, rows, game):
        if not active or not rows or not game:
            return layout.play_detail(None, None)
        i = active.get("row")
        if i is None or i >= len(rows):
            return no_update
        return layout.play_detail(game_log.game_pitches(game, with_video=False), rows[i].get("PitchUID"))

    videotab.register_callbacks(dash_app, "gl", default_angle="batter_side",
                                angles=videodata.HITTER_ANGLES)
