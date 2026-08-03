"""Development Trends tab — per-pitch-type metric trends across sessions."""
from __future__ import annotations

from dash import dcc, html

from app.data import bullpen as B
from app.dashboards.bullpen import charts
from app.reports.plots import color_for

_MUTED = {"padding": "12px", "color": "#555"}
_METRICS = [("velocity", "Velocity"), ("spin", "Spin"),
            ("movement", "Movement"), ("command", "Command")]


def chip_row(pitch_types) -> html.Div:
    chips = []
    for pt in pitch_types:
        col = color_for(pt)
        chips.append(html.Button(
            str(pt), id={"type": "bp-trend-chip", "index": str(pt)}, n_clicks=0,
            style={"border": f"2px solid {col}", "background": col, "color": "#fff",
                   "borderRadius": "14px", "padding": "3px 12px", "margin": "0 6px 6px 0",
                   "cursor": "pointer", "fontFamily": "Teko, sans-serif", "fontSize": "15px"}))
    return html.Div(chips, style={"margin": "8px 0"})


def body(df, metric, active):
    if df is None or df.empty:
        return html.Div("No bullpen data in this date range.", style=_MUTED)
    if df["date"].nunique() < 2:
        return html.Div("Only one session in range — trends need ≥2 sessions.", style=_MUTED)
    return dcc.Graph(figure=charts.trend_fig(df, metric, active), style={"height": "460px"})


def render(pitcher_id, start, end) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    df = B.trend_by_session(int(pitcher_id), start, end)
    types = sorted(df["tagged_pitch_type"].unique().tolist()) if not df.empty else []
    controls = html.Div([
        dcc.RadioItems(id="bp-trend-metric",
                       options=[{"label": lbl, "value": val} for val, lbl in _METRICS],
                       value="velocity", inline=True,
                       style={"fontFamily": "Teko, sans-serif", "fontSize": "16px"}),
        chip_row(types),
    ])
    return html.Div([
        controls,
        dcc.Store(id="bp-trend-active", data=types),
        dcc.Store(id="bp-trend-data", data=(df.to_json(orient="split") if not df.empty else None)),
        html.Div(id="bp-trend-body", children=body(df, "velocity", types)),
    ])
