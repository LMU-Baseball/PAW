"""Dash callbacks for the Splash Report page.

Data loading and rendering are deliberately SEPARATE callbacks:
- `_load_data` re-reads the DB only when Player/Season/Cycle actually change,
  caching the result in the `splash-data` Store.
- `_render` draws the body from whatever is currently in that Store, reacting
  to it AND to `splash-editing` -- so toggling Edit (which changes only HOW
  the page is drawn, not what data it shows) is a pure client-side re-render,
  no new query. Before this split, Edit re-ran every read behind the page
  each time it was clicked, which was most of why it felt slow.

Body render fires for EVERY account (player or coach) -- these are pure VIEW
controls, team-transparent like every other dashboard. `splash-editing`
additionally drives edit-mode rendering, but only a coach ever gets the Edit
button that can set it True (`suppress_callback_exceptions=True`, set in
index.py, lets Dash accept the Save callback's State ids even though they
only exist in the DOM once editing=True has actually rendered them).
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

    # Player/Season/Cycle change -> re-read the DB into splash-data. Not
    # Input("splash-editing", ...) -- toggling Edit must NOT retrigger this.
    # prevent_initial_call=True: serve_layout() already seeds splash-data for
    # the first paint; without this the callback would immediately re-run
    # the exact same load a second time on page load.
    @dash_app.callback(
        Output("splash-data", "data"),
        Input("splash-player", "value"), Input("splash-season", "value"),
        Input("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _load_data(player_id, season, cycle):
        return layout.load_data(player_id, season, cycle)

    # splash-data OR splash-editing change -> pure re-render, no DB access.
    @dash_app.callback(
        Output("splash-body", "children"),
        Input("splash-data", "data"), Input("splash-editing", "data"),
    )
    def _render(data, editing):
        return layout.render_from_data(data, editable=bool(editing) and _is_coach())

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
        Output("splash-data", "data", allow_duplicate=True),
        Input("splash-save", "n_clicks"),
        State("splash-data", "data"),
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
    def _on_save(n_clicks, current_data, player_id, season, cycle, vision, goals, pre, post,
                feet_set, feet_moving, work_day, strength_rows, rom_rows, gas_rows,
                pen_rows, *script_args):
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update
        if player_id is None:
            return no_update, "Select a pitcher first.", no_update

        # recovery_video_url has no edit control yet (deferred) -- carry the
        # cached value through (no extra DB read) so a save never blanks it.
        recovery_url = (current_data or {}).get("plan", {}).get("recovery_video_url", "")
        plan_fields = {
            "vision_statement": vision, "training_goals": goals,
            "pre_throw_checklist": pre, "post_throw_checklist": post,
            "feet_set": "\n".join(feet_set or []),
            "feet_moving": "\n".join(feet_moving or []),
            "work_day": "\n".join(work_day or []),
            "recovery_video_url": recovery_url,
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
        # One fresh load so splash-data (and the view-mode render right
        # after) reflects exactly what was just persisted -- correctness
        # over trying to hand-reconstruct it from the Save form's own values.
        new_data = layout.load_data(player_id, season, cycle)
        return False, "Saved.", new_data
