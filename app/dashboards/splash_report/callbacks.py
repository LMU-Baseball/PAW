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

import base64

import pandas as pd
from dash import ALL, MATCH, Input, Output, State, ctx, no_update
from flask_login import current_user

from app.data import splash_report as SR
from app.dashboards.pitching import selectors
from app.dashboards.splash_report import body_visual, charts, layout


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
        is_coach = _is_coach()
        return layout.render_from_data(data, editable=bool(editing) and is_coach,
                                       is_coach=is_coach)

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
        State("splash-gas-table", "data"),
        State("splash-pen-table", "data"),
        *_script_states(),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, current_data, player_id, season, cycle, vision, goals, pre, post,
                feet_set, feet_moving, work_day, gas_rows, pen_rows, *script_args):
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
        script_fields, script_pitch_rows = {}, {}
        for i, n in enumerate(range(1, SR.N_SCRIPTS + 1)):
            goal_v, measurable_v, rows_v = script_args[i * 3:i * 3 + 3]
            script_fields[n] = {"goal": goal_v, "measurable": measurable_v}
            script_pitch_rows[n] = rows_v or []

        SR.save_all(
            player_id, season, cycle, plan_fields=plan_fields,
            gas_rows=gas_rows or [], script_fields=script_fields,
            script_pitch_rows=script_pitch_rows, pen_rows=pen_rows or [],
            updated_by=getattr(current_user, "id", None))
        # One fresh load so splash-data (and the view-mode render right
        # after) reflects exactly what was just persisted -- correctness
        # over trying to hand-reconstruct it from the Save form's own values.
        new_data = layout.load_data(player_id, season, cycle)
        return False, "Saved.", new_data

    # Building the Engine's "Update Readings" -- deliberately separate from
    # the Edit/Save flow above (see app.data.splash_report.save_all's
    # docstring): it always ADDS a dated reading rather than revising
    # whatever's currently shown, so the trend survives regardless of how
    # often a coach clicks it.
    @dash_app.callback(
        Output("splash-update-readings-panel", "style"),
        Output("splash-update-readings-open", "data"),
        Input("splash-update-readings-toggle", "n_clicks"),
        State("splash-update-readings-open", "data"),
        prevent_initial_call=True,
    )
    def _toggle_update_readings(n_clicks, is_open):
        if not n_clicks or not _is_coach():
            return no_update, no_update
        now_open = not is_open
        style = {"display": "block", "marginTop": "8px"} if now_open \
            else {"display": "none", "marginTop": "8px"}
        return style, now_open

    @dash_app.callback(
        Output("splash-update-readings-status", "children"),
        Output("splash-update-readings-panel", "style", allow_duplicate=True),
        Output("splash-update-readings-open", "data", allow_duplicate=True),
        Output("splash-data", "data", allow_duplicate=True),
        Input("splash-update-readings-save", "n_clicks"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"), State("splash-reading-date", "value"),
        *[State(f"splash-reading-{k}", "value") for k in SR.ENGINE_METRIC_KEYS],
        prevent_initial_call=True,
    )
    def _on_update_readings(n_clicks, player_id, season, cycle, reading_date, *values):
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update, no_update
        if player_id is None:
            return "Select a pitcher first.", no_update, no_update, no_update
        if not reading_date:
            return "Enter a date first.", no_update, no_update, no_update
        rows = [{"metric_key": k, "value": v}
                for k, v in zip(SR.ENGINE_METRIC_KEYS, values) if v not in (None, "")]
        if not rows:
            return "Enter at least one value first.", no_update, no_update, no_update
        SR.upsert_engine_readings(player_id, season, cycle, reading_date, rows,
                                  updated_by=getattr(current_user, "id", None))
        new_data = layout.load_data(player_id, season, cycle)
        return (f"Saved reading for {reading_date}.", {"display": "none", "marginTop": "8px"},
                False, new_data)

    # ---- Drill catalog add/remove -- inline, directly under each of the
    # Feet Set / Feet Moving / Work Day dropdowns (2026-09-10 feedback: no
    # separate "Manage Drills" section). All three dropdowns share the same
    # catalog (app.data.splash_report.read_drill_options et al), so ONE
    # callback per action -- keyed by dash.MATCH on the "feetset"/
    # "feetmoving"/"workday" `section_key` -- serves all three instances of
    # `layout._drill_catalog_controls` instead of tripling the code; an add
    # or remove made from any one of the three shows up in all three after
    # the next splash-data refresh.
    @dash_app.callback(
        Output({"type": "splash-drill-status", "index": MATCH}, "children"),
        Output({"type": "splash-drill-add-input", "index": MATCH}, "value"),
        Output("splash-data", "data", allow_duplicate=True),
        Input({"type": "splash-drill-add-btn", "index": MATCH}, "n_clicks"),
        State({"type": "splash-drill-add-input", "index": MATCH}, "value"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_drill_catalog_add(n_clicks, name, player_id, season, cycle):
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update
        if not (name or "").strip():
            return "Enter a drill name first.", no_update, no_update
        SR.add_drill_option(name, created_by=getattr(current_user, "id", None))
        new_data = layout.load_data(player_id, season, cycle)
        return f"Added \"{name.strip()}\".", "", new_data

    @dash_app.callback(
        Output({"type": "splash-drill-status", "index": MATCH}, "children", allow_duplicate=True),
        Output("splash-data", "data", allow_duplicate=True),
        Input({"type": "splash-drill-remove-btn", "index": MATCH}, "n_clicks"),
        State({"type": "splash-drill-remove-select", "index": MATCH}, "value"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_drill_catalog_remove(n_clicks, name, player_id, season, cycle):
        if not n_clicks or not _is_coach():
            return no_update, no_update
        if not name:
            return "Pick a drill to remove first.", no_update
        SR.deactivate_drill_option(name)
        new_data = layout.load_data(player_id, season, cycle)
        return f"Removed \"{name}\".", new_data

    # ---- Manage Video Library: coach-only upload/remove for the shared
    # Recovery Protocols / Gas Station titled-link catalog (app.data.
    # splash_report.list_videos et al). Same "flag lives in splash-data"
    # reasoning as Manage Drills above.
    @dash_app.callback(
        Output("splash-data", "data", allow_duplicate=True),
        Input("splash-manage-videos-toggle", "n_clicks"),
        State("splash-data", "data"),
        prevent_initial_call=True,
    )
    def _toggle_manage_videos(n_clicks, data):
        if not n_clicks or not _is_coach() or not data:
            return no_update
        data = dict(data)
        data["manage_videos_open"] = not data.get("manage_videos_open", False)
        return data

    @dash_app.callback(
        Output("splash-video-upload-status", "children"),
        Output("splash-video-title", "value"),
        Output("splash-data", "data", allow_duplicate=True),
        Input("splash-video-upload", "contents"),
        State("splash-video-upload", "filename"),
        State("splash-video-title", "value"), State("splash-video-category", "value"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_upload_video(contents, filename, title, category, player_id, season, cycle):
        if not contents or not _is_coach():
            return no_update, no_update, no_update
        try:
            header, b64data = contents.split(",", 1)
            mimetype = header.split(";")[0].replace("data:", "") or "video/mp4"
            data = base64.b64decode(b64data)
            SR.add_video(title or filename or "Untitled", category, mimetype, data,
                        created_by=getattr(current_user, "id", None))
        except ValueError as e:
            return str(e), no_update, no_update
        new_data = layout.load_data(player_id, season, cycle)
        new_data["manage_videos_open"] = True
        return f"Uploaded \"{title or filename}\".", "", new_data

    @dash_app.callback(
        Output("splash-data", "data", allow_duplicate=True),
        Input({"type": "splash-video-delete", "index": ALL}, "n_clicks"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_delete_video(n_clicks_list, player_id, season, cycle):
        trig = ctx.triggered_id
        if not _is_coach() or not isinstance(trig, dict) or not any(n_clicks_list or []):
            return no_update
        SR.deactivate_video(trig["index"])
        new_data = layout.load_data(player_id, season, cycle)
        new_data["manage_videos_open"] = True
        return new_data

    # ---- Shared video popup (Recovery Protocols + Gas Station titled
    # links both open this one modal) -- streams from the /splash-video/
    # route (app.main.routes.splash_video), never embedded inline.
    @dash_app.callback(
        Output("splash-video-modal", "style"),
        Output("splash-video-modal-source", "src"),
        Output("splash-video-modal-title", "children"),
        Input({"type": "splash-video-open", "index": ALL}, "n_clicks"),
        Input("splash-video-modal-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_video_modal(_open_clicks, _close_clicks):
        trig = ctx.triggered_id
        hidden = {"display": "none", "position": "fixed", "inset": "0",
                 "backgroundColor": "rgba(0,0,0,0.7)", "zIndex": "1000", "padding": "16px"}
        shown = {**hidden, "display": "block"}
        if not isinstance(trig, dict) or not any(_open_clicks or []):
            return hidden, "", ""
        video_id = trig["index"]
        video = SR.get_video(video_id)
        if video is None:
            return hidden, "", ""
        return shown, f"/splash-video/{video_id}", video["title"]

    dash_app.clientside_callback(
        """
        function(src) {
            var v = document.getElementById('splash-video-modal-player');
            if (v) { v.load(); }
            return '';
        }
        """,
        Output("splash-video-modal-reload", "children"),
        Input("splash-video-modal-source", "src"),
    )

    # ---- Scripts section: "Show Scripts" reveals the matching card(s)
    # (2026-09-10 planning session -- "scripts below as a dropdown, only
    # show when clicked"). Every card is ALWAYS in the DOM (see
    # `layout.script_card`'s docstring for why) -- this just toggles each
    # wrapper's display, entirely client-side, so it never touches the
    # Save form's State values and never needs a server round trip.
    dash_app.clientside_callback(
        """
        function(selected) {
            var sel = selected || [];
            var out = [];
            for (var n = 1; n <= %d; n++) {
                out.push(sel.indexOf(n) !== -1
                    ? {display: 'block', marginBottom: '12px'} : {display: 'none'});
            }
            return out;
        }
        """ % SR.N_SCRIPTS,
        *[Output(f"splash-script-wrap-{n}", "style") for n in range(1, SR.N_SCRIPTS + 1)],
        Input("splash-script-select", "value"),
    )

    # "Compare Scripts" narrows which scripts' lines the pen-results trend
    # graph shows -- a normal (server) callback since it re-renders the
    # Plotly figure from splash-data, not just a style toggle.
    @dash_app.callback(
        Output("splash-pen-graph", "figure"),
        Input("splash-pen-compare", "value"), Input("splash-data", "data"),
    )
    def _on_pen_compare(selected, data):
        pen = pd.DataFrame((data or {}).get("pen", []))
        if selected and not pen.empty:
            pen = pen[pen["script_number"].isin(selected)]
        return charts.pen_results_fig(pen)

    # "Recently Removed" pen results -- Restore is immediate (not part of
    # the big Save), same "small coach-only action, refresh splash-data
    # right away" pattern as Manage Drills/Manage Video Library's
    # add/remove. See SR.save_pen_results'/restore_pen_result's docstrings
    # for why a deleted pen result is recoverable at all.
    @dash_app.callback(
        Output("splash-data", "data", allow_duplicate=True),
        Input({"type": "splash-pen-restore", "index": ALL}, "n_clicks"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_restore_pen_result(n_clicks_list, player_id, season, cycle):
        trig = ctx.triggered_id
        if not _is_coach() or not isinstance(trig, dict) or not any(n_clicks_list or []):
            return no_update
        SR.restore_pen_result(trig["index"], updated_by=getattr(current_user, "id", None))
        return layout.load_data(player_id, season, cycle)

    # Building the Engine's "View Cycles" -- widens Base/Now/Δ across more
    # than one cycle's readings (e.g. Fall+Winter+Spring = "full year"; see
    # SR.read_engine_history's docstring). Rebuilds the two tables AND the
    # body visual (its dot colors are the same now_value/flag the tables
    # show), not the whole card or splash-data, since nothing else on the
    # page reads a multi-cycle view.
    @dash_app.callback(
        Output("splash-engine-tables-wrap", "children"),
        Output("splash-engine-visual-wrap", "children"),
        Input("splash-engine-cycle-filter", "value"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-data", "data"),
        prevent_initial_call=True,
    )
    def _on_engine_cycle_filter(selected_cycles, player_id, season, data):
        if not selected_cycles or player_id is None:
            return no_update, no_update
        eng = SR.read_engine_metrics(player_id, season, selected_cycles)
        records = eng.to_dict("records")
        throws = ((data or {}).get("profile") or {}).get("throws")
        return layout.engine_tables_block(records), body_visual.render(records, throws)
