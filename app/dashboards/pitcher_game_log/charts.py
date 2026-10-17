"""Pitching Game Log play-detail figures: the selected pitch against the
pitcher's other pitches of the same type this game -- movement (with the
pitch type's 2-sigma ellipse, like the bullpen download overlay) and release
point (1:1, zoomed to the cluster, like the Pitching dashboard)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.dashboards.shell import CRIMSON
from app.data import pitching

_FONT = dict(family="Teko, sans-serif")
_RELEASE_MIN_HALF = 0.5
_RELEASE_PAD = 0.25


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=18)), height=360,
        margin=dict(l=6, r=6, t=40, b=6), showlegend=False, font=_FONT,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)")
    return fig


def _selected(fig, r, x, y, label):
    fig.add_trace(go.Scatter(
        x=[r[x]], y=[r[y]], mode="markers",
        marker=dict(symbol="star", size=22, color=CRIMSON, line=dict(color="white", width=1.5)),
        hovertemplate=f"This pitch<br>{label}<extra></extra>"))


def movement_fig(same: pd.DataFrame, selected_uid: str | None, pitch_type: str) -> go.Figure:
    color = pitching.pitch_color(pitch_type)
    d = same.dropna(subset=["HorzBreak", "InducedVertBreak"])
    fig = go.Figure()
    ell = pitching._cov_ellipse(d["HorzBreak"], d["InducedVertBreak"], n_std=2.0) \
        if len(d) >= 3 else None
    if ell is not None:
        xs, ys = ell
        fig.add_trace(go.Scatter(x=list(xs) + [xs[0]], y=list(ys) + [ys[0]], mode="lines",
                                 fill="toself", fillcolor=pitching._rgba(color, 0.18),
                                 line=dict(color=color, width=1.5), hoverinfo="skip"))
    others = d[d["PitchUID"] != selected_uid]
    fig.add_trace(go.Scatter(
        x=others["HorzBreak"], y=others["InducedVertBreak"], mode="markers",
        marker=dict(color=color, size=9, opacity=0.6),
        hovertemplate="HB %{x:.1f} in<br>IVB %{y:.1f} in<extra></extra>"))
    sel = d[d["PitchUID"] == selected_uid]
    if not sel.empty:
        r = sel.iloc[0]
        _selected(fig, r, "HorzBreak", "InducedVertBreak",
                  f"HB {r['HorzBreak']:.1f} in · IVB {r['InducedVertBreak']:.1f} in")
    fig.update_xaxes(title="Horizontal Break (in)", zeroline=True)
    fig.update_yaxes(title="Induced Vert Break (in)", zeroline=True)
    return _style(fig, f"Movement — {pitch_type}s this game")


def release_fig(same: pd.DataFrame, selected_uid: str | None, pitch_type: str) -> go.Figure:
    color = pitching.pitch_color(pitch_type)
    d = same.dropna(subset=["RelSide", "RelHeight"])
    fig = go.Figure()
    others = d[d["PitchUID"] != selected_uid]
    fig.add_trace(go.Scatter(
        x=others["RelSide"], y=others["RelHeight"], mode="markers",
        marker=dict(color=color, size=9, opacity=0.6),
        hovertemplate="Side %{x:.2f} ft<br>Height %{y:.2f} ft<extra></extra>"))
    sel = d[d["PitchUID"] == selected_uid]
    if not sel.empty:
        r = sel.iloc[0]
        _selected(fig, r, "RelSide", "RelHeight",
                  f"Side {r['RelSide']:.2f} ft · Height {r['RelHeight']:.2f} ft")
    if not d.empty:
        xs, ys = d["RelSide"], d["RelHeight"]
        half = max((xs.max() - xs.min()) / 2, (ys.max() - ys.min()) / 2) + _RELEASE_PAD
        half = max(float(half), _RELEASE_MIN_HALF)
        cx, cy = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
        fig.update_xaxes(range=[cx - half, cx + half])
        fig.update_yaxes(range=[cy - half, cy + half])
    fig.update_xaxes(title="Release Side (ft)", constrain="domain")
    fig.update_yaxes(title="Release Height (ft)", scaleanchor="x", scaleratio=1,
                     constrain="domain")
    return _style(fig, f"Release — {pitch_type}s this game")
