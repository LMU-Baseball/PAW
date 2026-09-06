"""Dash callbacks for the Splash Report page.

Body render fires for EVERY account (player or coach) whenever Player/
Season/Cycle changes -- these are pure VIEW controls, team-transparent like
every other dashboard. `splash-editing` additionally drives edit-mode
rendering, but only a coach ever gets the Edit button that can set it True
(`suppress_callback_exceptions=True`, set in index.py, lets Dash accept the
Save callback's State ids even though they only exist in the DOM once
editing=True has actually rendered them).
"""
from __future__ import annotations

from dash import Input, Output, State, no_update
from flask_login import current_user

from app.data import splash_report as SR
from app.dashboards.pitching import selectors
from app.dashboards.splash_report import layout


def _is_coach() -> bool:
    return bool(getattr(current_user, "is_coach", False))


def _script_states() -> list:
    states = []
    for n in range(1, SR.N_SCRIPTS + 1):
        states.append(State(f"splash-script-goal-{n}", "value"))
        states.append(State(f"splash-script-measurable-{n}", "value"))
        states.append(State(f"splash-script-rows-{n}", "data"))
    return states


def register_callbacks(dash_app) -> None:

    # Season change -> refresh the Player dropdown's roster to that season
    # (a placeholder id valid in one season and a REAL GAMES id in another
    # can both represent the same person, so the id itself can change across
    # a season switch). Without this, a stale id from the old season stayed
    # selected forever -- the whole page LOOKED like it updated (the Season
    # dropdown's own value changed) while every KPI/section kept reading
    # data for a player who no longer matched that id, i.e. "the filters
    # don't work." Mirrors hitting/callbacks.py's `_on_daterange_hitters`:
    # keep the current selection if it's still valid for the new season,
    # else fall back to the first available pitcher.
    @dash_app.callback(
        Output("splash-player", "options"), Output("splash-player", "value"),
        Input("splash-season", "value"), State("splash-player", "value"),
        prevent_initial_call=True,
    )
    def _on_season_change(season, current_player_id):
        is_coach = _is_coach()
        own = getattr(current_user, "trackman_id", None)
        opts = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own, season=season)
        values = {o["value"] for o in opts}
        value = current_player_id if current_player_id in values else (
            opts[0]["value"] if opts else None)
        return opts, value

    @dash_app.callback(
        Output("splash-body", "children"),
        Input("splash-player", "value"), Input("splash-season", "value"),
        Input("splash-cycle", "value"), Input("splash-editing", "data"),
    )
    def _render(player_id, season, cycle, editing):
        return layout.render_body(player_id, season, cycle,
                                  editable=bool(editing) and _is_coach())

    @dash_app.callback(
        Output("splash-editing", "data", allow_duplicate=True),
        Output("splash-save-status", "children", allow_duplicate=True),
        Input("splash-edit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_edit(n_clicks):
        if not n_clicks or not _is_coach():
            return no_update, no_update
        return True, "Editing — update the fields below, then Save."

    @dash_app.callback(
        Output("splash-editing", "data"),
        Output("splash-save-status", "children"),
        Input("splash-save", "n_clicks"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        State("splash-vision", "value"), State("splash-goals", "value"),
        State("splash-pre", "value"), State("splash-post", "value"),
        State("splash-feetset", "value"), State("splash-feetmoving", "value"),
        State("splash-workday", "value"),
        State("splash-engine-strength-table", "data"),
        State("splash-engine-rom-table", "data"),
        State("splash-gas-table", "data"),
        State("splash-pen-table", "data"),
        *_script_states(),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, player_id, season, cycle, vision, goals, pre, post,
                feet_set, feet_moving, work_day, strength_rows, rom_rows, gas_rows,
                pen_rows, *script_args):
        if not n_clicks or not _is_coach():
            return no_update, no_update
        if player_id is None:
            return no_update, "Select a pitcher first."

        # recovery_video_url has no edit control yet (deferred) -- carry the
        # existing value through so a save never blanks it out.
        current_plan = SR.read_plan(player_id, season, cycle)
        plan_fields = {
            "vision_statement": vision, "training_goals": goals,
            "pre_throw_checklist": pre, "post_throw_checklist": post,
            "feet_set": "\n".join(feet_set or []),
            "feet_moving": "\n".join(feet_moving or []),
            "work_day": "\n".join(work_day or []),
            "recovery_video_url": current_plan["recovery_video_url"],
        }
        engine_rows = [
            {"metric_key": r.get("metric_key"), "base_value": r.get("base_value"),
             "now_value": r.get("now_value")}
            for r in (strength_rows or []) + (rom_rows or [])
        ]
        script_fields, script_pitch_rows = {}, {}
        for i, n in enumerate(range(1, SR.N_SCRIPTS + 1)):
            goal_v, measurable_v, rows_v = script_args[i * 3:i * 3 + 3]
            script_fields[n] = {"goal": goal_v, "measurable": measurable_v}
            script_pitch_rows[n] = rows_v or []

        SR.save_all(
            player_id, season, cycle, plan_fields=plan_fields, engine_rows=engine_rows,
            gas_rows=gas_rows or [], script_fields=script_fields,
            script_pitch_rows=script_pitch_rows, pen_rows=pen_rows or [],
            updated_by=getattr(current_user, "id", None))
        return False, "Saved."
