"""Callbacks for HitTrax practice dashboard."""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
from dash import ALL, Input, Output, State, ctx, dcc, html
from flask_login import current_user

from app.data import practice as P
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
        min_d, max_d = P.date_bounds()
        anchor = str(max_d)
        s, e = dr.preset_range(preset, anchor)
        s = max(str(s), str(min_d))
        return s, str(e), show

    @dash_app.callback(
        Output("prac-filters", "data"),
        Output("prac-player", "options"),
        Input("prac-player", "value"),
        Input("prac-daterange", "start_date"),
        Input("prac-daterange", "end_date"),
    )
    def _on_filters(player, ds, de):
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
        return (
            {"player": player,
             "session": "All session types", "exclude_test": True,
             "start": start.isoformat() if start else None,
             "end": end.isoformat() if end else None},
            popts,
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
                                    start=start, end=end)
        # apply_filters still applies the session filter (player/date already scoped).
        filtered = P.apply_filters(pitch, player=player, start=start, end=end,
                                   session=filt.get("session"))
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
                                 start=start, end=end)
            return batted_ball.render(plays)

        if tab == "sessions":
            sessions = P.load_sessions(exclude_test=exclude_test, player=player,
                                       start=start, end=end)
            stats = P.load_player_stats(exclude_test=exclude_test)  # small summary table
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
                             player=player, start=start, end=end)
        if plays.empty:
            return html.Div("No batted-ball data for these filters.",
                            style={"color": "#555", "padding": "12px"})
        return batted_ball.body(plays, active)

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
                                     start=start, end=end)
                 if player else pd.DataFrame())
        d = P.apply_filters(pitch, player=player, start=start, end=end,
                            session=filt.get("session"))
        return layout.sidebar(d, player)
