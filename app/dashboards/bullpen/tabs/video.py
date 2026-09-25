"""Video tab -- one bullpen session's pitches, click a row to play that
pitch's Edgertronic clip. Mirrors `app.dashboards.video.component`'s
table+player look and row-click interaction, but built fresh rather than
reused: bullpen has exactly one camera (Edgertronic), not the multi-angle
toggle that component's table/callbacks are built around.
"""
from __future__ import annotations

from dash import Input, Output, State, dash_table, html, no_update

from app.dashboards import shell
from app.data import bullpen_video as BV

_MUTED = {"padding": "12px", "color": "#555"}

_DISPLAY_COLS = ["pitch_no", "pitch_type", "velo", "result", "pocket", "horz_break",
                 "ind_vert_break"]
_HEADERS = {"pitch_no": "Pitch #", "pitch_type": "Pitch", "velo": "Velo", "result": "Zone",
           "pocket": "Pocket", "horz_break": "HB", "ind_vert_break": "IVB"}


def render(pitcher_id, date) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    if not date:
        return html.Div("No bullpen session in this date range.", style=_MUTED)
    df = BV.session_pitch_video_df(int(pitcher_id), date)
    if df.empty:
        return html.Div("No pitches for this session.", style=_MUTED)

    display = df[_DISPLAY_COLS + ["play_id", "has_video"]].copy()
    display["velo"] = display["velo"].round(1)
    display["horz_break"] = display["horz_break"].round(1)
    display["ind_vert_break"] = display["ind_vert_break"].round(1)
    table = dash_table.DataTable(
        id="bp-video-table",
        columns=[{"name": _HEADERS[c], "id": c} for c in _DISPLAY_COLS],
        data=display.to_dict("records"),  # play_id/has_video ride along hidden
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": shell.CRIMSON, "color": "white", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"state": "active"}, "backgroundColor": "rgba(154,0,33,.15)",
             "border": f"1px solid {shell.CRIMSON}"},
        ],
    )
    player = html.Video(
        id="bp-video-player", controls=True, autoPlay=True, muted=True, preload="auto",
        children=html.Source(id="bp-video-source", src="", type="video/mp4"),
        style={"width": "100%", "borderRadius": "8px", "background": "#000"})
    reload_sink = html.Div(id="bp-video-reload", style={"display": "none"})
    # LMU-branded downloadable clip (2026-09-23, Brad: players want to
    # download their best pitches, with pitch type/velo/break + zone +
    # movement burned onto the video, to share with recruiters). A plain
    # <a download> to the Flask route (app.main.routes.bullpen_video_
    # download) -- the browser's own native download handling, no dcc.
    # Download/clientside plumbing needed. `href=""` (falsy) until a pitch
    # with video is selected, matching the player's own empty-src state.
    download_link = html.A(
        "Download with pitch data", id="bp-video-download", href="",
        download="", target="_blank",
        style={"display": "none", "marginTop": "8px", "padding": "6px 14px",
              "backgroundColor": shell.CRIMSON, "color": "white", "borderRadius": "6px",
              "textDecoration": "none", "fontFamily": "Teko, sans-serif", "fontSize": "15px"})

    return html.Div([
        html.Div([
            html.Div([
                html.Div("Click a pitch row to load video.", id="bp-video-hint",
                         style={"color": "#555", "marginBottom": "6px"}),
                player,
                reload_sink,
                download_link,
            ], className="paw-video-media", style={"flex": "2", "minWidth": "480px"}),
            html.Div([table], className="paw-video-table", style={"flex": "1", "minWidth": "300px"}),
        ], className="paw-video-row",
           style={"display": "flex", "gap": "16px", "alignItems": "flex-start"}),
    ])


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("bp-video-source", "src"),
        Output("bp-video-hint", "children"),
        Output("bp-video-download", "href"),
        Output("bp-video-download", "download"),
        Output("bp-video-download", "style"),
        Input("bp-video-table", "active_cell"),
        State("bp-video-table", "derived_viewport_data"),
        State("bp-video-download", "style"),
        prevent_initial_call=True,
    )
    def _select(active, rows, download_style):
        hidden = {**download_style, "display": "none"}
        if not active or not rows:
            return no_update, no_update, no_update, no_update, no_update
        i = active.get("row")
        if i is None or i >= len(rows):
            return no_update, no_update, no_update, no_update, no_update
        row = rows[i]
        if not row.get("has_video"):
            return "", "No video for this pitch.", "", "", hidden
        play_id = row["play_id"]
        shown = {**download_style, "display": "inline-block"}
        return (f"/bullpen-video/{play_id}", "", f"/bullpen-video/{play_id}/download",
               f"{play_id}.mp4", shown)

    dash_app.clientside_callback(
        """
        function(src) {
            var v = document.getElementById('bp-video-player');
            if (v) {
                v.load();
                if (src) { var p = v.play(); if (p && p.catch) { p.catch(function() {}); } }
            }
            return '';
        }
        """,
        Output("bp-video-reload", "children"),
        Input("bp-video-source", "src"),
    )
