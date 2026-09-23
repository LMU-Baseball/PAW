"""Dash callbacks for the Built on the Bluff page.

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
import json

import pandas as pd
from dash import ALL, MATCH, Input, Output, State, ctx, no_update
from flask_login import current_user

from app.data import splash_report as SR
from app.dashboards.pitching import selectors
from app.dashboards.splash_report import charts, layout


def _is_coach() -> bool:
    return bool(getattr(current_user, "is_coach", False))


def _script_states() -> list:
    states = []
    for n in range(1, SR.N_SCRIPTS + 1):
        states.append(State(f"splash-script-goal-{n}", "value"))
        states.append(State(f"splash-script-measurable-{n}", "value"))
        states.append(State(f"splash-script-type-{n}", "value"))
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
        State("splash-engine-strength-table", "data"),
        State("splash-engine-rom-table", "data"),
        State("splash-gas-table", "data"),
        State("splash-pen-table", "data"),
        State("splash-movement-table", "data"),
        *_script_states(),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, current_data, player_id, season, cycle, vision, goals, pre, post,
                feet_set, feet_moving, work_day, engine_strength_rows, engine_rom_rows,
                gas_rows, pen_rows, movement_table_rows, *script_args):
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
            goal_v, measurable_v, type_v, rows_v = script_args[i * 4:i * 4 + 4]
            script_fields[n] = {"goal": goal_v, "measurable": measurable_v, "script_type": type_v}
            script_pitch_rows[n] = rows_v or []
        # The Movement Log is now ONE shared table (`splash-movement-table`,
        # a Script # column instead of six separate per-script grids -- see
        # layout.scripts_section/tables.movement_log_table) -- regroup its
        # flat rows by script_number before handing them to SR.save_all,
        # which still saves per-script (SR.save_movement is unchanged).
        # Every script number gets a key (even an empty list) so a script
        # whose last remaining row was just deleted here still gets its
        # active DB rows soft-deleted, not left stale.
        movement_rows = {n: [] for n in range(1, SR.N_SCRIPTS + 1)}
        for row in (movement_table_rows or []):
            try:
                sn = int(row.get("script_number"))
            except (TypeError, ValueError):
                continue
            if sn in movement_rows:
                movement_rows[sn].append(row)
        engine_rows = (engine_strength_rows or []) + (engine_rom_rows or [])

        SR.save_all(
            player_id, season, cycle, plan_fields=plan_fields, engine_rows=engine_rows,
            gas_rows=gas_rows or [], script_fields=script_fields,
            script_pitch_rows=script_pitch_rows, pen_rows=pen_rows or [],
            movement_rows=movement_rows,
            updated_by=getattr(current_user, "id", None))
        # One fresh load so splash-data (and the view-mode render right
        # after) reflects exactly what was just persisted -- correctness
        # over trying to hand-reconstruct it from the Save form's own values.
        new_data = layout.load_data(player_id, season, cycle)
        return False, "Saved.", new_data

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
        State("splash-video-drill-category", "value"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_upload_video(contents, filename, title, category, drill_category,
                         player_id, season, cycle):
        if not contents or not _is_coach():
            return no_update, no_update, no_update
        try:
            header, b64data = contents.split(",", 1)
            mimetype = header.split(";")[0].replace("data:", "") or "video/mp4"
            data = base64.b64decode(b64data)
            SR.add_video(title or filename or "Untitled", category, mimetype, data,
                        created_by=getattr(current_user, "id", None),
                        drill_category=drill_category if category == "Gas Station" else None)
        except ValueError as e:
            return str(e), no_update, no_update
        new_data = layout.load_data(player_id, season, cycle)
        new_data["manage_videos_open"] = True
        return f"Uploaded \"{title or filename}\".", "", new_data

    # ---- Link-based video (2026-09-16 -- SR.add_video_link): same
    # Title/Category/Drill Category fields as the upload above, just a
    # different action button and no file contents to react to.
    @dash_app.callback(
        Output("splash-video-upload-status", "children", allow_duplicate=True),
        Output("splash-video-title", "value", allow_duplicate=True),
        Output("splash-video-link-url", "value"),
        Output("splash-data", "data", allow_duplicate=True),
        Input("splash-video-add-link", "n_clicks"),
        State("splash-video-link-url", "value"),
        State("splash-video-title", "value"), State("splash-video-category", "value"),
        State("splash-video-drill-category", "value"),
        State("splash-player", "value"), State("splash-season", "value"),
        State("splash-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_add_video_link(n_clicks, url, title, category, drill_category,
                           player_id, season, cycle):
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update, no_update
        try:
            SR.add_video_link(title or "Untitled", category, url,
                              created_by=getattr(current_user, "id", None),
                              drill_category=drill_category if category == "Gas Station" else None)
        except ValueError as e:
            return str(e), no_update, no_update, no_update
        new_data = layout.load_data(player_id, season, cycle)
        new_data["manage_videos_open"] = True
        return f"Added \"{title or 'Untitled'}\".", "", "", new_data

    # ---- Gas Station exercise search (2026-09-16 round 7, Brad: "add an
    # exercise search bar at the top of the column so coaches can search")
    # -- narrows the Exercise column's dropdown options as a coach types,
    # entirely client-side against `gas_videos` already loaded in
    # splash-data (same list `layout.gas_station_card`/`tables.
    # gas_station_table` render from), so no DB round trip. Needs
    # "need"'s options re-sent alongside "exercise"'s on every keystroke --
    # `dropdown` is one prop covering the whole table, not settable
    # per-column, so leaving "need" out would wipe it.
    dash_app.clientside_callback(
        """
        function(query, data) {
            var needOptions = %(need_options)s;
            var videos = ((data || {}).videos || {})["Gas Station"] || [];
            var q = (query || "").trim().toLowerCase();
            var filtered = videos.filter(function(v) {
                var label = (v.drill_category || v.category || "") + " " + v.title;
                return label.toLowerCase().indexOf(q) !== -1;
            });
            filtered.sort(function(a, b) {
                var ka = (a.drill_category || a.category || "") + " " + a.title;
                var kb = (b.drill_category || b.category || "") + " " + b.title;
                return ka < kb ? -1 : ka > kb ? 1 : 0;
            });
            var exerciseOptions = filtered.map(function(v) {
                return {label: (v.drill_category || v.category) + " — " + v.title,
                        value: v.title};
            });
            return {need: {options: needOptions}, exercise: {options: exerciseOptions}};
        }
        """ % {"need_options": json.dumps(
            [{"label": v, "value": v} for v in SR.STRENGTH_NEED_OPTIONS])},
        Output("splash-gas-table", "dropdown"),
        Input("splash-gas-exercise-search", "value"),
        State("splash-data", "data"),
    )

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
            for (var n = 1; n <= %(n)d; n++) {
                out.push(sel.indexOf(n) !== -1
                    ? {display: 'block', marginBottom: '12px'} : {display: 'none'});
            }
            return out;
        }
        """ % {"n": SR.N_SCRIPTS},
        *[Output(f"splash-script-wrap-{n}", "style") for n in range(1, SR.N_SCRIPTS + 1)],
        Input("splash-script-select", "value"),
    )

    # Per-script Copy/Paste/Undo (2026-09-22, Brad's screenshot; narrowed to
    # the pitch TABLE only + cross-player fix + Undo added 2026-09-23 per
    # follow-up feedback: "just the table contents, the boxes on top can be
    # entered manually," and copying script 1 of one player then pasting
    # into script 2 of a DIFFERENT player pasted that second player's OWN
    # script 1, not the first player's).
    #
    # Root cause of the cross-player bug: `splash-body` (every script-scoped
    # Button lives inside it) gets torn down and rebuilt from scratch on
    # ANY player/season/cycle/Edit/Save change, and the fresh Copy/Paste/
    # Undo Buttons are hardcoded back to n_clicks=0. Dash's front end diffs
    # each Input's new rendered value against the last value IT saw for
    # that component id -- going from a real click's n_clicks=1 down to a
    # freshly-mounted button's n_clicks=0 is still a "changed" value, so it
    # re-fires the callback even though nothing was clicked. Reading State
    # at THAT spurious firing picks up whatever player/script is on screen
    # NOW, silently overwriting the clipboard with the wrong content. Fix:
    # a real click always moves n_clicks from its current value to a MORE
    # positive one (0 -> 1, 1 -> 2, ...), so the triggered button's own new
    # n_clicks is never falsy for a genuine click -- treat a falsy value as
    # the spurious re-fire and ignore it. Applied uniformly below.
    #
    # Plain per-index ids (not ALL/MATCH) -- same idiom as every other
    # script-scoped id on this page (`splash-script-goal-{n}` etc.) --
    # `ctx.triggered_id` says which of the N_SCRIPTS buttons fired.
    def _spurious_refire(triggered_id: str, prefix: str, n_clicks_list) -> tuple[int, bool]:
        """(index, is_spurious) for a Copy/Paste/Undo callback firing --
        shared by all three below."""
        if not triggered_id.startswith(prefix):
            return -1, True
        i = int(triggered_id.rsplit("-", 1)[1]) - 1
        return i, not n_clicks_list[i]

    @dash_app.callback(
        Output("splash-script-clipboard", "data"),
        *[Input(f"splash-script-copy-{n}", "n_clicks") for n in range(1, SR.N_SCRIPTS + 1)],
        *[State(f"splash-script-rows-{n}", "data") for n in range(1, SR.N_SCRIPTS + 1)],
        prevent_initial_call=True,
    )
    def _on_script_copy(*args):
        n = SR.N_SCRIPTS
        n_clicks, rows = args[:n], args[n:2 * n]
        i, spurious = _spurious_refire(ctx.triggered_id or "", "splash-script-copy-", n_clicks)
        if spurious:
            return no_update
        return {"rows": rows[i]}

    @dash_app.callback(
        *[Output(f"splash-script-rows-{n}", "data", allow_duplicate=True)
          for n in range(1, SR.N_SCRIPTS + 1)],
        Output("splash-script-undo-buffer", "data", allow_duplicate=True),
        *[Input(f"splash-script-paste-{n}", "n_clicks") for n in range(1, SR.N_SCRIPTS + 1)],
        State("splash-script-clipboard", "data"),
        *[State(f"splash-script-rows-{n}", "data") for n in range(1, SR.N_SCRIPTS + 1)],
        prevent_initial_call=True,
    )
    def _on_script_paste(*args):
        n = SR.N_SCRIPTS
        n_clicks, clip, rows = args[:n], args[n], args[n + 1:2 * n + 1]
        out_rows = [no_update] * n
        i, spurious = _spurious_refire(ctx.triggered_id or "", "splash-script-paste-", n_clicks)
        if spurious or not clip:
            return (*out_rows, no_update)
        out_rows[i] = clip.get("rows")
        # Snapshot this script's PRE-paste rows so Undo can restore them --
        # single-level (this paste only), not a full history stack.
        return (*out_rows, {"script_number": i + 1, "rows": rows[i]})

    @dash_app.callback(
        *[Output(f"splash-script-rows-{n}", "data", allow_duplicate=True)
          for n in range(1, SR.N_SCRIPTS + 1)],
        Output("splash-script-undo-buffer", "data", allow_duplicate=True),
        *[Input(f"splash-script-undo-{n}", "n_clicks") for n in range(1, SR.N_SCRIPTS + 1)],
        State("splash-script-undo-buffer", "data"),
        prevent_initial_call=True,
    )
    def _on_script_undo(*args):
        n = SR.N_SCRIPTS
        n_clicks, buf = args[:n], args[n]
        out_rows = [no_update] * n
        i, spurious = _spurious_refire(ctx.triggered_id or "", "splash-script-undo-", n_clicks)
        # Only undoes if the buffer's snapshot actually belongs to THIS
        # script -- clicking Undo where nothing was just pasted (or after
        # it's already been used once) is a no-op, not an error.
        if spurious or not buf or buf.get("script_number") != i + 1:
            return (*out_rows, no_update)
        out_rows[i] = buf.get("rows")
        return (*out_rows, None)   # single-use: clear the buffer after undoing

    # Archive (2026-09-23, Brad: "an archive button... it will automatically
    # archive what is on that script from this table specifically. That way
    # coach can just pull that archive whenever he selects the type of the
    # script") -- saves THIS script's current rows as the shared, team-wide
    # template for its Type (`SR.save_script_template`), overwriting
    # whatever was archived before for that type. A server round trip (not
    # clientside like copy/paste) since it's a real DB write. The matching
    # "pull" half is `_on_script_type_change` below.
    @dash_app.callback(
        *[Output(f"splash-script-archive-status-{n}", "children")
          for n in range(1, SR.N_SCRIPTS + 1)],
        *[Input(f"splash-script-archive-{n}", "n_clicks") for n in range(1, SR.N_SCRIPTS + 1)],
        *[State(f"splash-script-type-{n}", "value") for n in range(1, SR.N_SCRIPTS + 1)],
        *[State(f"splash-script-rows-{n}", "data") for n in range(1, SR.N_SCRIPTS + 1)],
        prevent_initial_call=True,
    )
    def _on_script_archive(*args):
        n = SR.N_SCRIPTS
        n_clicks, types, rows = args[:n], args[n:2 * n], args[2 * n:3 * n]
        out = [no_update] * n
        i, spurious = _spurious_refire(ctx.triggered_id or "", "splash-script-archive-", n_clicks)
        if spurious:
            return out
        script_type = types[i]
        if not script_type:
            out[i] = "Set a Type first"
            return out
        SR.save_script_template(script_type, rows[i], updated_by=getattr(current_user, "id", None))
        out[i] = f"Saved as the {script_type} default"
        return out

    # The "pull" half of Archive: selecting a Type auto-fills this script's
    # rows from that type's shared template -- but ONLY when the script is
    # currently blank, so switching Type on an already-filled-in script
    # never silently overwrites a coach's real entries.
    @dash_app.callback(
        *[Output(f"splash-script-rows-{n}", "data", allow_duplicate=True)
          for n in range(1, SR.N_SCRIPTS + 1)],
        *[Input(f"splash-script-type-{n}", "value") for n in range(1, SR.N_SCRIPTS + 1)],
        *[State(f"splash-script-rows-{n}", "data") for n in range(1, SR.N_SCRIPTS + 1)],
        prevent_initial_call=True,
    )
    def _on_script_type_change(*args):
        n = SR.N_SCRIPTS
        types, rows = args[:n], args[n:2 * n]
        out = [no_update] * n
        trig = ctx.triggered_id or ""
        if not trig.startswith("splash-script-type-"):
            return out
        i = int(trig.rsplit("-", 1)[1]) - 1
        script_type = types[i]
        current_rows = rows[i] or []
        is_blank = not any((r.get("pitch_type") or r.get("ball_info") or r.get("info"))
                           for r in current_rows)
        if not script_type or not is_blank:
            return out
        template = SR.get_script_template(script_type)
        if template:
            out[i] = template
        return out

    # Elastic script rows (2026-09-23, Brad: a script's pitch table used to
    # hard-stop at a fixed row count with no way to add more once full;
    # should "expand and be elastic" as a coach types, and shrink back when
    # rows are cleared). Clientside (not a server round trip) so it's
    # instant on every keystroke's blur. Self-referencing -- Input and
    # Output are both this table's own `data` -- which is safe here because
    # the logic converges: after it appends/trims rows, the very next
    # firing (triggered by that same write) recomputes the identical
    # desired length and returns no_update instead of writing again.
    # `layout._elastic_script_rows` applies the same trim server-side for
    # the initial page render; this is its live-editing JS twin.
    for _n in range(1, SR.N_SCRIPTS + 1):
        dash_app.clientside_callback(
            f"""
            function(rows) {{
                if (!rows || !rows.length) {{ return window.dash_clientside.no_update; }}
                var lastFilled = 0;
                for (var i = 0; i < rows.length; i++) {{
                    var r = rows[i];
                    var filled = (r.pitch_type && String(r.pitch_type).trim()) ||
                                 (r.ball_info && String(r.ball_info).trim()) ||
                                 (r.info && String(r.info).trim());
                    if (filled) {{ lastFilled = r.row_num; }}
                }}
                var visible = Math.max(1, Math.min({SR.N_SCRIPT_ROWS}, lastFilled + 1));
                if (visible === rows.length) {{ return window.dash_clientside.no_update; }}
                if (visible < rows.length) {{ return rows.slice(0, visible); }}
                var out = rows.slice();
                for (var n = rows.length + 1; n <= visible; n++) {{
                    out.push({{row_num: n, pitch_type: '', ball_info: '', info: ''}});
                }}
                return out;
            }}
            """,
            Output(f"splash-script-rows-{_n}", "data", allow_duplicate=True),
            Input(f"splash-script-rows-{_n}", "data"),
            prevent_initial_call=True,
        )

    # "Compare Scripts" narrows which scripts' lines the pen-results trend
    # graph AND the shared movement chart show -- a normal (server) callback
    # since it re-renders both Plotly figures from splash-data, not just a
    # style toggle.
    @dash_app.callback(
        Output("splash-pen-graph", "figure"),
        Output("splash-movement-graph", "figure"),
        Input("splash-pen-compare", "value"), Input("splash-data", "data"),
    )
    def _on_pen_compare(selected, data):
        pen = pd.DataFrame((data or {}).get("pen", []))
        if selected and not pen.empty:
            pen = pen[pen["script_number"].isin(selected)]
        movement = (data or {}).get("movement", {})
        return charts.pen_results_fig(pen), charts.scripts_movement_fig(movement, selected)

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

    # ---- Backspace/Delete fix for every editable table on this page
    # (2026-09-17, Brad: "backspace nor delete work in these tables... can
    # you make it so the data we type can be deleted"). Confirmed live:
    # clicking a cell auto-selects its whole text, so Backspace there
    # deletes that selection and correctly clears the cell -- that part
    # already worked, this doesn't touch it. But once actively typing inside
    # a plain cell (a collapsed cursor, not a selection) OR typing into a
    # dropdown-presentation cell's filter box (e.g. Gas Station's
    # Need/Exercise columns -- a `react-select` input, DOM-wise unrelated to
    # a plain cell's `<input class="dash-cell-value">`), Backspace/Delete do
    # nothing at all -- dash_table's own JS swallows the keydown either way.
    # Both are documented dash_table limitations (plotly/dash-table #700,
    # #830), not something any DataTable prop controls, so there's no
    # supported fix from Python. Installs one page-wide, capture-phase
    # keydown listener (guarded so it only attaches once) that performs the
    # deletion itself -- using the native value setter (bypassing React's
    # instance-level override) plus a dispatched `input` event so React's
    # own onChange still fires and Dash's redux store (or react-select's own
    # state) stays in sync -- instead of letting dash_table's broken
    # handling run. A capture-phase listener on `document` always runs
    # before dash_table's own listener (attached lower in the DOM), so
    # `stopImmediatePropagation` fully replaces that handling rather than
    # racing it. Only intervenes when there's actual text to delete (a
    # selection, or a cursor not already at position 0) -- an empty search
    # box's own Backspace behavior (e.g. a multi-select dropdown removing
    # its last chip) passes through untouched.
    dash_app.clientside_callback(
        """
        function() {
            if (!window.__splashBackspaceFixInstalled) {
                window.__splashBackspaceFixInstalled = true;
                document.addEventListener('keydown', function(e) {
                    if ((e.key !== 'Backspace' && e.key !== 'Delete') ||
                        e.ctrlKey || e.metaKey || e.altKey) {
                        return;
                    }
                    var el = document.activeElement;
                    if (!el || el.tagName !== 'INPUT' || el.readOnly || el.disabled) {
                        return;
                    }
                    var isCellInput = el.classList.contains('dash-cell-value');
                    var isDropdownFilter = el.parentElement &&
                        el.parentElement.classList.contains('Select-input');
                    if (!isCellInput && !isDropdownFilter) { return; }
                    var start = el.selectionStart, end = el.selectionEnd;
                    if (start === null || end === null) { return; }
                    var val = el.value;
                    var newVal, newPos;
                    if (start !== end) {
                        newVal = val.slice(0, start) + val.slice(end);
                        newPos = start;
                    } else if (e.key === 'Backspace') {
                        if (start === 0) { return; }
                        newVal = val.slice(0, start - 1) + val.slice(start);
                        newPos = start - 1;
                    } else {
                        if (start >= val.length) { return; }
                        newVal = val.slice(0, start) + val.slice(start + 1);
                        newPos = start;
                    }
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    var setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, newVal);
                    el.setSelectionRange(newPos, newPos);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                }, true);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("splash-backspace-fix", "children"),
        Input("splash-editing", "data"),
    )

