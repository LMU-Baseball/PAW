"""Script Pen Results trend chart (one line per script) and the Pitch
Design movement plot (one script's hand-typed HB/IVB per pen session)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

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
    at least one recorded value; x = pen_date (2026-09-16: switched from the
    sequential pen_number -- Brad wanted real calendar progression, not an
    arbitrary 1st/2nd/3rd count), y = value (%). A row with no pen_date, or
    one Plotly can't actually parse, is dropped from the chart (nothing to
    plot it against on a date axis) but stays in the underlying data/table
    untouched.

    `pen_date` is a free-typed text cell (`tables.pen_results_table`), not a
    real date picker -- a coach types "9/16/26" as readily as "2026-09-16".
    Handing that raw string straight to a Plotly date axis was the actual
    2026-09-16 bug (Brad: "the xaxis starts from 2000 ... there is no data
    then"): Plotly's client-side date parser mis-reads "9/16/26" and the
    real points render far outside the default-autoscaled 2000-2001 view,
    so they're invisible, not missing. Parsing with `pd.to_datetime` HERE
    (pandas' parser correctly reads both "9/16/26" and "2026-09-16" as
    2026-09-16) and handing Plotly real Timestamps instead of the raw string
    fixes that regardless of what format a coach happened to type."""
    if df is None or df.empty:
        return _empty_fig()
    d = df.copy()
    # format="mixed": coaches type both "9/16/26" and "2026-09-16" across
    # different rows, so a single fixed format would reject one or the
    # other -- this parses each value on its own terms instead.
    d["pen_date"] = pd.to_datetime(d["pen_date"], errors="coerce", format="mixed")
    dated = d.dropna(subset=["pen_date"])
    if dated.empty:
        return _empty_fig()
    fig = go.Figure()
    for script_number, sub in dated.sort_values("pen_date").groupby("script_number"):
        color = SCRIPT_COLORS.get(int(script_number), "#888")
        fig.add_trace(go.Scatter(
            x=sub["pen_date"], y=sub["value"], mode="lines+markers",
            name=f"Script {int(script_number)}",
            line=dict(color=color, width=2), marker=dict(color=color, size=7),
            hovertemplate=(f"Script {int(script_number)}"
                           "<br>%{x|%Y-%m-%d}<br>%{y:.0f}%<extra></extra>"),
        ))
    fig.update_layout(
        # 2026-09-17 (Brad, screenshot): the "Date" axis title and the
        # legend row were landing on top of each other -- b=40 only left
        # room for the tick labels themselves, not the title below them AND
        # a legend below that. Taller bottom margin + legend pushed further
        # down (y is fraction of the whole figure, not just the plot area)
        # gives each its own row instead of stacking.
        title="Script Pen Results", height=380, margin=dict(l=40, r=20, t=50, b=90),
        xaxis=dict(title="Date", type="date"), yaxis=dict(title="Result (%)"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=-0.35, x=0.5, xanchor="center"))
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
        title="Movement", height=340, margin=dict(l=40, r=20, t=50, b=90),
        xaxis=dict(title="HB (in)", zeroline=True), yaxis=dict(title="IVB (in)", zeroline=True),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=-0.32, x=0.5, xanchor="center"))
    return fig
