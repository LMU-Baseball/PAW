"""Plotly figures for the catching dashboard (pure functions of pitch DataFrames)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.data import catching as C
from app.dashboards.shell import CRIMSON

# Reuse hitting zone geometry conventions (inches).
_ZONE_RECTS = [
    (-20.5, -25.5, 20.5, 25.5, "rgba(0,0,0,0.06)"),
    (-13.5, -15.125, 13.5, 15.125, "rgba(0,0,0,0.10)"),
    (-7.25, -8.75, 7.25, 8.75, "rgba(0,0,0,0.16)"),
]
_SZ = (-10, -13, 10, 13)
_VLINES = (-3.33, 3.33)
_HLINES = (-4.33, 4.33)


def framing_scatter(df: pd.DataFrame) -> go.Figure:
    """Strike-zone scatter of takes: crimson = called strike, blue = ball."""
    t = C.takes(df)
    fig = go.Figure()
    for x0, y0, x1, y1, fill in _ZONE_RECTS:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(width=0), fillcolor=fill, layer="below")
    x0, y0, x1, y1 = _SZ
    fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                  line=dict(color="#888", width=1.5), fillcolor="rgba(0,0,0,0)")
    for vx in _VLINES:
        fig.add_shape(type="line", x0=vx, y0=y0, x1=vx, y1=y1,
                      line=dict(color="#bbb", width=1))
    for hy in _HLINES:
        fig.add_shape(type="line", x0=x0, y0=hy, x1=x1, y1=hy,
                      line=dict(color="#bbb", width=1))

    if not t.empty and "plate_loc_side" in t.columns:
        d = t[t["plate_loc_side"].notna() & t["plate_loc_height"].notna()].copy()
        d["_x"] = d["plate_loc_side"] * -12
        d["_y"] = d["plate_loc_height"] * 12 - 30
        strikes = d[d["is_strike"]]
        balls = d[~d["is_strike"]]
        if not strikes.empty:
            fig.add_trace(go.Scatter(
                x=strikes["_x"], y=strikes["_y"], mode="markers",
                name="Called Strike",
                marker=dict(color=CRIMSON, size=9, line=dict(width=0)),
                hovertext=strikes["pitch_call"].astype(str),
                hoverinfo="text",
            ))
        if not balls.empty:
            fig.add_trace(go.Scatter(
                x=balls["_x"], y=balls["_y"], mode="markers",
                name="Ball / Other",
                marker=dict(color="#0076A5", size=9, line=dict(width=0)),
                hovertext=balls["pitch_call"].astype(str),
                hoverinfo="text",
            ))

    fig.update_layout(
        title="Takes — Catcher View",
        showlegend=True,
        margin=dict(l=20, r=20, t=40, b=20),
        height=420,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        xaxis=dict(range=[-50, 50], visible=False, showgrid=False, zeroline=False),
        yaxis=dict(range=[-35, 35], visible=False, showgrid=False, zeroline=False),
    )
    return fig


def pop_time_chart(df: pd.DataFrame) -> go.Figure:
    """Pop-time distribution for throw attempts (lower is better)."""
    t = C.throw_attempts(df)
    fig = go.Figure()
    if not t.empty and t["pop_time"].notna().any():
        d = t.dropna(subset=["pop_time"]).sort_values("pop_time")
        fig.add_trace(go.Scatter(
            x=list(range(1, len(d) + 1)),
            y=d["pop_time"],
            mode="markers+lines",
            name="Pop Time",
            marker=dict(color=CRIMSON, size=10),
            line=dict(color="#0076A5", width=1),
            hovertext=[
                f"Pop {p:.2f}s"
                + (f" · Exch {e:.2f}s" if pd.notna(e) else "")
                + (f" · {s:.1f} mph" if pd.notna(s) else "")
                for p, e, s in zip(d["pop_time"], d["exchange_time"], d["throw_speed"])
            ],
            hoverinfo="text",
        ))
    fig.update_layout(
        title="Pop Time by Attempt",
        xaxis_title="Attempt #",
        yaxis_title="Pop Time (s)",
        margin=dict(l=40, r=20, t=40, b=40),
        height=360,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig
