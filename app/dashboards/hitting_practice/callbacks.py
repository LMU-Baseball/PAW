"""Callbacks for HitTrax practice dashboard."""
from __future__ import annotations

import io
from datetime import date
from datetime import date as _date

import pandas as pd
from dash import Input, Output, ctx, html
from flask_login import current_user

from app.data import practice as P
from app.dashboards.hitting_practice import selectors
from app.dashboards.hitting_practice.tabs import (
    contact_overview, pitch_zones, session_tables, swing_frequency,
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
        Output("prac-filters", "data"),
        Output("prac-player", "options"),
        Output("prac-session", "options"),
        Output("prac-daterange", "start_date"),
        Output("prac-daterange", "end_date"),
        Input("prac-date-preset", "value"),
        Input("prac-player", "value"),
        Input("prac-session", "value"),
        Input("prac-exclude-test", "value"),
        Input("prac-daterange", "start_date"),
        Input("prac-daterange", "end_date"),
    )
    def _on_filters(preset, player, session, exclude_vals, ds, de):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own_name = getattr(current_user, "name", None)
        exclude_test = "exclude" in (exclude_vals or [])
        pitch, _, _, _ = _load_all(exclude_test)
        # Calendar edit wins when it fired; otherwise the preset drives the window.
        if ctx.triggered_id == "prac-daterange" and ds and de:
            start = _date.fromisoformat(ds[:10])
            end = _date.fromisoformat(de[:10])
        else:
            start, end = P.preset_date_range(preset or "Custom")
        # Narrow player list to selected date window for discoverability
        windowed = P.apply_filters(pitch, player=None, start=start, end=end, session=None)
        base = windowed if not windowed.empty else pitch
        popts = selectors.player_options(base, is_coach=is_coach, own_name=own_name)
        sopts = [{"label": s, "value": s} for s in P.session_options(base)]
        player = selectors.resolve_player(player, is_coach=is_coach, own_name=own_name)
        if player not in {o["value"] for o in popts} and popts:
            player = popts[0]["value"]
        return (
            {"player": player, "preset": preset or "Custom",
             "session": session or "All session types",
             "exclude_test": exclude_test,
             "start": start.isoformat(), "end": end.isoformat()},
            popts, sopts, start.isoformat(), end.isoformat(),
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

        if tab == "contact":
            return contact_overview.render(plays, stats, player=player)
        if tab == "sessions":
            return session_tables.render(stats, sessions, player=player)
        return html.Div()
