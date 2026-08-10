"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import catching_caps
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.dashboards.catching import charts, layout, selectors
from app.dashboards.catching.tabs import framing, static_framing, caught_stealing


def _read_game_df(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    # Season (outer scope) change -> rescope roster + full-season date range +
    # calendar bounds. catcher/game/sidebar/scoreboard cascade from these outputs.
    @dash_app.callback(
        Output("catcher-dd", "options"), Output("catcher-dd", "value"),
        Output("cat-daterange", "start_date"), Output("cat-daterange", "end_date"),
        Output("cat-daterange", "min_date_allowed"),
        Output("cat-daterange", "max_date_allowed"),
        Output("cat-date-preset", "value"),
        Input("cat-season", "value"),
        prevent_initial_call=True,
    )
    def _on_season(season):
        from app.data import seasons
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        catchers = selectors.catcher_options(is_coach=is_coach, own_trackman_id=own,
                                             season=season)
        default_catcher = selectors.resolve_catcher(
            catchers[0]["value"] if catchers else None,
            is_coach=is_coach, own_trackman_id=own)
        s_b, e_b = seasons.season_bounds(season)
        return catchers, default_catcher, s_b, e_b, s_b, e_b, "season"

    # Preset -> date range (nested inside the selected season).
    @dash_app.callback(
        Output("cat-daterange", "start_date", allow_duplicate=True),
        Output("cat-daterange", "end_date", allow_duplicate=True),
        Output("cat-cal-wrap", "style"),
        Input("cat-date-preset", "value"),
        State("cat-season", "value"), State("catcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset, season, catcher_id):
        from dash import no_update
        from app.data import seasons
        show = {"display": "block" if preset == "custom" else "none", "marginTop": "6px"}
        if preset == "custom":
            return no_update, no_update, show
        s_b, e_b = seasons.season_bounds(season)
        if preset == "season":
            return s_b, e_b, show  # "This Season" == the whole selected academic year
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        g = catching_caps.games_for_catcher(cid, s_b, e_b) if cid else None
        anchor = str(g["game_date"].max()) if (g is not None and not g.empty) else e_b
        s, e = dr.preset_range(preset, anchor)
        s = max(str(s), s_b); e = min(str(e), e_b)  # nest inside the season
        return s, str(e), show

    # Date-range change -> refresh the catcher dropdown to only those with data
    # in range (coach-only; a player's own option is never filtered by date --
    # catcher_options's is_coach=False branch ignores start/end -- so date-range
    # filtering can never hide a player from their own dashboard). Keep the
    # current selection if it's still valid, else fall back to the first
    # available catcher.
    @dash_app.callback(
        Output("catcher-dd", "options", allow_duplicate=True),
        Output("catcher-dd", "value", allow_duplicate=True),
        Input("cat-daterange", "start_date"), Input("cat-daterange", "end_date"),
        State("cat-season", "value"), State("catcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_daterange_catchers(start, end, season, current_catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        opts = selectors.catcher_options(is_coach=is_coach, own_trackman_id=own,
                                         season=season, start=start, end=end)
        values = {o["value"] for o in opts}
        value = current_catcher_id if current_catcher_id in values else (
            opts[0]["value"] if opts else None)
        return opts, value

    # Catcher or date-range change -> refresh the game options for that catcher
    # (catcher-dd is an Input, not State, so switching catchers re-lists their
    # games rather than keeping the previous/default catcher's).
    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("cat-daterange", "start_date"), Input("cat-daterange", "end_date"),
        Input("catcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        if not cid or not start or not end:
            return [], None
        g = catching_caps.games_for_catcher(cid, start=start, end=end)
        opts = dr.game_options(g, videodata.video_game_ids(g, catcher_id=cid))
        value = str(g.iloc[0]["game_id"]) if not g.empty else None  # empty range -> no value (sentinel isn't an option when 0 games); game_id is an opaque string
        return opts, value

    # Catcher/season/date-range -> sidebar (tiles rescope to the selected range;
    # when the range equals the season's bounds, framing_season_tiles reads the
    # fast precalc rollup, so the default "This Season" view is unchanged).
    @dash_app.callback(
        Output("sidebar", "children"),
        Input("catcher-dd", "value"), Input("cat-season", "value"),
        Input("cat-daterange", "start_date"), Input("cat-daterange", "end_date"),
        prevent_initial_call=True,
    )
    def _on_sidebar(catcher_id, season, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        return layout.sidebar(cid, season, start, end)

    # Selection -> selection store + scoreboard (fresh season/dates as Inputs).
    @dash_app.callback(
        Output("selection", "data"), Output("scoreboard", "children"),
        Input("catcher-dd", "value"), Input("game-dd", "value"),
        Input("cat-daterange", "start_date"), Input("cat-daterange", "end_date"),
        Input("cat-season", "value"),
    )
    def _on_selection(catcher_id, game_id, start, end, season):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = catching_caps.games_for_catcher(cid, start=start, end=end) if cid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"catcher_id": cid, "game_id": game_id, "season": season,
                 "start": start, "end": end}, sb)

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("catcher_id") is None:
            return None
        gid = sel.get("game_id")
        if gid == dr.ALL_IN_RANGE:
            if not sel.get("start") or not sel.get("end"):
                return None
            df = catching_caps.range_pitches_for(int(sel["catcher_id"]), sel["start"], sel["end"])
        elif gid is None:
            return None
        else:
            df = catching_caps.game_pitches_for(str(gid), int(sel["catcher_id"]))
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
                g = catching_caps.games_for_catcher(int(cid), start=sel.get("start"), end=sel.get("end"))
                gids = [str(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select a game.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [str(gid)]
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
