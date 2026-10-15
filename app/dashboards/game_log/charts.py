"""Game Log play-detail figures: the at-bat's pitch sequence in the zone, and
the hitter's balls in play with the selected one highlighted. Both reuse the
Hitting dashboard's zone geometry / spray field so they read the same."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.dashboards.hitting import charts as hcharts
from app.dashboards.shell import CRIMSON

_FONT = dict(family="Teko, sans-serif")


def pa_zone_fig(pa: pd.DataFrame, selected_uid: str | None) -> go.Figure:
    """Every pitch of the at-bat, numbered in order, selected pitch ringed."""
    fig = go.Figure()
    hcharts._add_zone_shapes(fig)
    d = hcharts._to_xy(pa) if pa is not None and not pa.empty else pd.DataFrame()
    for ptype, g in (d.groupby("TaggedPitchType", sort=False) if not d.empty else []):
        sel = g["PitchUID"] == selected_uid
        fig.add_trace(go.Scatter(
            x=g["_x"], y=g["_y"], mode="markers+text", name=g["Type"].iloc[0] or str(ptype),
            text=g["PitchofPA"].astype(int).astype(str), textposition="middle center",
            textfont=dict(color="white", size=13, family="Teko, sans-serif"),
            marker=dict(size=[30 if s else 22 for s in sel], color=hcharts.color_for(ptype),
                        line=dict(color=[CRIMSON if s else "white" for s in sel],
                                  width=[4 if s else 1 for s in sel])),
            customdata=g[["Count", "Result", "Velo"]].fillna("").to_numpy(),
            hovertemplate=(f"<b>{ptype}</b> %{{customdata[2]}}<br>%{{customdata[0]}} · "
                           "%{customdata[1]}<extra></extra>"),
        ))
    hcharts._style_axes(fig)
    fig.update_layout(
        title=dict(text="At-Bat Pitch Sequence", x=0.5, font=dict(size=18)),
        margin=dict(l=6, r=6, t=40, b=6), height=360,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        legend=dict(orientation="h", y=-0.02), font=_FONT)
    return fig


def spray_highlight_fig(bips: pd.DataFrame, selected_uid: str | None, title: str) -> go.Figure:
    """The hitter's balls in play this game (faded), selected one as a star."""
    fig = hcharts.spray_fig(bips)
    if bips is None or bips.empty:
        fig.update_layout(title=title)
        return fig
    for tr in fig.data:
        if tr.mode == "markers":
            tr.marker.opacity = 0.35
    sel = bips[(bips["PitchUID"] == selected_uid) & bips["x"].notna() & bips["y"].notna()]
    if not sel.empty:
        r = sel.iloc[0]
        fig.add_trace(go.Scatter(
            x=[r["x"]], y=[r["y"]], mode="markers", showlegend=False,
            marker=dict(symbol="star", size=22, color=CRIMSON, line=dict(color="white", width=1.5)),
            hovertemplate=(f"{r['Result']}<br>EV {r['exit_speed']:.1f} · "
                           f"{r['distance']:.0f} ft<extra></extra>")))
    fig.update_layout(title=dict(text=title, x=0.5, font=dict(size=18)), height=360,
                      margin=dict(l=6, r=6, t=40, b=6))
    return fig
