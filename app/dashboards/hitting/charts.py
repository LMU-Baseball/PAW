"""Plotly strike-zone visualizations (pure functions of a pitch DataFrame).

Geometry ported from the R `zones_location` renderer (units = inches):
  x = PlateLocSide * -12 ; y = PlateLocHeight * 12 - 30
Zone rectangles and 3x3 gridlines match the R plot. Axes are hidden.
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data.hitting import PITCH_ABBR

# Stable per-pitch-type colors (PAW palette; crimson fastball, blue slider).
PITCH_COLORS = {
    "Fastball": "#9A0021", "Sinker": "#7a5230", "Cutter": "#e07b39",
    "Slider": "#0076A5", "Curveball": "#2b4c7e", "ChangeUp": "#e08a1e",
    "Splitter": "#5a5a5a", "Other": "#9aa0a6",
}
_DEFAULT_COLOR = "#9aa0a6"

# Zone rectangles as (x0, y0, x1, y1, fillcolor).
_ZONE_RECTS = [
    (-20.5, -25.5, 20.5, 25.5, "rgba(0,0,0,0.06)"),   # waste
    (-13.5, -15.125, 13.5, 15.125, "rgba(0,0,0,0.10)"),  # shadow
    (-7.25, -8.75, 7.25, 8.75, "rgba(0,0,0,0.16)"),   # heart
]
_SZ = (-10, -13, 10, 13)          # strike-zone border box
_VLINES = (-3.33, 3.33)           # vertical 3x3 gridlines
_HLINES = (-4.33, 4.33)           # horizontal 3x3 gridlines
_XRANGE = (-50, 50)
_YRANGE = (-35, 35)


def color_for(pitch_type: str) -> str:
    return PITCH_COLORS.get(pitch_type, _DEFAULT_COLOR)


def _to_xy(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["PlateLocSide"].notna() & df["PlateLocHeight"].notna()].copy()
    d["_x"] = d["PlateLocSide"] * -12
    d["_y"] = d["PlateLocHeight"] * 12 - 30
    return d


def _result_text(r) -> str:
    if r["PlayResult"] in (None, "Undefined"):
        return str(r["PitchCall"])
    return f"{r.get('TaggedHitType') or ''} - {r['PlayResult']}".strip(" -")


def _add_zone_shapes(fig, *, row=None, col=None):
    kw = {}
    if row is not None:
        kw = {"row": row, "col": col}
    for x0, y0, x1, y1, fill in _ZONE_RECTS:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(width=0), fillcolor=fill, layer="below", **kw)
    x0, y0, x1, y1 = _SZ
    fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                  line=dict(color="#888", width=1.5), fillcolor="rgba(0,0,0,0)", **kw)
    for vx in _VLINES:
        fig.add_shape(type="line", x0=vx, y0=y0, x1=vx, y1=y1,
                      line=dict(color="#bbb", width=1), **kw)
    for hy in _HLINES:
        fig.add_shape(type="line", x0=x0, y0=hy, x1=x1, y1=hy,
                      line=dict(color="#bbb", width=1), **kw)


def _style_axes(fig, *, row=None, col=None):
    kw = {"row": row, "col": col} if row is not None else {}
    fig.update_xaxes(range=list(_XRANGE), showgrid=False, zeroline=False,
                     visible=False, **kw)
    fig.update_yaxes(range=list(_YRANGE), showgrid=False, zeroline=False,
                     visible=False, scaleanchor=None, **kw)


def zone_scatter(df: pd.DataFrame, title: str = "") -> go.Figure:
    """Strike-zone scatter, one marker per pitch, colored by pitch type."""
    fig = go.Figure()
    _add_zone_shapes(fig)
    if df is not None and not df.empty:
        d = _to_xy(df)
        for ptype, g in d.groupby("TaggedPitchType"):
            fig.add_trace(go.Scatter(
                x=g["_x"], y=g["_y"], mode="markers",
                name=PITCH_ABBR.get(ptype, ptype),
                marker=dict(size=13, color=color_for(ptype),
                            line=dict(color="white", width=1), opacity=0.85),
                customdata=[[r["Balls"], r["Strikes"], r.get("Pitcher", ""),
                             _result_text(r)] for _, r in g.iterrows()],
                hovertemplate=("<b>%{text}</b><br>Count %{customdata[0]}-%{customdata[1]}"
                               "<br>Pitcher %{customdata[2]}<br>%{customdata[3]}"
                               "<extra></extra>"),
                text=[PITCH_ABBR.get(ptype, ptype)] * len(g),
            ))
    _style_axes(fig)
    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=16)),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.05), height=460,
    )
    return fig


def all_pas_figure(df: pd.DataFrame) -> go.Figure:
    """One strike-zone subplot per plate appearance (grouped Inning, PAofInning)."""
    if df is None or df.empty:
        fig = go.Figure()
        _add_zone_shapes(fig)
        _style_axes(fig)
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10),
                          paper_bgcolor="rgba(0,0,0,0)")
        return fig

    pa_keys = list(df.groupby(["Inning", "PAofInning"]).groups.keys())
    n = len(pa_keys)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    titles = [f"Inn {int(i)} · PA {int(p)}" for (i, p) in pa_keys]
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=titles,
                        horizontal_spacing=0.03, vertical_spacing=0.08)
    for idx, key in enumerate(pa_keys):
        row = idx // ncols + 1
        col = idx % ncols + 1
        _add_zone_shapes(fig, row=row, col=col)
        g = _to_xy(df[(df["Inning"] == key[0]) & (df["PAofInning"] == key[1])])
        for ptype, gg in g.groupby("TaggedPitchType"):
            fig.add_trace(go.Scatter(
                x=gg["_x"], y=gg["_y"], mode="markers+text",
                text=[str(int(v)) for v in gg["PitchofPA"]],
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=11, color=color_for(ptype),
                            line=dict(color="white", width=1)),
                showlegend=False,
            ), row=row, col=col)
        _style_axes(fig, row=row, col=col)
    fig.update_layout(height=300 * nrows, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig
