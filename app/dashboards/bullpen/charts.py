"""Plotly figure builders for the bullpen dashboard (snake_case bullpen cols).

Interactive counterparts to app/reports/bullpen_plots.py (matplotlib, PDF).
Pitch-type color always via plots.color_for for cross-app consistency.
"""
from __future__ import annotations

import plotly.graph_objects as go

from app.reports.plots import color_for

_BASE = dict(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
             margin=dict(l=45, r=20, t=42, b=42), showlegend=True,
             font=dict(family="Teko, sans-serif", size=14),
             title_font=dict(color="#9A0021", size=16))
_ZONE = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)  # standard strike-zone box (ft)


def _empty(msg="No data"):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=16, color="#888"))
    fig.update_layout(**_BASE)
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return fig


def _types(df):
    return list(df.groupby("tagged_pitch_type").groups)


def velo_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    types = _types(df)
    for i, pt in enumerate(types):
        sub = df[df["tagged_pitch_type"] == pt]
        y = len(types) - i
        fig.add_trace(go.Scatter(
            x=sub["rel_speed"], y=[y] * len(sub), mode="markers", name=str(pt),
            marker=dict(size=11, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.update_layout(title="Velocity by pitch type", xaxis_title="mph", **_BASE)
    fig.update_yaxes(tickvals=list(range(1, len(types) + 1)), ticktext=list(reversed(types)))
    return fig


def movement_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["horz_break"], y=sub["ind_vert_break"], mode="markers", name=str(pt),
            marker=dict(size=10, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.add_hline(y=0, line_color="#ccc"); fig.add_vline(x=0, line_color="#ccc")
    fig.update_layout(title="Movement", xaxis_title="HB (in)", yaxis_title="IVB (in)", **_BASE)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


def release_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["rel_side"], y=sub["rel_height"], mode="markers", name=str(pt),
            marker=dict(size=10, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.update_layout(title="Release", xaxis_title="Rel side (ft)",
                      yaxis_title="Rel height (ft)", **_BASE)
    return fig


def location_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    fig.add_shape(type="rect", x0=_ZONE["x0"], x1=_ZONE["x1"], y0=_ZONE["y0"], y1=_ZONE["y1"],
                  line=dict(color="black", width=1.5))
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=str(pt),
            marker=dict(size=9, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.update_layout(title="Location", **_BASE)
    fig.update_xaxes(range=[-2.5, 2.5], visible=False)
    fig.update_yaxes(range=[0, 5], visible=False, scaleanchor="x", scaleratio=1)
    return fig


_TREND_TITLES = {
    "velocity": "Velocity trend — avg (solid) / max (dashed)",
    "spin": "Spin trend — rate (solid) / efficiency % (dotted, right axis)",
    "movement": "Movement trend — IVB (solid) / HB (dashed)",
    "command": "Location spread — lower = tighter (consistency proxy)",
}


def trend_fig(df, metric, active_types=None):
    if df is None or df.empty:
        return _empty("Need at least 2 sessions to show a trend.")
    types = active_types if active_types else sorted(df["tagged_pitch_type"].unique())
    fig = go.Figure()
    for pt in types:
        sub = df[df["tagged_pitch_type"] == pt].sort_values("date")
        if sub.empty:
            continue
        col = color_for(pt)
        if metric == "velocity":
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["velo_avg"], mode="lines+markers",
                                     name=f"{pt} avg", line=dict(color=col)))
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["velo_max"], mode="lines+markers",
                                     name=f"{pt} max", line=dict(color=col, dash="dash")))
        elif metric == "spin":
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["spin_avg"], mode="lines+markers",
                                     name=f"{pt} spin", line=dict(color=col)))
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["eff_avg"], mode="lines+markers",
                                     name=f"{pt} eff%", line=dict(color=col, dash="dot"),
                                     yaxis="y2"))
        elif metric == "movement":
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["ivb_avg"], mode="lines+markers",
                                     name=f"{pt} IVB", line=dict(color=col)))
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["hb_avg"], mode="lines+markers",
                                     name=f"{pt} HB", line=dict(color=col, dash="dash")))
        else:  # command
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["loc_spread"], mode="lines+markers",
                                     name=str(pt), line=dict(color=col)))
    fig.update_layout(title=_TREND_TITLES.get(metric, ""), xaxis_title="Session date", **_BASE)
    if metric == "spin":
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", title="eff %"))
    return fig
