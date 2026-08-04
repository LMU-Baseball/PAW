"""Development Trends tab — per-pitch-type metric trends across sessions."""
from __future__ import annotations

from dash import dcc, html

from app.data import bullpen as B
from app.dashboards.bullpen import charts

_MUTED = {"padding": "12px", "color": "#555"}
_METRICS = [("velocity", "Velocity"), ("spin", "Spin"),
            ("movement", "Movement"), ("command", "Command")]


def body(df, metric):
    if df is None or df.empty:
        return html.Div("No bullpen data in this date range.", style=_MUTED)
    if df["date"].nunique() < 2:
        return html.Div("Only one session in range — trends need ≥2 sessions.", style=_MUTED)
    return dcc.Graph(figure=charts.trend_small_multiples(df, metric), style={"height": "auto"})


def render(pitcher_id, start, end) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    df = B.trend_by_session(int(pitcher_id), start, end)
    controls = dcc.RadioItems(id="bp-trend-metric",
        options=[{"label": lbl, "value": val} for val, lbl in _METRICS],
        value="velocity", inline=True,
        style={"fontFamily": "Teko, sans-serif", "fontSize": "16px"})
    return html.Div([
        controls,
        dcc.Store(id="bp-trend-data", data=(df.to_json(orient="split") if not df.empty else None)),
        html.Div(id="bp-trend-body", children=body(df, "velocity")),
    ])
