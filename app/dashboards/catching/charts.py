"""Plotly figures for the catching dashboard (pure functions of pitch DataFrames).

Framing scatter/facets use the legacy stolen/lost color scheme over a catcher-view
strike-zone frame (home-plate pentagon + nested rulebook/Heart/Shadow rectangles).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data import catching as C
from app.dashboards.shell import CRIMSON

CALLTYPE_COLORS = {
    "Stolen Strike": "#000000",
    "Lost Strike": "#9A0021",
    "Correct Call": "#cccccc",
}
_ORDER = ["Correct Call", "Stolen Strike", "Lost Strike"]  # draw grey first


def _zone_frame(fig, row=None, col=None):
    """Catcher-view zone frame in inches (matches src/app.R)."""
    def seg(x0, y0, x1, y1):
        fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="black", width=1), row=row, col=col)
    def rect(x0, y0, x1, y1, dash=None, width=1.5):
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="black", width=width,
                                dash=dash) if dash else dict(color="black", width=width),
                      fillcolor="rgba(0,0,0,0)", row=row, col=col)
    # home-plate pentagon
    seg(-9, -21.5, 9, -21.5); seg(-9, -21.5, -9, -23.5); seg(9, -21.5, 9, -23.5)
    seg(-9, -23.5, 0, -25); seg(9, -23.5, 0, -25)
    # rulebook box (solid) + Heart + wide (dashed)
    rect(-10, -13, 10, 13, width=1.5)
    rect(-7.25, -8.75, 7.25, 8.75, dash="dash", width=1)
    rect(-13.5, -16, 13.5, 16, dash="dash", width=1)


def _base_axes(fig, row=None, col=None):
    fig.update_xaxes(range=[-40, 40], visible=False, row=row, col=col)
    fig.update_yaxes(range=[-25, 25], visible=False, row=row, col=col)


def _hover_texts(sub: pd.DataFrame) -> list[str]:
    """Per-point hover strings: Velo/BatSide/PitchSide/PitchSpeed/PitchCall
    (legacy hover fields), built defensively so a missing column never raises."""
    n = len(sub)
    velo = sub["rel_speed"] if "rel_speed" in sub.columns else None
    bat_side = sub["batter_side"] if "batter_side" in sub.columns else None
    pitcher_throws = sub["pitcher_throws"] if "pitcher_throws" in sub.columns else None
    pitch_speed = sub["PitchSpeed"] if "PitchSpeed" in sub.columns else None
    pitch_call = sub["pitch_call"] if "pitch_call" in sub.columns else None
    out = []
    for i in range(n):
        lines = []
        if velo is not None:
            v = velo.iloc[i]
            if pd.notna(v):
                lines.append(f"Velo: {float(v):.1f}")
        if bat_side is not None:
            lines.append(f"BatSide: {bat_side.iloc[i]}")
        if pitcher_throws is not None:
            lines.append(f"PitchSide: {pitcher_throws.iloc[i]}")
        if pitch_speed is not None:
            lines.append(f"PitchSpeed: {pitch_speed.iloc[i]}")
        if pitch_call is not None:
            lines.append(f"PitchCall: {pitch_call.iloc[i]}")
        out.append("<br>".join(lines))
    return out


def _scatter_traces(fig, d, row=None, col=None, shown=None):
    if shown is None:
        shown = set()
    for ct in _ORDER:
        sub = d[d["CallType"] == ct]
        if sub.empty:
            continue
        showlegend = ct not in shown
        shown.add(ct)
        fig.add_trace(go.Scatter(
            x=sub["_x"], y=sub["_y"], mode="markers", name=ct,
            legendgroup=ct, showlegend=showlegend,
            marker=dict(color=CALLTYPE_COLORS[ct], size=9,
                        line=dict(width=0.5, color="#666")),
            hovertext=_hover_texts(sub), hoverinfo="text",
        ), row=row, col=col)


def framing_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    _zone_frame(fig)
    if not df.empty:
        d = C.add_framing_cols(df) if "CallType" not in df.columns else df
        d = d[d["plate_loc_side"].notna() & d["plate_loc_height"].notna()]
        _scatter_traces(fig, d)
    _base_axes(fig)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_layout(
        title="Zone Location — Catcher View", showlegend=True,
        margin=dict(l=20, r=20, t=40, b=20), height=460,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def framing_facets(df: pd.DataFrame, by: str, title: str) -> go.Figure:
    d = C.add_framing_cols(df) if not df.empty and "CallType" not in df.columns else df
    vals = sorted(d[by].dropna().unique()) if not d.empty and by in d.columns else []
    n = max(1, len(vals))
    fig = make_subplots(rows=1, cols=n, subplot_titles=[str(v) for v in vals] or [title])
    shown = set()
    for i, v in enumerate(vals, start=1):
        _zone_frame(fig, row=1, col=i)
        _scatter_traces(fig, d[d[by] == v], row=1, col=i, shown=shown)
        _base_axes(fig, row=1, col=i)
        fig.update_yaxes(scaleanchor=("x" if i == 1 else f"x{i}"),
                         scaleratio=1, row=1, col=i)
    if not vals:
        _zone_frame(fig, row=1, col=1); _base_axes(fig, row=1, col=1)
        fig.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=1)
    fig.update_layout(
        title=title, height=380, margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def caught_stealing_trend_fig(trend_df: pd.DataFrame) -> go.Figure:
    """Dual-axis trend: CS% (crimson, left) + Avg Pop time (blue, right) by game date."""
    fig = go.Figure()
    if trend_df is not None and not trend_df.empty:
        x = trend_df["game_date"].astype(str)
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["cs_pct"], name="CS%", yaxis="y",
            mode="markers+lines", marker=dict(color=CRIMSON, size=10),
            line=dict(color=CRIMSON, width=2),
            hovertext=[f"{a} att · {c} caught" for a, c in
                       zip(trend_df["attempts"], trend_df["caught"])],
            hoverinfo="text+y",
        ))
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["avg_pop"], name="Avg Pop (s)", yaxis="y2",
            mode="markers+lines", marker=dict(color="#0076A5", size=9),
            line=dict(color="#0076A5", width=2, dash="dot"),
        ))
    fig.update_layout(
        title="Caught Stealing Trend",
        xaxis=dict(title="Game"),
        yaxis=dict(title="CS%", range=[0, 100], side="left"),
        yaxis2=dict(title="Avg Pop (s)", overlaying="y", side="right",
                    showgrid=False),
        height=340, margin=dict(l=40, r=40, t=40, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=1.12),
    )
    return fig
