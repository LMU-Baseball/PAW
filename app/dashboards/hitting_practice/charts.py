"""Plotly figures for HitTrax practice dashboard."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data import practice as P
from app.dashboards.shell import CRIMSON

_BLUE = "#0076A5"


def pitch_zone_heatmap(df: pd.DataFrame) -> go.Figure:
    z, xedges, yedges = P.heatmap_contact_rate(df)
    x_centers = (xedges[:-1] + xedges[1:]) / 2
    y_centers = (yedges[:-1] + yedges[1:]) / 2
    fig = go.Figure(data=go.Heatmap(
        z=z, x=x_centers, y=y_centers,
        colorscale="YlOrRd", zmin=0, zmax=100,
        colorbar=dict(title="Contact %"),
        hovertemplate="x=%{x:.2f}ft<br>y=%{y:.2f}ft<br>Contact=%{z:.1f}%<extra></extra>",
    ))
    # Strike zone rectangle (catcher's view)
    fig.add_shape(type="rect", x0=P.SZ_X0, y0=P.SZ_Y0, x1=P.SZ_X1, y1=P.SZ_Y1,
                  line=dict(color="white", width=2), fillcolor="rgba(0,0,0,0)")
    fig.update_layout(
        title="Pitch Zones — Contact Rate (Catcher's View)",
        xaxis_title="Horizontal (ft)", yaxis_title="Height (ft)",
        yaxis=dict(scaleanchor="x", scaleratio=1),
        height=480, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def contact_by_zone_bars(zone_tbl: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not zone_tbl.empty:
        fig.add_trace(go.Bar(
            x=[f"Z{int(z)}" for z in zone_tbl["Zone"]],
            y=zone_tbl["Contact%"],
            text=[f"{int(c)}/{int(p)}" for c, p in
                  zip(zone_tbl["Contacts"], zone_tbl["Pitches"])],
            textposition="outside",
            marker_color=CRIMSON,
        ))
    fig.update_layout(
        title="Contact Rate by Zone",
        yaxis_title="Contact %", yaxis=dict(range=[0, 110]),
        height=360, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def ev_distance_by_pitch(df: pd.DataFrame) -> go.Figure:
    """Dual-axis EV + distance for contact pitches in order."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.update_layout(title="EV / Distance by Pitch #")
        return fig
    d = df[df["is_contact"]].sort_values("play_timestamp").copy()
    if d.empty:
        fig.update_layout(title="EV / Distance by Pitch # (no contacts)")
        return fig
    d = d.reset_index(drop=True)
    d["pitch_n"] = np.arange(1, len(d) + 1)
    fig.add_trace(go.Scatter(
        x=d["pitch_n"], y=d["exit_velocity"], name="Exit Velo",
        mode="lines+markers", line=dict(color=CRIMSON),
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=d["pitch_n"], y=d["distance_feet"], name="Distance",
        mode="lines+markers", line=dict(color=_BLUE),
    ), secondary_y=True)
    fig.update_layout(
        title="Exit Velo & Distance by Pitch #",
        height=380, margin=dict(l=40, r=40, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=1.08),
    )
    fig.update_yaxes(title_text="EV (mph)", secondary_y=False)
    fig.update_yaxes(title_text="Distance (ft)", secondary_y=True)
    fig.update_xaxes(title_text="Pitch #")
    return fig


def hit_type_donut(counts: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not counts.empty:
        fig.add_trace(go.Pie(
            labels=counts["Hit Type"], values=counts["Count"],
            hole=0.45, marker_colors=[CRIMSON, _BLUE, "#e07b39", "#5a5a5a"],
        ))
    fig.update_layout(
        title="Hit Type Mix", height=360,
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def top_players_bar(stats: pd.DataFrame, value_col: str, title: str) -> go.Figure:
    fig = go.Figure()
    if not stats.empty and value_col in stats.columns:
        d = stats.dropna(subset=[value_col]).head(10).iloc[::-1]
        fig.add_trace(go.Bar(
            x=d[value_col], y=d["player_name"], orientation="h",
            marker_color=CRIMSON,
        ))
    fig.update_layout(
        title=title, height=380, margin=dict(l=120, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig
