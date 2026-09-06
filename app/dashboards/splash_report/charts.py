"""Script Pen Results trend chart: one line per script (1-6)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Fixed per-script colors (not cycled) so a script's line color is stable
# across re-renders regardless of which scripts happen to have data.
SCRIPT_COLORS = {
    1: "#9A0021", 2: "#0076A5", 3: "#e07b39",
    4: "#4a7fb5", 5: "#6b8e23", 6: "#7a5230",
}


def _empty_fig() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title="Script Pen Results", height=360, margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        annotations=[dict(text="No pen results for this cycle yet.",
                          showarrow=False, font=dict(size=16, family="Teko, sans-serif"))])
    return fig


def pen_results_fig(df: pd.DataFrame) -> go.Figure:
    """`df`: columns script_number/pen_number/pen_date/value (see
    `app.data.splash_report.read_pen_results`). One line per script that has
    at least one recorded value; x = pen_number (sequential within that
    script), y = value (%)."""
    if df is None or df.empty:
        return _empty_fig()
    fig = go.Figure()
    for script_number, sub in df.sort_values("pen_number").groupby("script_number"):
        color = SCRIPT_COLORS.get(int(script_number), "#888")
        fig.add_trace(go.Scatter(
            x=sub["pen_number"], y=sub["value"], mode="lines+markers",
            name=f"Script {int(script_number)}",
            line=dict(color=color, width=2), marker=dict(color=color, size=7),
            customdata=sub["pen_date"].fillna("").to_numpy(),
            hovertemplate=(f"Script {int(script_number)}<br>Pen %{{x}}"
                           "<br>%{customdata}<br>%{y:.0f}%<extra></extra>"),
        ))
    fig.update_layout(
        title="Script Pen Results", height=360, margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(title="Pen #", dtick=1), yaxis=dict(title="Result (%)"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=-0.15))
    return fig
