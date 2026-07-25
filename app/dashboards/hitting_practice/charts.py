"""Plotly figures for HitTrax practice dashboard."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data import practice as P
from app.dashboards.shell import CRIMSON

_BLUE = "#0076A5"
_CRIMSON_SCALE = [[0.0, "rgb(253,234,238)"], [0.5, "rgb(200,90,110)"], [1.0, "#9A0021"]]


_METRIC_CFG = {
    "contact": ("Contact %", _CRIMSON_SCALE, (0, 100), "Contact Rate"),
    "ev": ("Avg EV (mph)", _CRIMSON_SCALE, (None, None), "Avg Exit Velocity"),
    "distance": ("Avg Dist (ft)", _CRIMSON_SCALE, (None, None), "Avg Distance"),
}


def pitch_zone_heatmap(df: pd.DataFrame, metric: str = "contact") -> go.Figure:
    label, scale, (zmin, zmax), title = _METRIC_CFG.get(metric, _METRIC_CFG["contact"])
    z, xedges, yedges = P.heatmap_metric(df, metric)
    x_centers = (xedges[:-1] + xedges[1:]) / 2
    y_centers = (yedges[:-1] + yedges[1:]) / 2
    fig = go.Figure(data=go.Heatmap(
        z=z, x=x_centers, y=y_centers, colorscale=scale,
        zmin=zmin, zmax=zmax, colorbar=dict(title=label),
        hovertemplate=("Horizontal: %{x:.2f} ft<br>Height: %{y:.2f} ft<br>"
                       f"{label}: %{{z:.1f}}<extra></extra>"),
    ))
    fig.add_shape(type="rect", x0=P.SZ_X0, y0=P.SZ_Y0, x1=P.SZ_X1, y1=P.SZ_Y1,
                  line=dict(color="black", width=2), fillcolor="rgba(0,0,0,0)")
    fig.update_layout(
        title=f"Pitch Zones — {title} (Catcher's View)",
        xaxis_title="Horizontal (ft)", yaxis_title="Height (ft)",
        yaxis=dict(scaleanchor="x", scaleratio=1),
        height=480, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
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
        hovertemplate="Pitch #: %{x}<br>Exit Velo: %{y:.1f} mph<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=d["pitch_n"], y=d["distance_feet"], name="Distance",
        mode="lines+markers", line=dict(color=_BLUE),
        hovertemplate="Pitch #: %{x}<br>Distance: %{y:.0f} ft<extra></extra>",
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


_HIT_COLORS = P.HIT_TYPE_COLORS


def _crimson_shade(frac: float) -> str:
    """Light-pink -> brand crimson by fraction 0..1."""
    frac = max(0.0, min(1.0, frac))
    c0, c1 = (253, 234, 238), (154, 0, 33)
    r, g, b = (round(c0[i] + (c1[i] - c0[i]) * frac) for i in range(3))
    return f"rgb({r},{g},{b})"


def _fan_field(fig: go.Figure) -> None:
    L = P.FAN_DISPLAY_MAX
    # foul lines from home plate along +/-45 deg
    for sgn in (-1, 1):
        th = np.radians(45.0) * sgn
        fig.add_shape(type="line", x0=0, y0=0, x1=L * np.sin(th), y1=L * np.cos(th),
                      line=dict(color="#888", width=1))
    # outer arc
    ts = np.radians(np.linspace(-45, 45, 40))
    xs, ys = L * np.sin(ts), L * np.cos(ts)
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    fig.add_shape(type="path", path=path, line=dict(color="#888", width=1))


def spray_distribution_fan(fan_df: pd.DataFrame) -> go.Figure:
    """Filled fan: each cell shaded by its share of batted balls + % label."""
    fig = go.Figure()
    _fan_field(fig)
    annotations = []
    if fan_df is not None and not fan_df.empty:
        maxpct = max(float(fan_df["pct"].max()), 1e-9)
        for _, row in fan_df.iterrows():
            if row["count"] <= 0:
                continue
            a0, a1 = np.radians(row["a0"]), np.radians(row["a1"])
            r0, r1 = float(row["r0"]), float(row["r1"])
            ts = np.linspace(a0, a1, 12)
            outer = [(r1 * np.sin(t), r1 * np.cos(t)) for t in ts]
            inner = [(r0 * np.sin(t), r0 * np.cos(t)) for t in ts[::-1]]
            poly = outer + inner
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", fill="toself",
                fillcolor=_crimson_shade(float(row["pct"]) / (maxpct)),
                line=dict(color="#bbb", width=0.5), showlegend=False,
                hovertext=f"{row['direction']} · {row['ring']}: "
                          f"{row['pct']:.0f}% ({int(row['count'])})",
                hoverinfo="text"))
            mid_a = (a0 + a1) / 2; mid_r = (r0 + r1) / 2
            annotations.append(dict(x=mid_r * np.sin(mid_a), y=mid_r * np.cos(mid_a),
                                    text=f"{row['pct']:.0f}%", showarrow=False,
                                    font=dict(family="Teko, sans-serif", size=14,
                                              color="#1a1a1a")))
    fig.update_layout(
        title="Batted-Ball Distribution", annotations=annotations,
        xaxis=dict(range=[-P.FAN_DISPLAY_MAX, P.FAN_DISPLAY_MAX], visible=False),
        yaxis=dict(range=[-20, P.FAN_DISPLAY_MAX + 20], visible=False,
                   scaleanchor="x", scaleratio=1),
        height=460, margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def _date_labels(series: pd.Series) -> pd.Series:
    """Human-readable date labels from either date/datetime values or the
    int64 epoch-ms that a dcc.Store JSON round-trip produces."""
    s = pd.Series(series)
    if pd.api.types.is_numeric_dtype(s):
        dt = pd.to_datetime(s, unit="ms")
    else:
        dt = pd.to_datetime(s, errors="coerce")
    return dt.dt.strftime("%b %d")


def swing_decision_trend_fig(trend_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if trend_df is not None and not trend_df.empty:
        x = _date_labels(trend_df["play_date"])
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["score"], mode="lines+markers", name="Swing Decision Score",
            line=dict(color=CRIMSON, width=2), marker=dict(color=CRIMSON, size=9)))
        fig.add_hline(y=0, line=dict(color="#bbb", width=1))
    fig.update_layout(
        title="Swing Decision Score by Session (In-Zone % − Chase %)",
        xaxis_title="Session date", yaxis_title="Score",
        xaxis=dict(type="category"),
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def spray_chart_fig(spray_df: pd.DataFrame) -> go.Figure:
    """Plotly-drawn field + batted-ball landing points colored by hit type."""
    fig = go.Figure()
    # Field: foul lines from home (0,0), outfield arc (~330ft), infield diamond.
    L = 330.0
    fig.add_shape(type="line", x0=0, y0=0, x1=-L * 0.707, y1=L * 0.707,
                  line=dict(color="#888", width=1))
    fig.add_shape(type="line", x0=0, y0=0, x1=L * 0.707, y1=L * 0.707,
                  line=dict(color="#888", width=1))
    fig.add_shape(type="path",
                  path=f"M {-L*0.707},{L*0.707} Q 0,{L*1.15} {L*0.707},{L*0.707}",
                  line=dict(color="#888", width=1))
    # infield diamond (~90ft bases, rotated): home->1st->2nd->3rd
    b = 63.6  # 90/sqrt(2)
    fig.add_shape(type="path",
                  path=f"M 0,0 L {b},{b} L 0,{2*b} L {-b},{b} Z",
                  line=dict(color="#bbb", width=1), fillcolor="rgba(0,0,0,0)")
    if spray_df is not None and not spray_df.empty:
        has_hover = {"distance_feet", "exit_velocity"} <= set(spray_df.columns)
        for label, sub in spray_df.groupby("hit_type_label"):
            trace = dict(x=sub["x"], y=sub["y"], mode="markers", name=str(label),
                         marker=dict(color=_HIT_COLORS.get(label, "#5a5a5a"), size=8,
                                     line=dict(width=0.5, color="#666")))
            if has_hover:
                trace["customdata"] = sub[["distance_feet", "exit_velocity"]].to_numpy()
                trace["hovertemplate"] = (f"{label}<br>Distance: %{{customdata[0]:.0f}} ft"
                                          "<br>Exit Velo: %{customdata[1]:.1f} mph<extra></extra>")
            fig.add_trace(go.Scatter(**trace))
    fig.update_layout(
        title="Spray Chart", showlegend=True,
        xaxis=dict(range=[-260, 260], visible=False),
        yaxis=dict(range=[-20, 400], visible=False, scaleanchor="x", scaleratio=1),
        height=460, margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def contact_type_bar(counts_df: pd.DataFrame) -> go.Figure:
    """Vertical bar of hit-type counts, sorted descending, colored per hit type."""
    fig = go.Figure()
    if counts_df is not None and not counts_df.empty:
        d = counts_df.sort_values("Count", ascending=False)
        colors = [_HIT_COLORS.get(ht, "#5a5a5a") for ht in d["Hit Type"]]
        fig.add_trace(go.Bar(x=d["Hit Type"], y=d["Count"], marker_color=colors,
                             text=d["Count"], textposition="outside"))
    fig.update_layout(
        title="Contact Type", yaxis_title="Count",
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
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
