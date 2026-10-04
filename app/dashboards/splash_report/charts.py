"""Script Pen Results trend chart (one line per script) and the Pitch
Design movement plot (per-script average HB/IVB per pitch type)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.dashboards.bullpen.charts import _ellipse_xy
from app.reports.plots import color_for

# Fixed per-script colors (not cycled) so a script's line color is stable
# across re-renders regardless of which scripts happen to have data.
SCRIPT_COLORS = {
    1: "#9A0021", 2: "#0076A5", 3: "#e07b39",
    4: "#4a7fb5", 5: "#6b8e23", 6: "#7a5230",
}


def _empty_fig() -> go.Figure:
    # Shorter than the real chart (360px) -- a full-height reserved chart
    # area with nothing in it but a caption was one of the bigger blank
    # spots on the page (2026-09-10 planning session: "eliminate as much
    # white space as possible"); once real data exists the figure grows
    # back to its normal height.
    fig = go.Figure()
    fig.update_layout(
        title="Script Pen Results", height=160, margin=dict(l=40, r=20, t=50, b=20),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        annotations=[dict(text="No pen results for this cycle yet.",
                          showarrow=False, font=dict(size=16, family="Teko, sans-serif"))])
    return fig


def pen_results_fig(df: pd.DataFrame) -> go.Figure:
    """`df`: columns script_number/pen_number/pen_date/value (see
    `app.data.splash_report.read_pen_results`). One line per script that has
    at least one recorded value; x = which time that script was thrown
    (1st, 2nd, 3rd...), y = value (%).

    2026-09-26, Brad: switched from a calendar-date x-axis back to a
    per-script instance count -- each script is thrown several times on
    different days, so a date axis scattered the scripts across the chart;
    lining up every script's 1st throw at x=1 lets the attempts connect and
    compare directly. Instances are ordered by pen_date, then pen_number, so
    the date still drives the order (and shows in the hover) without being
    the axis. `pen_date` is a free-typed text cell ("9/16/26" or
    "2026-09-16"), hence `pd.to_datetime(format="mixed")`; an undated or
    unparseable row sorts after the dated ones rather than being dropped."""
    if df is None or df.empty:
        return _empty_fig()
    d = df.dropna(subset=["value"]).copy()
    if d.empty:
        return _empty_fig()
    d["pen_date"] = pd.to_datetime(d["pen_date"], errors="coerce", format="mixed")
    d = d.sort_values(["script_number", "pen_date", "pen_number"], na_position="last")
    d["instance"] = d.groupby("script_number").cumcount() + 1
    d["date_label"] = d["pen_date"].dt.strftime("%Y-%m-%d").fillna("no date")
    fig = go.Figure()
    for script_number, sub in d.groupby("script_number"):
        color = SCRIPT_COLORS.get(int(script_number), "#888")
        fig.add_trace(go.Scatter(
            x=sub["instance"], y=sub["value"], mode="lines+markers",
            name=f"Script {int(script_number)}",
            line=dict(color=color, width=3),
            marker=dict(color=color, size=9, line=dict(width=1.5, color="white")),
            customdata=sub[["date_label"]].to_numpy(),
            hovertemplate=(f"Script {int(script_number)} - #%{{x}}"
                           "<br>%{customdata[0]}<br>%{y:.1f}<extra></extra>"),
        ))
        # 2026-10-04 (Brad: "the script lines are really close together"):
        # name each line at its last point so it reads without the legend.
        last = sub.iloc[-1]
        fig.add_annotation(x=last["instance"], y=last["value"], text=f"S{int(script_number)}",
                           xanchor="left", xshift=8, showarrow=False,
                           font=dict(color=color, size=14, family="Teko, sans-serif"))
    y_min, y_max = float(d["value"].min()), float(d["value"].max())
    y_pad = max(3.0, (y_max - y_min) * 0.08)
    grid = "rgba(0,0,0,0.07)"
    fig.update_layout(
        # 2026-09-17 (Brad, screenshot): the x-axis title and the legend row
        # were landing on top of each other -- taller bottom margin + legend
        # pushed further down gives each its own row instead of stacking.
        title="Script Pen Results", height=440, margin=dict(l=45, r=40, t=50, b=90),
        xaxis=dict(title="Time Thrown", tickmode="linear", tick0=1, dtick=1,
                   range=[0.7, int(d["instance"].max()) + 0.6], gridcolor=grid),
        yaxis=dict(title="Result", range=[y_min - y_pad, y_max + y_pad], gridcolor=grid),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"), hovermode="closest",
        legend=dict(orientation="h", y=-0.3, x=0.5, xanchor="center"))
    return fig


def _empty_movement_fig() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title="Movement", height=220, margin=dict(l=40, r=20, t=50, b=20),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        annotations=[dict(text="No movement logged for this script yet.",
                          showarrow=False, font=dict(size=14, family="Teko, sans-serif"))])
    return fig


def scripts_movement_fig(movement_by_script: dict, selected: list[int] | None = None) -> go.Figure:
    """One dot per (script, pitch_type) -- the AVERAGE HB/IVB across every
    pen-session entry logged for that script+pitch_type. `movement_by_script`:
    {str(script_number): [row dicts with pitch_type/hb/ivb]} (see
    `app.data.splash_report.read_all_movement`); `selected` narrows which
    script numbers are included (mirrors "Compare Scripts"), None/empty
    means all six.

    2026-09-16, Brad: reworked from a per-script detail panel (one dot per
    pen session, only visible after picking a script in "Show Scripts") to
    this single shared chart, always visible right under Script Pen
    Results -- "each dot represents the average from that script... a dot
    for each script based on the pitch type." Each dot is labeled with its
    script number directly on the chart (not just in the hover), since
    several scripts can share the same pitch type (and therefore color)."""
    frames = []
    for key, rows in (movement_by_script or {}).items():
        try:
            n = int(key)
        except (TypeError, ValueError):
            continue
        if selected and n not in selected:
            continue
        d = pd.DataFrame(rows)
        if d.empty:
            continue
        d["script_number"] = n
        frames.append(d)
    if not frames:
        return _empty_movement_fig()
    all_rows = pd.concat(frames, ignore_index=True).dropna(subset=["hb", "ivb"], how="all")
    if all_rows.empty:
        return _empty_movement_fig()
    agg = all_rows.groupby(["script_number", "pitch_type"], as_index=False).agg(
        hb=("hb", "mean"), ivb=("ivb", "mean"), sessions=("hb", "size"))
    fig = go.Figure()
    # 2026-09-26, Brad: once more than one script is on the chart, add the
    # same faint 1-sigma pitch-type ellipse the other movement charts use
    # (`bullpen.charts.movement_fig`). Dots stay per-script averages; the
    # ellipse is built from the underlying per-session entries, since a
    # handful of averaged dots is too few points for a covariance ellipse.
    xs, ys = list(all_rows["hb"].dropna()), list(all_rows["ivb"].dropna())
    if agg["script_number"].nunique() > 1:
        for pitch_type, raw in all_rows.groupby("pitch_type"):
            ell = _ellipse_xy(raw["hb"], raw["ivb"])
            if ell is None:
                continue
            xs += list(ell[0])
            ys += list(ell[1])
            color = color_for(pitch_type)
            fig.add_trace(go.Scatter(
                x=ell[0], y=ell[1], mode="lines", fill="toself", fillcolor=color,
                opacity=0.22, line=dict(color=color, width=1.5),
                showlegend=False, hoverinfo="skip"))
    for pitch_type, sub in agg.groupby("pitch_type"):
        color = color_for(pitch_type)
        fig.add_trace(go.Scatter(
            x=sub["hb"], y=sub["ivb"], mode="markers+text", name=str(pitch_type),
            text=[f"S{n}" for n in sub["script_number"]], textposition="top center",
            textfont=dict(size=11, family="Teko, sans-serif"),
            marker=dict(color=color, size=13, line=dict(width=1, color="white")),
            customdata=sub[["script_number", "sessions"]].to_numpy(),
            hovertemplate=(f"{pitch_type}<br>Script %{{customdata[0]}}"
                           "<br>HB %{x:.1f} / IVB %{y:.1f}"
                           "<br>avg of %{customdata[1]} session(s)<extra></extra>"),
        ))
    fig.update_layout(
        # Same fix as pen_results_fig: the "HB (in)" axis title and the
        # pitch-type legend were overlapping with only b=40/y=-0.2 to work
        # with -- taller bottom margin + legend pushed further down gives
        # the title its own row above the legend.
        # Explicit padded ranges (2026-10-04): autorange hugged the outermost
        # dot, clipping its "S#" label and the edge of its ellipse.
        title="Movement", height=400, margin=dict(l=45, r=20, t=50, b=90),
        xaxis=dict(title="HB (in)", zeroline=True, range=[min(xs) - 3, max(xs) + 3],
                   gridcolor="rgba(0,0,0,0.07)"),
        yaxis=dict(title="IVB (in)", zeroline=True, range=[min(ys) - 3, max(ys) + 4],
                   gridcolor="rgba(0,0,0,0.07)"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=-0.32, x=0.5, xanchor="center"))
    return fig
