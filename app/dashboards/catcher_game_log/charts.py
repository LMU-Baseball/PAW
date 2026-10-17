"""Catching Game Log play-detail figure: the catcher's taken pitches this game
on the Catching dashboard's framing chart (stolen black / lost crimson /
correct grey, catcher view), with the selected pitch starred."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.dashboards.catching import charts as ccharts
from app.dashboards.shell import CRIMSON


def framing_fig(taken: pd.DataFrame, selected: pd.Series | None, catcher: str) -> go.Figure:
    d = pd.DataFrame({
        "plate_loc_side": taken["PlateLocSide"], "plate_loc_height": taken["PlateLocHeight"],
        "pitch_call": taken["PitchCall"], "tagged_pitch_type": taken["TaggedPitchType"],
        "rel_speed": taken["RelSpeed"], "batter_side": taken["BatterSide"],
        "pitcher_throws": taken["PitcherThrows"],
    })
    fig = ccharts.framing_scatter(d)
    if selected is not None and pd.notna(selected["fx"]) and pd.notna(selected["fy"]):
        fig.add_trace(go.Scatter(
            x=[selected["fx"]], y=[selected["fy"]], mode="markers", showlegend=False,
            marker=dict(symbol="star", size=24, color=CRIMSON, line=dict(color="white", width=1.5)),
            hovertemplate=f"This pitch · {selected['Result']}<extra></extra>"))
    fig.update_layout(title=dict(text=f"{catcher} — taken pitches this game", x=0.5,
                                 font=dict(size=18)),
                      height=360, margin=dict(l=6, r=6, t=40, b=6))
    return fig
