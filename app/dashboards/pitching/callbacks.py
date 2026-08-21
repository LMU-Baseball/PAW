"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import pitching as P
from app.data import pitching_caps
from app.data import video as videodata
from app.dashboards import background_warm, date_range as dr, notes_ui, video as videotab
from app.dashboards.pitching import layout, selectors
from app.dashboards.pitching.tabs import (last_outings, location_movement,
                                          pitch_breakdown, counts, heatmaps)


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
        g = pitching_caps.games_for_pitcher(int(pid), start=sel["start"], end=sel["end"])
        return str(g.iloc[0]["game_id"]) if not g.empty else None
    return gid


def register_callbacks(dash_app) -> None:

    # Season (outer scope) change -> rescope roster + full-season date range +
    # calendar bounds. pitcher/outing/sidebar/scoreboard cascade from these.
    @dash_app.callback(
        Output("pitcher-dd", "options"), Output("pitcher-dd", "value"),
        Output("pit-daterange", "start_date"), Output("pit-daterange", "end_date"),
        Output("pit-daterange", "min_date_allowed"),
        Output("pit-daterange", "max_date_allowed"),
        Output("pit-date-preset", "value"),
        Input("pit-season", "value"),
        prevent_initial_call=True,
    )
    def _on_season(season):
        from app.data import seasons
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pitchers = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                             season=season)
        default_pitcher = selectors.resolve_pitcher(
            pitchers[0]["value"] if pitchers else None,
            is_coach=is_coach, own_trackman_id=own)
        s_b, e_b = seasons.season_bounds(season)
        return pitchers, default_pitcher, s_b, e_b, s_b, e_b, "season"

    # Preset -> date range (nested inside the selected season).
    @dash_app.callback(
        Output("pit-daterange", "start_date", allow_duplicate=True),
        Output("pit-daterange", "end_date", allow_duplicate=True),
        Output("pit-cal-wrap", "style"),
        Input("pit-date-preset", "value"),
        State("pit-season", "value"), State("pitcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset, season, pitcher_id):
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
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        g = pitching_caps.games_for_pitcher(pid, s_b, e_b) if pid else None
        anchor = str(g["game_date"].max()) if (g is not None and not g.empty) else e_b
        s, e = dr.preset_range(preset, anchor)
        s = max(str(s), s_b); e = min(str(e), e_b)  # nest inside the season
        return s, str(e), show

    # Date-range change -> refresh the pitcher dropdown to only those with data
    # in range (coach-only; a player's own option is never filtered by date --
    # pitcher_options's is_coach=False branch ignores start/end -- so date-range
    # filtering can never hide a player from their own dashboard). Keep the
    # current selection if it's still valid, else fall back to the first
    # available pitcher.
    @dash_app.callback(
        Output("pitcher-dd", "options", allow_duplicate=True),
        Output("pitcher-dd", "value", allow_duplicate=True),
        Input("pit-daterange", "start_date"), Input("pit-daterange", "end_date"),
        State("pit-season", "value"), State("pitcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_daterange_pitchers(start, end, season, current_pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        opts = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                         season=season, start=start, end=end)
        values = {o["value"] for o in opts}
        value = current_pitcher_id if current_pitcher_id in values else (
            opts[0]["value"] if opts else None)
        return opts, value

    # Pitcher or date-range change -> refresh the outing options for that pitcher
    # (pitcher-dd is an Input, not State, so switching pitchers re-lists their
    # outings rather than keeping the previous/default pitcher's).
    @dash_app.callback(
        Output("outing-dd", "options"), Output("outing-dd", "value"),
        Input("pit-daterange", "start_date"), Input("pit-daterange", "end_date"),
        Input("pitcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        if not pid or not start or not end:
            return [], None
        g = pitching_caps.games_for_pitcher(pid, start=start, end=end)
        opts = dr.game_options(g, videodata.video_game_ids(g, pitcher_id=pid))
        value = str(g.iloc[0]["game_id"]) if not g.empty else None  # empty range -> no value
        # Layer 3: warm the all-in-range pitch pull in the background (the
        # default view is a single game; switching to "All in range" is
        # otherwise cold).
        if pid:
            background_warm.warm_async(
                lambda: pitching_caps.range_pitches_for(int(pid), start, end))
        return opts, value

    # Pitcher/date-range -> sidebar. The KPI tiles are date-range-driven (the
    # season's bounds rescope them automatically), but the development callout
    # below them is season-over-season, so the season IS an Input here: it has
    # to agree with the `pit-season` dropdown, not with whatever range happens
    # to be selected inside it.
    @dash_app.callback(
        Output("sidebar", "children"),
        Input("pitcher-dd", "value"),
        Input("pit-daterange", "start_date"), Input("pit-daterange", "end_date"),
        Input("pit-season", "value"),
        prevent_initial_call=True,
    )
    def _on_sidebar(pitcher_id, start, end, season):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        return layout.sidebar(pid, start, end, season)

    # Selection -> selection store + scoreboard (fresh season/dates as Inputs).
    @dash_app.callback(
        Output("selection", "data"), Output("scoreboard", "children"),
        Input("pitcher-dd", "value"), Input("outing-dd", "value"),
        Input("pit-daterange", "start_date"), Input("pit-daterange", "end_date"),
        Input("pit-season", "value"),
    )
    def _on_selection(pitcher_id, game_id, start, end, season):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = pitching_caps.games_for_pitcher(pid, start=start, end=end) if pid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"pitcher_id": pid, "game_id": game_id, "season": season,
                 "start": start, "end": end}, sb)

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("pitcher_id") is None:
            return None
        gid = sel.get("game_id")
        if gid == dr.ALL_IN_RANGE:
            if not sel.get("start") or not sel.get("end"):
                return None
            df = pitching_caps.range_pitches_for(int(sel["pitcher_id"]), sel["start"], sel["end"])
        elif gid is None:
            return None
        else:
            df = pitching_caps.game_pitches_for(str(gid), int(sel["pitcher_id"]))
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
                g = pitching_caps.games_for_pitcher(int(pid), start=sel.get("start"), end=sel.get("end"))
                gids = [str(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select an outing.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [str(gid)]
            vdf = videodata.pitch_video_df(gids, pitcher_id=int(pid))
            # Coach prefers the center-field (Broadcast) camera; the component
            # falls back to another angle when a pitch has no broadcast clip.
            return videotab.render(vdf, prefix="pit", default_angle="Broadcast")
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "breakdown":
            return pitch_breakdown.render(df)
        if tab == "location":
            # The year-over-year panel needs more than this selection's pitches:
            # hand the tab the pitcher and the selected season so it can pull
            # the two full seasons itself (same shape as the Outing Overview
            # dispatch above, which is also handed ids rather than a frame).
            sel = sel or {}
            return location_movement.render(df, sel.get("pitcher_id"),
                                            sel.get("season"))
        if tab == "counts":
            return counts.render(df)
        if tab == "heatmaps":
            return heatmaps.render(df)
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

    # Active-set / filters (or new data) -> re-render movement + location + table.
    @dash_app.callback(
        Output("lm-body", "children"),
        Input("lm-active", "data"), Input("lm-count", "value"),
        Input("lm-result", "value"), Input("lm-hand", "value"),
        State("game-data", "data"),
    )
    def _lm_body(active, counts_sel, results_sel, hand, data_json):
        df = _read_game_df(data_json)
        df = location_movement.apply_filters(
            df, pitch_types=active, counts=counts_sel,
            results=results_sel, hand=hand or "All")
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
        Output("counts-body", "children"),
        Input("counts-dd", "value"), State("game-data", "data"),
    )
    def _counts_body(sel_counts, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.", style={"padding": "12px", "color": "#555"})
        if sel_counts is not None:
            cs = (df["balls"].astype("Int64").astype(str) + "-"
                  + df["strikes"].astype("Int64").astype(str))
            df = df[cs.isin(sel_counts)]
        return counts.body(df)

    @dash_app.callback(
        Output("hm-body", "children"),
        Input("hm-pt", "value"), Input("hm-side", "value"), Input("hm-count", "value"),
        State("game-data", "data"),
    )
    def _hm_body(pts, side, sel_counts, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.", style={"padding": "12px", "color": "#555"})
        if pts is not None:
            df = df[P.pitch_type(df).isin(pts)]
        if side and side != "All":
            df = df[df["batter_side"] == side]
        if sel_counts is not None:
            cs = (df["balls"].astype("Int64").astype(str) + "-"
                  + df["strikes"].astype("Int64").astype(str))
            df = df[cs.isin(sel_counts)]
        return heatmaps.body(df)

    videotab.register_callbacks(dash_app, "pit", default_angle="Broadcast")
    notes_ui.register_note_callbacks(dash_app, "pitching", "pitcher_id")
