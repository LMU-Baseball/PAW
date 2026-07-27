"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import pitching as P
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.dashboards.pitching import layout, selectors
from app.dashboards.pitching.tabs import last_outings, location_movement, pitch_breakdown, rhh_lhh


def _read_game_df(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def _outings_anchor(sel):
    """Resolve the Last-Outings anchor game_id (sentinel -> most-recent in-range game)."""
    sel = sel or {}
    gid = sel.get("game_id")
    if gid == dr.ALL_IN_RANGE:
        pid = sel.get("pitcher_id")
        if not pid or not sel.get("start") or not sel.get("end"):
            return None
        g = P.games_for_pitcher(int(pid), start=sel["start"], end=sel["end"])
        return int(g.iloc[0]["game_id"]) if not g.empty else None
    return gid


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("pit-daterange", "start_date"), Output("pit-daterange", "end_date"),
        Input("pitcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_pitcher_range(pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        g = P.games_for_pitcher(pid) if pid else None
        if g is None or g.empty:
            return None, None
        return str(g["game_date"].min()), str(g["game_date"].max())

    @dash_app.callback(
        Output("outing-dd", "options"), Output("outing-dd", "value"),
        Input("pit-daterange", "start_date"), Input("pit-daterange", "end_date"),
        State("pitcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        if not pid or not start or not end:
            return [], None
        g = P.games_for_pitcher(pid, start=start, end=end)
        opts = dr.game_options(g)
        value = int(g.iloc[0]["game_id"]) if not g.empty else None
        return opts, value

    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("pitcher-dd", "value"), Input("outing-dd", "value"),
        State("pit-daterange", "start_date"), State("pit-daterange", "end_date"),
    )
    def _on_selection(pitcher_id, game_id, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = P.games_for_pitcher(pid, start=start, end=end) if pid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"pitcher_id": pid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(pid), sb)

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("pitcher_id") is None:
            return None
        gid = sel.get("game_id")
        if gid == dr.ALL_IN_RANGE:
            if not sel.get("start") or not sel.get("end"):
                return None
            df = P.range_pitches_for(int(sel["pitcher_id"]), sel["start"], sel["end"])
        elif gid is None:
            return None
        else:
            df = P.game_pitches_for(int(gid), int(sel["pitcher_id"]))
        return None if df.empty else df.to_json(orient="split")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        if tab == "outings":
            sel = sel or {}
            anchor = _outings_anchor(sel)
            return last_outings.render(sel.get("pitcher_id"), anchor, 5)
        if tab == "pitchlevel":
            sel = sel or {}
            pid = sel.get("pitcher_id")
            if pid is None:
                return html.Div("Select a pitcher.", style={"padding": "12px", "color": "#555"})
            gid = sel.get("game_id")
            if gid == dr.ALL_IN_RANGE:
                g = P.games_for_pitcher(int(pid), start=sel.get("start"), end=sel.get("end"))
                gids = [int(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select an outing.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [int(gid)]
            vdf = videodata.pitch_video_df(gids, pitcher_id=int(pid))
            return videotab.render(vdf, prefix="pit", default_angle="HomeBehind")
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "breakdown":
            return pitch_breakdown.render(df)
        if tab == "location":
            return location_movement.render(df)
        if tab == "splits":
            return rhh_lhh.render(df)
        return html.Div()

    @dash_app.callback(
        Output("lo-body", "children"),
        Input("lo-count-dd", "value"), State("selection", "data"),
    )
    def _lo_body(n, sel):
        sel = sel or {}
        return last_outings.body(sel.get("pitcher_id"), _outings_anchor(sel), n or 5)

    # Chip click -> toggle the pitch type in the active-set store.
    @dash_app.callback(
        Output("lm-active", "data"),
        Input({"type": "lm-chip", "index": ALL}, "n_clicks"),
        State("lm-active", "data"),
        prevent_initial_call=True,
    )
    def _lm_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]
        active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    # Active-set (or new data) -> re-render movement + location + table, filtered.
    @dash_app.callback(
        Output("lm-body", "children"),
        Input("lm-active", "data"), State("game-data", "data"),
    )
    def _lm_body(active, data_json):
        df = _read_game_df(data_json)
        if not df.empty and active is not None:
            df = df[P.pitch_type(df).isin(active)]
        return location_movement.body(df)

    # Give the active chips a visual "off" state: dim deselected chips.
    @dash_app.callback(
        Output({"type": "lm-chip", "index": ALL}, "style"),
        Input("lm-active", "data"),
        State({"type": "lm-chip", "index": ALL}, "id"),
    )
    def _lm_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = P.pitch_color(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out

    @dash_app.callback(
        Output("splits-active", "data"),
        Input({"type": "splits-chip", "index": ALL}, "n_clicks"),
        State("splits-active", "data"), prevent_initial_call=True,
    )
    def _splits_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]; active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    @dash_app.callback(
        Output("splits-body", "children"),
        Input("splits-active", "data"), State("game-data", "data"),
    )
    def _splits_body(active, data_json):
        df = _read_game_df(data_json)
        if not df.empty and active is not None:
            df = df[P.pitch_type(df).isin(active)]
        return rhh_lhh.body(df)

    @dash_app.callback(
        Output({"type": "splits-chip", "index": ALL}, "style"),
        Input("splits-active", "data"),
        State({"type": "splits-chip", "index": ALL}, "id"),
    )
    def _splits_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = P.pitch_color(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col, "borderRadius": "14px",
                        "padding": "3px 12px", "margin": "0 6px 6px 0",
                        "cursor": "pointer", "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out

    videotab.register_callbacks(dash_app, "pit", default_angle="HomeBehind")
    notes_ui.register_note_callbacks(dash_app, "pitching", "pitcher_id")
