"""Shared pitch-level video tab: pitch table + one player + angle toggle."""
from __future__ import annotations

import pandas as pd
from dash import ALL, Input, Output, State, ctx, dash_table, dcc, html, no_update

from app.data.video import ANGLES, DISPLAY_COLS, URL_COL

CRIMSON = "#9A0021"


def _btn_style(has: bool, on: bool) -> dict:
    return {"border": f"2px solid {CRIMSON}",
            "background": CRIMSON if on else "#fff",
            "color": "#fff" if on else (CRIMSON if has else "#bbb"),
            "borderRadius": "14px", "padding": "4px 14px", "margin": "0 6px 0 0",
            "cursor": "pointer" if has else "not-allowed", "opacity": "1" if has else ".5",
            "fontFamily": "Teko, sans-serif", "fontSize": "15px"}


def render(df: pd.DataFrame, *, prefix: str, default_angle: str) -> html.Div:
    if df is None or df.empty:
        return html.Div("No video available for this selection.",
                        style={"padding": "16px", "color": "#555",
                               "fontFamily": "Teko, sans-serif", "fontSize": "18px"})
    table = dash_table.DataTable(
        id=f"{prefix}-video-table",
        columns=[{"name": c, "id": c} for c in DISPLAY_COLS],
        data=df.to_dict("records"),          # includes hidden url_* + batter_side + pitch_uid
        page_size=15, sort_action="native", filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": CRIMSON, "color": "white", "fontWeight": "bold"},
        style_data_conditional=[{"if": {"state": "active"},
                                 "backgroundColor": "rgba(154,0,33,.15)",
                                 "border": f"1px solid {CRIMSON}"}],
    )
    buttons = [html.Button(label, id={"type": f"{prefix}-angle", "index": key},
                           n_clicks=0, style=_btn_style(True, False))
               for key, label in ANGLES]
    player = html.Video(id=f"{prefix}-video-player", src="", controls=True,
                        autoPlay=True, muted=True, loop=True,
                        style={"width": "100%", "borderRadius": "8px", "background": "#000"})
    return html.Div([
        dcc.Store(id=f"{prefix}-video-pitch"),
        dcc.Store(id=f"{prefix}-video-angle"),
        html.Div([
            html.Div([html.Div("Click a pitch to load video",
                               style={"color": "#555", "marginBottom": "4px"}), table],
                     style={"flex": "1", "minWidth": "340px"}),
            html.Div([
                html.Div(buttons, style={"marginBottom": "8px"}),
                html.Div("Click a pitch row to load video.", id=f"{prefix}-video-hint",
                         style={"color": "#555", "marginBottom": "6px"}),
                player,
            ], style={"flex": "1", "minWidth": "360px"}),
        ], style={"display": "flex", "gap": "16px", "alignItems": "flex-start"}),
    ])


def _resolve_default(pitch: dict | None, default_angle: str) -> str:
    urls = (pitch or {}).get("urls") or {}
    side = (pitch or {}).get("side")
    if default_angle == "batter_side":
        order = ["HomeRight" if side == "Right" else "HomeLeft", "HomeBehind", "Broadcast"]
    else:
        order = [default_angle]
    order += [k for k, _ in ANGLES if k not in order]
    for k in order:
        if urls.get(k):
            return k
    return "HomeBehind" if default_angle == "batter_side" else default_angle


def register_callbacks(dash_app, prefix: str, default_angle: str = "HomeBehind") -> None:

    @dash_app.callback(
        Output(f"{prefix}-video-pitch", "data"),
        Input(f"{prefix}-video-table", "active_cell"),
        State(f"{prefix}-video-table", "derived_viewport_data"),
        prevent_initial_call=True,
    )
    def _select(active, rows):
        if not active or not rows:
            return no_update
        i = active.get("row")
        if i is None or i >= len(rows):
            return no_update
        row = rows[i]
        return {"urls": {k: row.get(URL_COL[k]) for k, _ in ANGLES},
                "side": row.get("batter_side")}

    @dash_app.callback(
        Output(f"{prefix}-video-angle", "data"),
        Input(f"{prefix}-video-pitch", "data"),
        Input({"type": f"{prefix}-angle", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _angle(pitch, _clicks):
        trig = ctx.triggered_id
        if isinstance(trig, dict):
            return trig["index"]
        return _resolve_default(pitch, default_angle)

    @dash_app.callback(
        Output(f"{prefix}-video-player", "src"),
        Output(f"{prefix}-video-hint", "children"),
        Input(f"{prefix}-video-pitch", "data"),
        Input(f"{prefix}-video-angle", "data"),
    )
    def _src(pitch, angle):
        if not pitch:
            return "", "Click a pitch row to load video."
        url = ((pitch.get("urls") or {}).get(angle)) or ""
        return (url, "") if url else ("", "No video for this angle.")

    @dash_app.callback(
        Output({"type": f"{prefix}-angle", "index": ALL}, "disabled"),
        Output({"type": f"{prefix}-angle", "index": ALL}, "style"),
        Input(f"{prefix}-video-pitch", "data"),
        Input(f"{prefix}-video-angle", "data"),
        State({"type": f"{prefix}-angle", "index": ALL}, "id"),
    )
    def _btn_states(pitch, angle, ids):
        urls = (pitch or {}).get("urls") or {}
        disabled, styles = [], []
        for i in ids:
            key = i["index"]
            has = bool(urls.get(key))
            disabled.append(not has)
            styles.append(_btn_style(has, key == angle and has))
        return disabled, styles
