"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import catching as C
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.dashboards.catching import charts, layout, selectors
from app.dashboards.catching.tabs import framing, static_framing, caught_stealing


def _read_game_df(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("cat-daterange", "start_date"), Output("cat-daterange", "end_date"),
        Input("catcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_catcher_range(catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        g = C.games_for_catcher(cid) if cid else None
        if g is None or g.empty:
            return None, None
        return str(g["game_date"].min()), str(g["game_date"].max())

    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("cat-daterange", "start_date"), Input("cat-daterange", "end_date"),
        State("catcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        if not cid or not start or not end:
            return [], None
        g = C.games_for_catcher(cid, start=start, end=end)
        opts = dr.game_options(g)
        value = int(g.iloc[0]["game_id"]) if not g.empty else None  # empty range -> no value (sentinel isn't an option when 0 games)
        return opts, value

    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("catcher-dd", "value"), Input("game-dd", "value"),
        State("cat-daterange", "start_date"), State("cat-daterange", "end_date"),
    )
    def _on_selection(catcher_id, game_id, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = C.games_for_catcher(cid, start=start, end=end) if cid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"catcher_id": cid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(cid), sb)

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("catcher_id") is None:
            return None
        gid = sel.get("game_id")
        if gid == dr.ALL_IN_RANGE:
            if not sel.get("start") or not sel.get("end"):
                return None
            df = C.range_pitches_for(int(sel["catcher_id"]), sel["start"], sel["end"])
        elif gid is None:
            return None
        else:
            df = C.game_pitches_for(int(gid), int(sel["catcher_id"]))
        return None if df.empty else df.to_json(orient="split")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        if tab == "pitchlevel":
            sel = sel or {}
            cid = sel.get("catcher_id")
            if cid is None:
                return html.Div("Select a catcher.", style={"padding": "12px", "color": "#555"})
            gid = sel.get("game_id")
            if gid == dr.ALL_IN_RANGE:
                g = C.games_for_catcher(int(cid), start=sel.get("start"), end=sel.get("end"))
                gids = [int(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select a game.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [int(gid)]
            vdf = videodata.pitch_video_df(gids, catcher_id=int(cid))
            return videotab.render(vdf, prefix="cat", default_angle="HomeBehind")
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "framing":
            return framing.render(df)
        if tab == "static":
            return static_framing.render(df)
        if tab == "caught":
            return caught_stealing.render(df)
        return html.Div()

    @dash_app.callback(
        Output("fr-body", "children"),
        Input("fr-bat", "value"), Input("fr-throws", "value"),
        Input("fr-speed", "value"), Input("fr-zone", "value"),
        Input("call-active", "data"),
        State("game-data", "data"),
    )
    def _framing_body(bat, throws, speed, zone, active_calls, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        return framing.body(df, bat_side=bat or "All", pitcher_throws=throws or "All",
                            pitch_speed=speed or "All", zone=zone or "All",
                            active_calls=active_calls)

    @dash_app.callback(
        Output("call-active", "data"),
        Input({"type": "call-chip", "index": ALL}, "n_clicks"),
        State("call-active", "data"),
        prevent_initial_call=True,
    )
    def _call_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        ct = tid["index"]
        active = list(active or [])
        return [c for c in active if c != ct] if ct in active else active + [ct]

    @dash_app.callback(
        Output({"type": "call-chip", "index": ALL}, "style"),
        Input("call-active", "data"),
        State({"type": "call-chip", "index": ALL}, "id"),
    )
    def _call_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            ct = i["index"]; col = charts.CALLTYPE_COLORS[ct]; on = ct in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out

    @dash_app.callback(
        Output("static-call-active", "data"),
        Input({"type": "static-call-chip", "index": ALL}, "n_clicks"),
        State("static-call-active", "data"),
        prevent_initial_call=True,
    )
    def _static_call_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        ct = tid["index"]
        active = list(active or [])
        return [c for c in active if c != ct] if ct in active else active + [ct]

    @dash_app.callback(
        Output("static-body", "children"),
        Input("static-call-active", "data"), State("game-data", "data"),
    )
    def _static_body(active, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        return static_framing.body(df, active_calls=active)

    @dash_app.callback(
        Output({"type": "static-call-chip", "index": ALL}, "style"),
        Input("static-call-active", "data"),
        State({"type": "static-call-chip", "index": ALL}, "id"),
    )
    def _static_call_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            ct = i["index"]; col = charts.CALLTYPE_COLORS[ct]; on = ct in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out

    videotab.register_callbacks(dash_app, "cat", default_angle="HomeBehind")
    notes_ui.register_note_callbacks(dash_app, "catching", "catcher_id")
