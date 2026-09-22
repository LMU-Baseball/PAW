"""Callbacks for HitTrax practice dashboard."""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
from dash import ALL, Input, Output, State, ctx, dcc, html
from flask_login import current_user

from app.data import practice as P
from app.data import practice_plans as PP
from app.dashboards import date_range as dr
from app.dashboards.hitting_practice import layout, selectors
from app.dashboards.hitting_practice.tabs import (
    batted_ball, pitch_zones, session_tables, swing_frequency,
)


def _read_json(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("prac-daterange", "start_date"), Output("prac-daterange", "end_date"),
        Output("prac-cal-wrap", "style"),
        Input("prac-date-preset", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset):
        from dash import no_update
        show = {"display": "block" if preset == "custom" else "none", "marginTop": "6px"}
        if preset == "custom":
            return no_update, no_update, show
        min_d, _ = P.date_bounds()
        # Anchor rolling-window presets (Past Week/Month/.../Year) on TODAY's
        # real calendar date, not the latest ingested session in the whole
        # table -- anchoring on the latter silently narrows "Past Year" to
        # end at whenever HitTrax was last ingested for ANY player, which
        # can cut off a player whose own last session predates that by more
        # than a year even though it's genuinely within the last 365 days.
        # Matches the season-default anchor already used in layout.py.
        anchor = str(date.today())
        s, e = dr.preset_range(preset, anchor)
        s = max(str(s), str(min_d))
        return s, str(e), show

    @dash_app.callback(
        Output("prac-filters", "data"),
        Output("prac-player", "options"),
        Output("prac-session-dates", "options"),
        Output("prac-plan-assignment-dates", "options"),
        Output("prac-plan-filter", "options"),
        Output("prac-plan-assignment-values", "options"),
        Output("prac-plan-manage-select", "options"),
        Input("prac-player", "value"),
        Input("prac-daterange", "start_date"),
        Input("prac-daterange", "end_date"),
        Input("prac-session-dates", "value"),
        Input("prac-plan-filter", "value"),
    )
    def _on_filters(player, ds, de, selected_dates, selected_plans):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own_name = getattr(current_user, "name", None)
        # Scoped to the selected date range -- a player with no HitTrax data in
        # range shouldn't appear in the dropdown (light query; no pitch load).
        names = P.players_in_range(ds, de)
        popts = selectors.player_options(names, is_coach=is_coach, own_name=own_name)
        start = date.fromisoformat(ds[:10]) if ds else None
        end = date.fromisoformat(de[:10]) if de else None
        player = selectors.resolve_player(player, is_coach=is_coach,
                                          own_name=own_name, available=names)
        available_dates = P.practice_dates(start, end, player=player)
        selected_date = selected_dates or "__all_sessions__"
        if selected_date != "__all_sessions__" and selected_date not in available_dates:
            selected_date = "__all_sessions__"
        plan_names = {p.name for p in PP.list_plans()}
        selected_plans = [p for p in (selected_plans or []) if p in plan_names]
        if selected_plans:
            assignments = PP.assignments_for_dates(available_dates)
            plan_dates = {d for d, names_for_date in assignments.items()
                          if set(names_for_date).intersection(selected_plans)}
            if selected_date == "__all_sessions__":
                effective_dates = plan_dates
            else:
                effective_dates = {selected_date} & plan_dates
        else:
            effective_dates = set(available_dates) if selected_date == "__all_sessions__" else {selected_date}
        return (
            {"player": player,
             "session": "All session types", "exclude_test": True,
             "start": start.isoformat() if start else None,
             "end": end.isoformat() if end else None,
             "session_dates": sorted(effective_dates), "plans": selected_plans},
            popts,
            [{"label": f"All sessions in range ({len(available_dates)})",
              "value": "__all_sessions__"}]
            + [{"label": d, "value": d} for d in available_dates],
            [{"label": d, "value": d} for d in available_dates],
            [{"label": p, "value": p} for p in sorted(plan_names)],
            [{"label": p, "value": p} for p in sorted(plan_names)],
            [{"label": p.name, "value": p.id} for p in PP.list_plans(include_archived=True)],
        )

    @dash_app.callback(
        Output("prac-pitch-data", "data"),
        Input("prac-filters", "data"),
    )
    def _load_pitch(filt):
        filt = filt or {}
        exclude_test = bool(filt.get("exclude_test", True))
        player = filt.get("player")
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        if not player:
            return None
        # Scoped load: only this player's rows for the window (not every player).
        pitch = P.load_pitch_coords(exclude_test=exclude_test, player=player,
                                    start=start, end=end,
                                    dates=filt.get("session_dates"),
                                    plan_names=filt.get("plans"))
        # apply_filters still applies the session filter (player/date already scoped).
        filtered = P.apply_filters(pitch, player=player, start=start, end=end,
                                   session=filt.get("session"),
                                   dates=filt.get("session_dates"))
        return None if filtered.empty else filtered.to_json(orient="split")

    @dash_app.callback(
        Output("prac-tab-content", "children"),
        Input("prac-tabs", "value"),
        Input("prac-pitch-data", "data"),
        Input("prac-filters", "data"),
    )
    def _render(tab, pitch_json, filt):
        filt = filt or {}
        exclude_test = bool(filt.get("exclude_test", True))
        player = filt.get("player")
        pitch = _read_json(pitch_json)
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None

        if tab == "zones":
            return pitch_zones.render(pitch)
        if tab == "swing":
            return swing_frequency.render(pitch)
        if tab == "batted":
            # Scoped: only this player's plays for the window.
            plays = P.load_plays(exclude_test=exclude_test, player=player,
                                 start=start, end=end, dates=filt.get("session_dates"),
                                 plan_names=filt.get("plans"))
            return batted_ball.render(plays)

        if tab == "sessions":
            sessions = P.load_sessions(exclude_test=exclude_test, player=player,
                                       start=start, end=end,
                                       dates=filt.get("session_dates"),
                                       plan_names=filt.get("plans"))
            # Scoped: only this player's summary row (not every active player).
            stats = P.load_player_stats(exclude_test=exclude_test, player=player)
            return session_tables.render(stats, sessions, player=player)
        return html.Div()

    @dash_app.callback(
        Output("pz-heatmap", "children"),
        Input("pz-metric", "value"), State("prac-pitch-data", "data"),
    )
    def _pz_metric(metric, pitch_json):
        from app.dashboards.hitting_practice import charts
        df = _read_json(pitch_json)
        if df.empty:
            return dcc.Graph(figure=charts.pitch_zone_heatmap(df, metric or "contact"))
        d = P.trim_to_first_contact(df)
        return dcc.Graph(figure=charts.pitch_zone_heatmap(d, metric or "contact"))

    @dash_app.callback(
        Output("sfz-active", "data"),
        Input({"type": "sfz-chip", "index": ALL}, "n_clicks"),
        State("sfz-active", "data"), State("sfz-present", "data"),
        prevent_initial_call=True,
    )
    def _sfz_toggle(_clicks, active, present):
        tid = ctx.triggered_id
        if not tid:
            return active
        z = tid["index"]
        present = set(present or [])
        if z not in present:                 # disabled/empty zone -> ignore
            return active
        active = list(active or [])
        return [x for x in active if x != z] if z in active else active + [z]

    @dash_app.callback(
        Output("sf-ev-body", "children"),
        Input("sfz-active", "data"), State("prac-pitch-data", "data"),
    )
    def _sfz_body(active, pitch_json):
        from app.dashboards.hitting_practice.tabs import swing_frequency as sf
        df = _read_json(pitch_json)
        if df.empty:
            return sf.ev_body(df, active)
        return sf.ev_body(P.trim_to_first_contact(df), active)

    @dash_app.callback(
        Output({"type": "sfz-chip", "index": ALL}, "style"),
        Input("sfz-active", "data"),
        State("sfz-present", "data"),
        State({"type": "sfz-chip", "index": ALL}, "id"),
    )
    def _sfz_styles(active, present, ids):
        from app.dashboards.hitting_practice.tabs.swing_frequency import chip_style
        active = set(active or [])
        present = set(present or [])
        return [chip_style(active=i["index"] in active, present=i["index"] in present)
                for i in ids]

    @dash_app.callback(
        Output("sds-active", "data"),
        Input({"type": "sds-chip", "index": ALL}, "n_clicks"),
        State("sds-active", "data"), State("sds-present", "data"),
        prevent_initial_call=True,
    )
    def _sds_toggle(_clicks, active, present):
        tid = ctx.triggered_id
        if not tid:
            return active
        z = tid["index"]
        active = list(active or [])
        return [x for x in active if x != z] if z in active else active + [z]

    @dash_app.callback(
        Output("sds-trend-body", "children"),
        Input("sds-active", "data"), State("prac-pitch-data", "data"),
    )
    def _sds_body(active, pitch_json):
        from app.dashboards.hitting_practice.tabs import swing_frequency as sf
        df = _read_json(pitch_json)
        if df.empty:
            return sf.trend_body(df, active or [])
        return sf.trend_body(P.trim_to_first_contact(df), active or [])

    @dash_app.callback(
        Output({"type": "sds-chip", "index": ALL}, "style"),
        Input("sds-active", "data"),
        State("sds-present", "data"),
        State({"type": "sds-chip", "index": ALL}, "id"),
    )
    def _sds_styles(active, present, ids):
        from app.dashboards.hitting_practice.tabs.swing_frequency import chip_style
        active = set(active or [])
        present = set(present or [])
        return [chip_style(active=i["index"] in active, present=i["index"] in present)
                for i in ids]

    @dash_app.callback(
        Output("bb-active", "data"),
        Input({"type": "bb-chip", "index": ALL}, "n_clicks"),
        State("bb-active", "data"), State("bb-present", "data"),
        prevent_initial_call=True,
    )
    def _bb_toggle(_clicks, active, present):
        tid = ctx.triggered_id
        if not tid:
            return active
        label = tid["index"]
        present = set(present or [])
        if label not in present:
            return active
        active = list(active or [])
        return [x for x in active if x != label] if label in active else active + [label]

    @dash_app.callback(
        Output({"type": "bb-chip", "index": ALL}, "style"),
        Input("bb-active", "data"),
        State({"type": "bb-chip", "index": ALL}, "id"),
    )
    def _bb_styles(active, ids):
        from app.dashboards.hitting_practice.tabs.batted_ball import bb_chip_style
        active = set(active or [])
        return [bb_chip_style(P.HIT_TYPE_COLORS.get(i["index"], "#5a5a5a"),
                              active=i["index"] in active) for i in ids]

    @dash_app.callback(
        Output("bb-body", "children"),
        Input("bb-active", "data"),
        State("prac-filters", "data"),
    )
    def _bb_body(active, filt):
        from app.dashboards.hitting_practice.tabs import batted_ball
        filt = filt or {}
        player = filt.get("player")
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        plays = P.load_plays(exclude_test=bool(filt.get("exclude_test", True)),
                             player=player, start=start, end=end,
                             dates=filt.get("session_dates"),
                             plan_names=filt.get("plans"))
        if plays.empty:
            return html.Div("No batted-ball data for these filters.",
                            style={"color": "#555", "padding": "12px"})
        return batted_ball.body(plays, active)

    @dash_app.callback(
        Output("prac-plan-status", "children"),
        Input("prac-plan-save", "n_clicks"),
        State("prac-plan-assignment-dates", "value"),
        State("prac-plan-assignment-values", "value"),
        prevent_initial_call=True,
    )
    def _save_plan_assignments(_clicks, dates, plans):
        if not getattr(current_user, "is_coach", False):
            return "Only coaches may assign practice plans."
        try:
            PP.replace_assignments(dates or [], plans or [],
                                   actor_is_coach=True,
                                   actor_id=getattr(current_user, "id", None))
        except (ValueError, PermissionError) as exc:
            return str(exc)
        return f"Updated assignments for {len(dates or [])} date(s)."

    @dash_app.callback(
        Output("prac-plan-status", "children", allow_duplicate=True),
        Input("prac-plan-rename-button", "n_clicks"),
        State("prac-plan-manage-select", "value"),
        State("prac-plan-rename", "value"),
        prevent_initial_call=True,
    )
    def _rename_plan(_clicks, plan_id, name):
        if not getattr(current_user, "is_coach", False):
            return "Only coaches may manage practice plans."
        try:
            PP.rename_plan(plan_id, name or "", actor_is_coach=True)
        except (ValueError, PermissionError) as exc:
            return str(exc)
        return "Practice plan renamed. Reload the page to refresh the labels."

    @dash_app.callback(
        Output("prac-plan-status", "children", allow_duplicate=True),
        Input("prac-plan-archive", "n_clicks"),
        State("prac-plan-manage-select", "value"),
        prevent_initial_call=True,
    )
    def _archive_plan(_clicks, plan_id):
        if not getattr(current_user, "is_coach", False):
            return "Only coaches may manage practice plans."
        try:
            PP.archive_plan(plan_id, actor_is_coach=True)
        except (ValueError, PermissionError) as exc:
            return str(exc)
        return "Practice plan archived. Historical assignments were preserved."

    @dash_app.callback(
        Output("prac-plan-status", "children", allow_duplicate=True),
        Input("prac-plan-add", "n_clicks"),
        State("prac-plan-new-name", "value"),
        prevent_initial_call=True,
    )
    def _add_plan(_clicks, name):
        if not getattr(current_user, "is_coach", False):
            return "Only coaches may manage practice plans."
        try:
            PP.create_plan(name or "", actor_is_coach=True)
        except (ValueError, PermissionError) as exc:
            return str(exc)
        return "Practice plan added. Reload the page to use it."

    @dash_app.callback(
        Output("prac-sidebar", "children"),
        Input("prac-filters", "data"),
    )
    def _sidebar(filt):
        filt = filt or {}
        exclude_test = bool(filt.get("exclude_test", True))
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        player = filt.get("player")
        pitch = (P.load_pitch_coords(exclude_test=exclude_test, player=player,
                                     start=start, end=end,
                                     dates=filt.get("session_dates"),
                                     plan_names=filt.get("plans"))
                 if player else pd.DataFrame())
        d = P.apply_filters(pitch, player=player, start=start, end=end,
                            session=filt.get("session"),
                            dates=filt.get("session_dates"))
        return layout.sidebar(d, player)
