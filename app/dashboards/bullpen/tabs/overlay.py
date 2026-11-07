"""Overlay tab -- pick 2-3 bullpen pitches from any sessions in the date
range and render them into one release-aligned video next to their Trackman
flight paths (app.reports.bullpen_pitch_overlay, served by
app.main.routes.bullpen_overlay).

Pitching staff ask (2026-11-07): "select a fastball from any bullpen vs
another one ... pen on Monday 95 vs pen on Friday 88, different colors, and
compare mechanics", plus pitch tunneling within one pen.
"""
from __future__ import annotations

from urllib.parse import urlencode

from dash import ALL, Input, Output, State, dash_table, dcc, html, no_update

from app.dashboards import shell
from app.data import bullpen_video as BV
from app.reports.bullpen_pitch_overlay import COLORS, MAX_PITCHES, pitch_label

_MUTED = {"padding": "12px", "color": "#555"}
_HEX = ["#{:02x}{:02x}{:02x}".format(*c) for c in COLORS]

_COLS = [("date", "Date"), ("session_pitch", "Pitch #"), ("pitch_type", "Pitch"),
         ("velo", "Velo"), ("ind_vert_break", "IVB"), ("horz_break", "HB"), ("spin", "Spin")]
_KEEP = [c for c, _ in _COLS] + ["play_id", "pitcher", "extension"]

_MODE_OPTIONS = [
    {"label": " Ghost overlay (same bullpen)", "value": "overlay"},
    {"label": " Side by side (different bullpens)", "value": "side"},
]


def merge_picks(picked: list[str], selected: list[str], limit: int = MAX_PITCHES) -> list[str]:
    """New ordered pick list after the table's checkboxes change: unchecked
    picks drop out, new checks go on the end (order is color order), and
    anything past `limit` is ignored. The table's filters only hide rows
    (`filter_query`), so a pick hidden by switching the filter -- Monday's
    fastball while picking from Friday -- stays checked."""
    selected_set = set(selected)
    kept = [p for p in picked if p in selected_set]
    for p in selected:
        if p not in kept and len(kept) < limit:
            kept.append(p)
    return kept


def filter_query(sessions, types) -> str:
    """DataTable `filter_query` for the Bullpens / Pitch types dropdowns."""
    parts = []
    for col, values in (("date", sessions), ("pitch_type", types)):
        if values:
            parts.append("(" + " || ".join(f'{{{col}}} = "{v}"' for v in values) + ")")
    return " && ".join(parts)


def default_mode(dates: list[str]) -> str:
    """The Edger gets moved between pens, so a ghost overlay only lines up
    within one session."""
    return "overlay" if len(set(dates)) <= 1 else "side"


def render(pitcher_id, start, end) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    if not start or not end:
        return html.Div("Pick a date range.", style=_MUTED)
    df = BV.overlay_pitch_options(int(pitcher_id), start, end)
    if df.empty:
        return html.Div("No bullpen pitches with Edger video in this date range.", style=_MUTED)

    df = df[_KEEP].copy()
    for c in ("velo", "ind_vert_break", "horz_break", "extension"):
        df[c] = df[c].round(1)
    df["spin"] = df["spin"].round(0)
    df["id"] = df["play_id"]
    records = df.to_dict("records")
    counts = df.groupby("date").size().sort_index(ascending=False)
    session_opts = [{"label": f"{d} ({n})", "value": d} for d, n in counts.items()]
    type_opts = [{"label": t, "value": t} for t in sorted(df["pitch_type"].dropna().unique())]

    filters = html.Div([
        html.Div([
            html.Label("Bullpens", style={"fontWeight": "bold"}),
            dcc.Dropdown(id="bp-ovl-sessions", options=session_opts, multi=True,
                         placeholder="All bullpens in range"),
        ], style={"flex": "1", "minWidth": "220px"}),
        html.Div([
            html.Label("Pitch types", style={"fontWeight": "bold"}),
            dcc.Dropdown(id="bp-ovl-types", options=type_opts, multi=True,
                         placeholder="All pitch types"),
        ], style={"flex": "1", "minWidth": "220px"}),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "8px"})

    table = dash_table.DataTable(
        id="bp-ovl-table",
        columns=[{"name": h, "id": c} for c, h in _COLS],
        data=records,
        row_selectable="multi",
        selected_rows=[],
        sort_action="native",
        filter_action="native",
        filter_query="",
        # The Bullpens / Pitch types dropdowns drive filter_query; hide the free-text filter row.
        css=[{"selector": "tr:has(th.dash-filter)", "rule": "display: none"}],
        page_size=15,
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": shell.CRIMSON, "color": "white", "fontWeight": "bold"},
    )

    controls = html.Div([
        html.Div(f"Check up to {MAX_PITCHES} pitches. Colors follow the order you pick them; "
                 "extra checks are ignored.",
                 style={"color": "#555", "marginBottom": "6px"}),
        html.Div("No pitches picked yet.", id="bp-ovl-picked-list", style={"color": "#555"}),
        dcc.RadioItems(id="bp-ovl-mode", options=_MODE_OPTIONS, value="overlay",
                       labelStyle={"display": "block"}, style={"margin": "8px 0"}),
        html.Div(id="bp-ovl-mode-hint", style={"color": "#555", "fontSize": "13px"}),
        html.Button("Build overlay video", id="bp-ovl-build", n_clicks=0, disabled=True,
                    style={"marginTop": "8px", "padding": "6px 14px", "border": "none",
                           "backgroundColor": shell.CRIMSON, "color": "white",
                           "borderRadius": "6px", "fontFamily": "Teko, sans-serif",
                           "fontSize": "17px", "cursor": "pointer"}),
        html.Div(id="bp-ovl-status", style={"color": "#555", "margin": "8px 0"}),
        # No `src` until a build: an empty src resolves to the page URL itself.
        html.Video(id="bp-ovl-player", controls=True, autoPlay=True, muted=True, loop=True,
                   style={"display": "none", "width": "100%", "borderRadius": "8px",
                          "background": "#000"}),
        html.A("Download MP4", id="bp-ovl-download", href="", download="",
               style={"display": "none", "marginTop": "8px", "padding": "6px 14px",
                      "backgroundColor": shell.CRIMSON, "color": "white", "borderRadius": "6px",
                      "textDecoration": "none", "fontFamily": "Teko, sans-serif",
                      "fontSize": "15px"}),
    ])

    return html.Div([
        dcc.Store(id="bp-ovl-all", data=records),
        dcc.Store(id="bp-ovl-picked", data=[]),
        filters,
        html.Div([
            html.Div([table], className="paw-video-table", style={"flex": "1", "minWidth": "320px"}),
            html.Div([controls], className="paw-video-media", style={"flex": "2", "minWidth": "480px"}),
        ], className="paw-video-row",
           style={"display": "flex", "gap": "16px", "alignItems": "flex-start"}),
    ])


def _chip(i: int, row: dict) -> html.Div:
    return html.Div([
        html.Span(style={"display": "inline-block", "width": "14px", "height": "14px",
                         "backgroundColor": _HEX[i], "borderRadius": "3px",
                         "marginRight": "8px", "verticalAlign": "middle"}),
        html.Span(f"{pitch_label(row)} mph", style={"marginRight": "12px"}),
        html.Span("release nudge (frames) ", style={"color": "#555", "fontSize": "13px"}),
        dcc.Input(id={"type": "bp-ovl-nudge", "index": row["play_id"]}, type="number",
                  value=0, step=1, min=-60, max=60, debounce=True, style={"width": "64px"}),
    ], style={"marginBottom": "4px"})


def overlay_url(picked: list[str], nudges: list, mode: str, download: bool = False) -> str:
    params = {"ids": ",".join(picked),
              "nudge": ",".join(str(int(n or 0)) for n in nudges),
              "mode": mode}
    if download:
        params["dl"] = "1"
    return "/bullpen-overlay.mp4?" + urlencode(params)


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("bp-ovl-table", "filter_query"),
        Input("bp-ovl-sessions", "value"),
        Input("bp-ovl-types", "value"),
        prevent_initial_call=True,
    )
    def _filter(sessions, types):
        return filter_query(sessions, types)

    @dash_app.callback(
        Output("bp-ovl-picked", "data"),
        Input("bp-ovl-table", "selected_rows"),
        State("bp-ovl-table", "data"),
        State("bp-ovl-picked", "data"),
        prevent_initial_call=True,
    )
    def _pick(selected_rows, data, picked):
        data = data or []
        selected = [data[i]["id"] for i in (selected_rows or []) if i < len(data)]
        merged = merge_picks(picked or [], selected)
        return merged if merged != (picked or []) else no_update

    @dash_app.callback(
        Output("bp-ovl-picked-list", "children"),
        Output("bp-ovl-mode", "value"),
        Output("bp-ovl-build", "disabled"),
        Input("bp-ovl-picked", "data"),
        State("bp-ovl-all", "data"),
        prevent_initial_call=True,
    )
    def _picked_list(picked, records):
        by_id = {r["id"]: r for r in records or []}
        rows = [by_id[p] for p in picked or [] if p in by_id]
        if not rows:
            return html.Div("No pitches picked yet.", style={"color": "#555"}), no_update, True
        chips = [_chip(i, r) for i, r in enumerate(rows)]
        return chips, default_mode([r["date"] for r in rows]), False

    @dash_app.callback(
        Output("bp-ovl-mode-hint", "children"),
        Input("bp-ovl-mode", "value"),
        State("bp-ovl-picked", "data"),
        State("bp-ovl-all", "data"),
    )
    def _mode_hint(mode, picked, records):
        by_id = {r["id"]: r for r in records or []}
        dates = {by_id[p]["date"] for p in picked or [] if p in by_id}
        if mode == "overlay" and len(dates) > 1:
            return ("These pitches are from different bullpens. The Edger usually moved "
                    "between them, so a ghost overlay won't line up -- side by side reads better.")
        return ""

    @dash_app.callback(
        Output("bp-ovl-player", "src"),
        Output("bp-ovl-player", "style"),
        Output("bp-ovl-download", "href"),
        Output("bp-ovl-download", "style"),
        Output("bp-ovl-status", "children"),
        Input("bp-ovl-build", "n_clicks"),
        State("bp-ovl-picked", "data"),
        State({"type": "bp-ovl-nudge", "index": ALL}, "value"),
        State("bp-ovl-mode", "value"),
        State("bp-ovl-player", "style"),
        State("bp-ovl-download", "style"),
        prevent_initial_call=True,
    )
    def _build(n_clicks, picked, nudges, mode, player_style, dl_style):
        if not n_clicks or not picked:
            return no_update, no_update, no_update, no_update, no_update
        return (overlay_url(picked, nudges, mode),
                {**(player_style or {}), "display": "block"},
                overlay_url(picked, nudges, mode, download=True),
                {**(dl_style or {}), "display": "inline-block"},
                "Rendering -- the video starts playing when it's ready (usually under a minute). "
                "If a delivery looks early or late, nudge its release and build again.")
