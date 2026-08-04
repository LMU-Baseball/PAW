"""Plotly figure builders for the bullpen dashboard (snake_case bullpen cols).

Interactive counterparts to app/reports/bullpen_plots.py (matplotlib, PDF).
Pitch-type color always via plots.color_for for cross-app consistency.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.reports.plots import color_for

_BASE = dict(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
             margin=dict(l=45, r=20, t=42, b=42), showlegend=True,
             font=dict(family="Teko, sans-serif", size=14),
             title_font=dict(color="#9A0021", size=16))
_ZONE = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)  # standard strike-zone box (ft)


def _ellipse_xy(xs, ys, n_std=1.0, n=40):
    xs = np.asarray(xs, float); ys = np.asarray(ys, float)
    m = np.isfinite(xs) & np.isfinite(ys)
    xs, ys = xs[m], ys[m]
    if len(xs) < 3:
        return None
    cov = np.cov(xs, ys)
    if not np.all(np.isfinite(cov)):
        return None
    vals, vecs = np.linalg.eigh(cov)
    order = vals.argsort()[::-1]; vals, vecs = vals[order], vecs[:, order]
    t = np.linspace(0, 2 * np.pi, n)
    ell = vecs @ ((n_std * np.sqrt(np.maximum(vals, 0)))[:, None] * np.array([np.cos(t), np.sin(t)]))
    return ell[0] + xs.mean(), ell[1] + ys.mean()


def _add_zone(fig):
    """Strike-zone box + nine-pocket 3x3 grid."""
    z = _ZONE
    fig.add_shape(type="rect", x0=z["x0"], x1=z["x1"], y0=z["y0"], y1=z["y1"],
                  line=dict(color="black", width=1.5))
    for i in (1, 2):
        xi = z["x0"] + (z["x1"] - z["x0"]) * i / 3
        yi = z["y0"] + (z["y1"] - z["y0"]) * i / 3
        fig.add_shape(type="line", x0=xi, x1=xi, y0=z["y0"], y1=z["y1"],
                      line=dict(color="#bbb", width=0.8))
        fig.add_shape(type="line", x0=z["x0"], x1=z["x1"], y0=yi, y1=yi,
                      line=dict(color="#bbb", width=0.8))


def _empty(msg="No data"):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=16, color="#888"))
    fig.update_layout(**_BASE)
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return fig


def _types(df):
    return list(df.groupby("tagged_pitch_type").groups)


def pitch_freq_bar(df):
    """Horizontal stacked bar of pitch-type mix for a session (width = count)."""
    if df is None or df.empty:
        return _empty()
    vc = df["tagged_pitch_type"].value_counts()
    total = int(vc.sum())
    fig = go.Figure()
    for pt, n in vc.items():
        fig.add_trace(go.Bar(y=["mix"], x=[int(n)], name=str(pt), orientation="h",
            marker_color=color_for(pt), text=[int(n)], textposition="inside",
            hovertemplate=f"{pt}: {int(n)}<extra></extra>"))
    fig.update_layout(barmode="stack", **_BASE)
    fig.update_layout(title=f"Pitch Frequency (Total {total})", showlegend=True,
                      height=180, yaxis_visible=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    return fig


def velo_fig(df):
    """Horizontal range-lollipop per pitch type: min-max bar + avg dot + label."""
    if df is None or df.empty:
        return _empty()
    rows = []
    for pt, sub in df.groupby("tagged_pitch_type"):
        v = sub["rel_speed"].dropna()
        if v.empty:
            continue
        rows.append((str(pt), float(v.min()), float(v.max()), float(v.mean())))
    if not rows:
        return _empty()
    rows.sort(key=lambda r: r[3])  # slowest at bottom, fastest on top
    fig = go.Figure()
    for i, (pt, vmin, vmax, vavg) in enumerate(rows):
        y = i + 1
        col = color_for(pt)
        fig.add_trace(go.Scatter(x=[vmin, vmax], y=[y, y], mode="lines",
            line=dict(color=col, width=6), opacity=0.35, showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[vavg], y=[y], mode="markers+text",
            marker=dict(size=15, color=col, line=dict(width=1, color="white")),
            text=[f"{vavg:.1f}"], textposition="middle right",
            textfont=dict(size=12, color="#222"), showlegend=False,
            customdata=[[pt, vmin, vmax]],
            hovertemplate="%{customdata[0]}<br>Velo: %{x:.1f} mph<br>"
                          "Range: %{customdata[1]:.1f}–%{customdata[2]:.1f}<extra></extra>"))
    fig.update_layout(**_BASE)
    fig.update_layout(title="Velocity by pitch type", xaxis_title="mph", showlegend=False)
    fig.update_yaxes(tickvals=list(range(1, len(rows) + 1)),
                     ticktext=[r[0] for r in rows], range=[0.4, len(rows) + 0.7])
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    return fig


def movement_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["horz_break"], y=sub["ind_vert_break"], mode="markers", name=str(pt),
            marker=dict(size=10, color=color_for(pt), line=dict(width=0.5, color="white")),
            customdata=[[str(pt)]] * len(sub),
            hovertemplate="%{customdata[0]}<br>IVB: %{y:.1f} in · HB: %{x:.1f} in<extra></extra>"))
        ell = _ellipse_xy(sub["horz_break"], sub["ind_vert_break"])
        if ell is not None:
            fig.add_trace(go.Scatter(x=ell[0], y=ell[1], mode="lines", fill="toself",
                fillcolor=color_for(pt), opacity=0.15, line=dict(color=color_for(pt), width=1),
                showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[sub["horz_break"].mean()], y=[sub["ind_vert_break"].mean()],
            mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=13, color="white", line=dict(width=2, color=color_for(pt)))))
    fig.add_hline(y=0, line_color="#ccc"); fig.add_vline(x=0, line_color="#ccc")
    fig.update_layout(title="Movement", xaxis_title="HB (in)", yaxis_title="IVB (in)", **_BASE)
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    fig.update_yaxes(scaleanchor="x", scaleratio=1, showgrid=True, gridcolor="#eee")
    return fig


def release_fig(df):
    """Release-point dispersion: equal aspect, per-type 1σ ellipse + mean marker."""
    if df is None or df.empty:
        return _empty()
    d = df.dropna(subset=["rel_side", "rel_height"])
    if d.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(d):
        sub = d[d["tagged_pitch_type"] == pt]
        col = color_for(pt)
        ell = _ellipse_xy(sub["rel_side"], sub["rel_height"])
        if ell is not None:
            fig.add_trace(go.Scatter(x=ell[0], y=ell[1], mode="lines", fill="toself",
                fillcolor=col, opacity=0.15, line=dict(color=col, width=1),
                showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=sub["rel_side"], y=sub["rel_height"], mode="markers",
            name=str(pt), marker=dict(size=9, color=col, line=dict(width=0.5, color="white")),
            customdata=[[str(pt)]] * len(sub),
            hovertemplate="%{customdata[0]}<br>Rel H: %{y:.2f} ft · Rel S: %{x:.2f} ft<extra></extra>"))
        fig.add_trace(go.Scatter(x=[sub["rel_side"].mean()], y=[sub["rel_height"].mean()],
            mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=13, color="white", line=dict(width=2, color=col))))
    fig.update_layout(**_BASE)
    fig.update_layout(title="Release", xaxis_title="Rel side (ft)", yaxis_title="Rel height (ft)")
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    fig.update_yaxes(scaleanchor="x", scaleratio=1, showgrid=True, gridcolor="#eee")
    return fig


def location_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    _add_zone(fig)
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=str(pt),
            marker=dict(size=9, color=color_for(pt), line=dict(width=0.5, color="white")),
            customdata=[[str(pt)]] * len(sub),
            hovertemplate="%{customdata[0]}<br>Side: %{x:.2f} · Height: %{y:.2f} ft<extra></extra>"))
    fig.update_layout(title="Location", **_BASE)
    fig.update_xaxes(range=[-2.5, 2.5], visible=False)
    fig.update_yaxes(range=[0, 5], visible=False, scaleanchor="x", scaleratio=1)
    return fig


# Per-metric series for the trend small-multiples. Each entry:
#   (df_column, legend_label, line_dash, on_secondary_y_axis)
# Labels are plain words (a top legend names each line) — no parenthetical
# solid/dashed decoding. Spin puts Efficiency on a secondary axis because its
# scale (~40-96%) is dwarfed by Spin Rate (~2000 rpm).
_METRIC_SERIES = {
    "velocity": [("velo_avg", "Avg", None, False), ("velo_max", "Max", "dash", False)],
    "spin": [("spin_avg", "Spin Rate", None, False),
             ("eff_avg", "Efficiency %", "dot", True)],
    "movement": [("ivb_avg", "IVB", None, False), ("hb_avg", "HB", "dash", False)],
    "command": [("loc_spread", "Location Spread", None, False)],
}
_METRIC_YTITLE = {"velocity": "mph", "spin": "rpm", "movement": "inches",
                  "command": "spread"}


def trend_small_multiples(df, metric):
    if df is None or df.empty:
        return _empty("Need at least 2 sessions to show a trend.")
    types = sorted(df["tagged_pitch_type"].unique())
    series = _METRIC_SERIES.get(metric, _METRIC_SERIES["velocity"])
    has_secondary = any(s[3] for s in series)
    ncols = 2
    nrows = (len(types) + 1) // 2
    specs = [[{"secondary_y": has_secondary} for _ in range(ncols)] for _ in range(nrows)]
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=types, specs=specs,
                        vertical_spacing=0.16, horizontal_spacing=0.10)
    for i, pt in enumerate(types):
        r, c = i // ncols + 1, i % ncols + 1
        sub = df[df["tagged_pitch_type"] == pt].sort_values("date")
        col = color_for(pt)
        for key, label, dash, secondary in series:
            # Show the legend once (first panel) with plain-word labels so both
            # lines are named; legendgroup keeps later panels from duplicating.
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub[key], mode="lines+markers", name=label,
                legendgroup=label, showlegend=(i == 0),
                line=dict(color=col, dash=dash),
                hovertemplate=f"{label}: %{{y:.1f}}<extra></extra>"),
                row=r, col=c, secondary_y=secondary)
    fig.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                      font=dict(family="Teko, sans-serif", size=13),
                      title_font=dict(color="#9A0021"),
                      margin=dict(l=40, r=20, t=54, b=30),
                      height=max(280, 250 * nrows),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    fig.update_yaxes(showgrid=True, gridcolor="#eee")
    return fig
