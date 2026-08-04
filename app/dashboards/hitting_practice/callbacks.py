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


def _load_all(exclude_test: bool):
    try:
        pitch = P.load_pitch_coords(exclude_test=exclude_test)
    except Exception:
        pitch = pd.DataFrame()
    try:
        plays = P.load_plays(exclude_test=exclude_test)
    except Exception:
        plays = pd.DataFrame()
    try:
        sessions = P.load_sessions(exclude_test=exclude_test)
    except Exception:
        sessions = pd.DataFrame()
    try:
        stats = P.load_player_stats(exclude_test=exclude_test)
    except Exception:
        stats = pd.DataFrame()
    return pitch, plays, sessions, stats


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
        exclude_test = True
        pitch, _, _, _ = _load_all(exclude_test)
        start = date.fromisoformat(ds[:10]) if ds else None
        end = date.fromisoformat(de[:10]) if de else None
        windowed = P.apply_filters(pitch, player=None, start=start, end=end, session=None)
        base = windowed if not windowed.empty else pitch
        popts = selectors.player_options(base, is_coach=is_coach, own_name=own_name)
        player = selectors.resolve_player(player, is_coach=is_coach, own_name=own_name)
        if player not in {o["value"] for o in popts} and popts:
            player = popts[0]["value"]
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
        pitch, _, _, _ = _load_all(exclude_test)
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        filtered = P.apply_filters(
            pitch,
            player=filt.get("player"),
            start=start, end=end,
            session=filt.get("session"),
        )
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
        player = filt.get("player") or "All Players"
        pitch = _read_json(pitch_json)
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None

        if tab == "zones":
            return pitch_zones.render(pitch)
        if tab == "swing":
            return swing_frequency.render(pitch)
        if tab == "batted":
            _, plays, _, _ = _load_all(exclude_test)
            if not plays.empty and start and end and "play_date" in plays.columns:
                plays = plays[pd.to_datetime(plays["play_date"]).between(
                    pd.Timestamp(start), pd.Timestamp(end))]
            if player != "All Players" and not plays.empty:
                plays = plays[plays["player_name"] == player]
            return batted_ball.render(plays)

        _, plays, sessions, stats = _load_all(exclude_test)
        # Date / player filter on plays & sessions
        if not plays.empty and start and end and "play_date" in plays.columns:
            plays = plays[pd.to_datetime(plays["play_date"]).between(
                pd.Timestamp(start), pd.Timestamp(end))]
        if not sessions.empty and start and end:
            sessions = sessions[pd.to_datetime(sessions["session_date"]).between(
                pd.Timestamp(start), pd.Timestamp(end))]
        if player != "All Players":
            if not plays.empty:
                plays = plays[plays["player_name"] == player]
            if not sessions.empty:
                sessions = sessions[sessions["player_name"] == player]

        if tab == "sessions":
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
        _, plays, _, _ = _load_all(bool(filt.get("exclude_test", True)))
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        player = filt.get("player") or "All Players"
        if not plays.empty and start and end and "play_date" in plays.columns:
            plays = plays[pd.to_datetime(plays["play_date"]).between(
                pd.Timestamp(start), pd.Timestamp(end))]
        if player != "All Players" and not plays.empty:
            plays = plays[plays["player_name"] == player]
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
        pitch, _, _, _ = _load_all(exclude_test)
        from datetime import date
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        player = filt.get("player") or "All Players"
        d = P.apply_filters(pitch, player=player, start=start, end=end,
                            session=filt.get("session"))
        return layout.sidebar(d, player)
