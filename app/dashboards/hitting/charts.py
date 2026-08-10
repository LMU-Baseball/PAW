"""Plotly strike-zone visualizations (pure functions of a pitch DataFrame).

Geometry ported from the R `zones_location` renderer (units = inches):
  x = PlateLocSide * -12 ; y = PlateLocHeight * 12 - 30
Zone rectangles and 3x3 gridlines match the R plot. Axes are hidden.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data.hitting import PITCH_ABBR
from app.data import pitching as _pitching

PITCH_COLORS = _pitching.PITCH_COLORS  # single source of truth (matches pitchers)

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
    return _pitching.pitch_color(pitch_type)


def _to_xy(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["PlateLocSide"].notna() & df["PlateLocHeight"].notna()].copy()
    d["_x"] = d["PlateLocSide"] * -12
    d["_y"] = d["PlateLocHeight"] * 12 - 30
    return d


def _result_text(r) -> str:
    if r["PlayResult"] in (None, "Undefined"):
        return str(r["PitchCall"])
    hit = r.get("TaggedHitType")
    hit = "" if pd.isna(hit) else str(hit)
    return f"{hit} - {r['PlayResult']}".strip(" -")


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
                # Hover shows only what pitch was thrown + its result.
                customdata=[_result_text(r) for _, r in g.iterrows()],
                hovertemplate=f"<b>{ptype}</b><br>%{{customdata}}<extra></extra>",
            ))
    _style_axes(fig)
    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=16)),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        legend=dict(orientation="h", y=-0.05), height=460,
    )
    return fig


def _empty_pas_figure() -> go.Figure:
    fig = go.Figure()
    _add_zone_shapes(fig)
    _style_axes(fig)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10),
                      paper_bgcolor="#ffffff", plot_bgcolor="#ffffff")
    return fig


def _pa_keys(df: pd.DataFrame) -> list[tuple]:
    """Ordered composite PA identity: (GameID, Inning, PAofInning).

    A pooled multi-game df reuses Inning/PAofInning per game, so GameID must be
    part of the key to avoid conflating PAs across games. GameID defaults to 0
    when the column is absent so a single game's grouping/ordering is unaffected.
    """
    if "GameID" not in df.columns:
        return [(0, i, p) for i, p in
                sorted(df.groupby(["Inning", "PAofInning"]).groups.keys())]
    return sorted(df.groupby(["GameID", "Inning", "PAofInning"]).groups.keys())


# Defense-in-depth: never build more than this many PA subplots. The Plate
# Appearances tab already caps to 12, but a large df from any caller would make
# make_subplots raise (vertical_spacing > 1/(rows-1)) -- an 88-row season df
# crashed it. Cap here too so no code path can crash on an oversized selection.
_MAX_PA_SUBPLOTS = 12


def all_pas_figure(df: pd.DataFrame) -> go.Figure:
    """One strike-zone subplot per plate appearance, numbered in game order.

    PAs are ordered chronologically (GameID, then Inning, then PAofInning) and
    titled by the hitter's sequential game PA number ("PA 1 · Inn 1") — NOT
    PAofInning, which is the position within the inning across all batters. When
    the df spans more than one game, each title is prefixed with a "G{GameID}"
    marker so PAs from different games stay distinguishable.
    """
    if df is None or df.empty:
        return _empty_pas_figure()

    pa_keys = _pa_keys(df)
    if len(pa_keys) > _MAX_PA_SUBPLOTS:
        pa_keys = pa_keys[-_MAX_PA_SUBPLOTS:]  # most-recent N; never crash
    n = len(pa_keys)
    if n == 0:
        return _empty_pas_figure()
    multi_game = len({k[0] for k in pa_keys}) > 1
    has_gameid = "GameID" in df.columns
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    titles = []
    for seq, (gid, i, p) in enumerate(pa_keys, 1):
        t = f"PA {seq} · Inn {int(i)}"
        titles.append(f"G{gid} · {t}" if multi_game else t)
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=titles,
                        horizontal_spacing=0.03, vertical_spacing=0.08)
    for idx, key in enumerate(pa_keys):
        gid, inn, pa = key
        row = idx // ncols + 1
        col = idx % ncols + 1
        _add_zone_shapes(fig, row=row, col=col)
        mask = (df["Inning"] == inn) & (df["PAofInning"] == pa)
        if has_gameid:
            mask &= (df["GameID"] == gid)
        g = _to_xy(df[mask])
        for ptype, gg in g.groupby("TaggedPitchType"):
            fig.add_trace(go.Scatter(
                x=gg["_x"], y=gg["_y"], mode="markers+text",
                text=["" if pd.isna(v) else str(int(v)) for v in gg["PitchofPA"]],
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=11, color=color_for(ptype),
                            line=dict(color="white", width=1)),
                customdata=[_result_text(r) for _, r in gg.iterrows()],
                hovertemplate=f"<b>{ptype}</b><br>%{{customdata}}<extra></extra>",
                showlegend=False,
            ), row=row, col=col)
        _style_axes(fig, row=row, col=col)
    # Fixed ~360px per column so a lone PA keeps the zone's proportions instead of
    # stretching to full container width; multi-PA layout is unchanged.
    fig.update_layout(height=300 * nrows, width=360 * ncols,
                      margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="#ffffff", plot_bgcolor="#ffffff")
    return fig


_HIT_COLORS = {"FlyBall": "#c0392b", "GroundBall": "#4a7fb5", "LineDrive": "#e08a1e",
               "PopUp": "#6b8e23", "Undefined": "#888888"}


def _empty_bip_fig(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title, height=440, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        annotations=[dict(text="No balls in play for this selection.",
                          showarrow=False, font=dict(size=18, family="Teko, sans-serif"))])
    return fig


def radial_fig(bip_df) -> go.Figure:
    """Launch-angle radial: EV rings (40/90/120 mph) + LA guide lines, points at
    (rx, ry) colored by hit type."""
    d = None
    if bip_df is not None and not bip_df.empty:
        d = bip_df[bip_df["rx"].notna() & bip_df["ry"].notna()]
    if d is None or d.empty:
        return _empty_bip_fig("Launch Angle / Exit Velo")
    fig = go.Figure()
    th = np.linspace(-np.pi / 2, np.pi / 2, 200)
    for r, fill in [(1.0, "#e8e8e8"), (2 / 3, "#c8c8c8"), (1 / 3, "#9a9a9a")]:
        fig.add_trace(go.Scatter(
            x=np.concatenate([r * np.cos(th), [0.0]]),
            y=np.concatenate([r * np.sin(th), [-r]]),
            fill="toself", fillcolor=fill, line=dict(width=0),
            hoverinfo="skip", showlegend=False))
    for ang, color in [(8, "green"), (25, "green"), (45, "#777"), (90, "#777")]:
        a = np.radians(ang)
        fig.add_trace(go.Scatter(x=[0, np.cos(a)], y=[0, np.sin(a)], mode="lines",
                                 line=dict(color=color, width=1), hoverinfo="skip",
                                 showlegend=False))
    for ht, sub in d.groupby("hit_type"):
        fig.add_trace(go.Scatter(
            x=sub["rx"], y=sub["ry"], mode="markers", name=str(ht), showlegend=False,
            marker=dict(size=9, color=_HIT_COLORS.get(str(ht), "#888"),
                        line=dict(width=0.5, color="#555")),
            customdata=sub[["exit_speed", "la"]].to_numpy(),
            hovertemplate=(f"{ht}<br>EV: %{{customdata[0]:.1f}} mph"
                           "<br>LA: %{customdata[1]:.0f}°<extra></extra>")))
    fig.update_layout(
        title="Launch Angle / Exit Velo", height=440, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(range=[0, 1.15], visible=False),
        yaxis=dict(range=[-1.15, 1.15], visible=False, scaleanchor="x", scaleratio=1),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def spray_fig(bip_df) -> go.Figure:
    """Spray chart: foul lines + outfield arc + infield diamond, points at (x, y)
    colored by hit type."""
    d = None
    if bip_df is not None and not bip_df.empty:
        d = bip_df[bip_df["x"].notna() & bip_df["y"].notna()]
    if d is None or d.empty:
        return _empty_bip_fig("Spray Chart")
    fig = go.Figure()
    L = 400.0
    for sgn in (-1, 1):
        t = np.radians(45.0) * sgn
        fig.add_shape(type="line", x0=0, y0=0, x1=L * np.sin(t), y1=L * np.cos(t),
                      line=dict(color="#888", width=1))
    arc = np.radians(np.linspace(-45, 45, 80))
    fig.add_trace(go.Scatter(x=L * np.sin(arc), y=L * np.cos(arc), mode="lines",
                             line=dict(color="#888", width=1), hoverinfo="skip",
                             showlegend=False))
    b = 63.6
    fig.add_shape(type="path", path=f"M 0,0 L {b},{b} L 0,{2 * b} L {-b},{b} Z",
                  line=dict(color="#bbb", width=1), fillcolor="rgba(0,0,0,0)")
    for ht, sub in d.groupby("hit_type"):
        fig.add_trace(go.Scatter(
            x=sub["x"], y=sub["y"], mode="markers", name=str(ht), showlegend=False,
            marker=dict(size=9, color=_HIT_COLORS.get(str(ht), "#888"),
                        line=dict(width=0.5, color="#555")),
            customdata=sub[["distance", "exit_speed"]].to_numpy(),
            hovertemplate=(f"{ht}<br>Dist: %{{customdata[0]:.0f}} ft"
                           "<br>EV: %{customdata[1]:.1f} mph<extra></extra>")))
    fig.update_layout(
        title="Spray Chart", height=440, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(range=[-300, 300], visible=False),
        yaxis=dict(range=[-20, 430], visible=False, scaleanchor="x", scaleratio=1),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
