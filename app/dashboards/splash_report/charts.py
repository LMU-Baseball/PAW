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
    arbitrary 1st/2nd/3rd count), y = value (%). A row with no pen_date is
    dropped from the chart (nothing to plot it against on a date axis) but
    stays in the underlying data/table untouched."""
    if df is None or df.empty:
        return _empty_fig()
    dated = df.dropna(subset=["pen_date"])
    dated = dated[dated["pen_date"] != ""]
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
                           "<br>%{x}<br>%{y:.0f}%<extra></extra>"),
        ))
    fig.update_layout(
        title="Script Pen Results", height=360, margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(title="Date", type="date"), yaxis=dict(title="Result (%)"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=-0.15))
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


def movement_fig(df: pd.DataFrame) -> go.Figure:
    """`df`: columns pitch_type/pen_date/hb/ivb (see
    `app.data.splash_report.read_movement`), already scoped to ONE Pitch
    Design script. x = HB (horizontal break, in), y = IVB (induced vertical
    break, in) -- the same pair every other movement chart in the app plots
    (see `app.reports.plots`/bullpen's charts), except each dot here is a
    coach-typed session average rather than a raw tracked pitch. One trace
    per pitch_type, colored by `app.reports.plots.color_for` for visual
    consistency with the rest of the site. Wider than tall (rectangle, not
    square) per the 2026-09-16 meeting -- set via `style` on the dcc.Graph
    that wraps this, not here."""
    if df is None or df.empty:
        return _empty_movement_fig()
    d = df.dropna(subset=["hb", "ivb"], how="all")
    if d.empty:
        return _empty_movement_fig()
    fig = go.Figure()
    for pitch_type, sub in d.groupby("pitch_type"):
        color = color_for(pitch_type)
        fig.add_trace(go.Scatter(
            x=sub["hb"], y=sub["ivb"], mode="markers", name=str(pitch_type),
            marker=dict(color=color, size=10, line=dict(width=1, color="white")),
            customdata=sub["pen_date"].fillna("").to_numpy(),
            hovertemplate=(f"{pitch_type}<br>%{{customdata}}"
                           "<br>HB %{x:.1f} / IVB %{y:.1f}<extra></extra>"),
        ))
    fig.update_layout(
        title="Movement", height=280, margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(title="HB (in)", zeroline=True), yaxis=dict(title="IVB (in)", zeroline=True),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=-0.2))
    return fig
