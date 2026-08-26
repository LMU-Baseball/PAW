"""Plotly figures for the catching dashboard (pure functions of pitch DataFrames).

Framing scatter/facets use the legacy stolen/lost color scheme over a catcher-view
strike-zone frame (home-plate pentagon + nested rulebook/Heart/Shadow rectangles).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data import catching as C
from app.data import called_strike as cs
from app.data import catching_caps
from app.dashboards.shell import CRIMSON

CALLTYPE_COLORS = {
    "Stolen Strike": "#000000",
    "Lost Strike": "#9A0021",
    "Correct Call": "#cccccc",
}
_ORDER = ["Correct Call", "Stolen Strike", "Lost Strike"]  # draw grey first


def _zone_frame(fig, row=None, col=None):
    """Catcher-view zone frame in inches (matches src/app.R)."""
    def seg(x0, y0, x1, y1):
        fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="black", width=1), row=row, col=col)
    def rect(x0, y0, x1, y1, dash=None, width=1.5):
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="black", width=width,
                                dash=dash) if dash else dict(color="black", width=width),
                      fillcolor="rgba(0,0,0,0)", row=row, col=col)
    # home-plate pentagon
    seg(-9, -21.5, 9, -21.5); seg(-9, -21.5, -9, -23.5); seg(9, -21.5, 9, -23.5)
    seg(-9, -23.5, 0, -25); seg(9, -23.5, 0, -25)
    # rulebook box (solid) + Heart + wide (dashed)
    rect(-10, -13, 10, 13, width=1.5)
    rect(-7.25, -8.75, 7.25, 8.75, dash="dash", width=1)
    rect(-13.5, -16, 13.5, 16, dash="dash", width=1)


def _base_axes(fig, row=None, col=None):
    fig.update_xaxes(range=[-40, 40], visible=False, row=row, col=col)
    fig.update_yaxes(range=[-25, 25], visible=False, row=row, col=col)


def _hover_texts(sub: pd.DataFrame) -> list[str]:
    """Per-point hover strings: Velo/BatSide/PitchSide/PitchSpeed/PitchCall
    (legacy hover fields), built defensively so a missing column never raises."""
    n = len(sub)
    velo = sub["rel_speed"] if "rel_speed" in sub.columns else None
    bat_side = sub["batter_side"] if "batter_side" in sub.columns else None
    pitcher_throws = sub["pitcher_throws"] if "pitcher_throws" in sub.columns else None
    pitch_speed = sub["PitchSpeed"] if "PitchSpeed" in sub.columns else None
    pitch_call = sub["pitch_call"] if "pitch_call" in sub.columns else None
    out = []
    for i in range(n):
        lines = []
        if velo is not None:
            v = velo.iloc[i]
            if pd.notna(v):
                lines.append(f"Velo: {float(v):.1f}")
        if bat_side is not None:
            lines.append(f"BatSide: {bat_side.iloc[i]}")
        if pitcher_throws is not None:
            lines.append(f"PitchSide: {pitcher_throws.iloc[i]}")
        if pitch_speed is not None:
            lines.append(f"PitchSpeed: {pitch_speed.iloc[i]}")
        if pitch_call is not None:
            lines.append(f"PitchCall: {pitch_call.iloc[i]}")
        out.append("<br>".join(lines))
    return out


def _scatter_traces(fig, d, row=None, col=None, shown=None):
    if shown is None:
        shown = set()
    for ct in _ORDER:
        sub = d[d["CallType"] == ct]
        if sub.empty:
            continue
        showlegend = ct not in shown
        shown.add(ct)
        fig.add_trace(go.Scatter(
            x=sub["_x"], y=sub["_y"], mode="markers", name=ct,
            legendgroup=ct, showlegend=showlegend,
            marker=dict(color=CALLTYPE_COLORS[ct], size=9,
                        line=dict(width=0.5, color="#666")),
            hovertext=_hover_texts(sub), hoverinfo="text",
        ), row=row, col=col)


def framing_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    _zone_frame(fig)
    if not df.empty:
        d = C.add_framing_cols(df) if "CallType" not in df.columns else df
        d = d[d["plate_loc_side"].notna() & d["plate_loc_height"].notna()]
        _scatter_traces(fig, d)
    _base_axes(fig)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_layout(
        title="Zone Location — Catcher View", showlegend=False,
        margin=dict(l=20, r=20, t=40, b=20), height=460,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def framing_facets(df: pd.DataFrame, by: str, title: str) -> go.Figure:
    import math
    d = C.add_framing_cols(df) if not df.empty and "CallType" not in df.columns else df
    vals = sorted(d[by].dropna().unique()) if not d.empty and by in d.columns else []
    n = max(1, len(vals))
    ncols = min(2, n)
    nrows = math.ceil(n / ncols)
    fig = make_subplots(rows=nrows, cols=ncols,
                        subplot_titles=[str(v) for v in vals] or [title],
                        vertical_spacing=0.12, horizontal_spacing=0.06)
    shown = set()
    for i, v in enumerate(vals):
        r, c = i // ncols + 1, i % ncols + 1
        _zone_frame(fig, row=r, col=c)
        _scatter_traces(fig, d[d[by] == v], row=r, col=c, shown=shown)
        _base_axes(fig, row=r, col=c)
        idx = (r - 1) * ncols + c  # make_subplots axis numbering (row-major)
        fig.update_yaxes(scaleanchor=("x" if idx == 1 else f"x{idx}"),
                         scaleratio=1, row=r, col=c)
    # Hide any unused trailing cells when len(vals) is odd and n < nrows*ncols
    if vals:
        for j in range(len(vals), nrows * ncols):
            r, c = j // ncols + 1, j % ncols + 1
            fig.update_xaxes(visible=False, row=r, col=c)
            fig.update_yaxes(visible=False, row=r, col=c)
    if not vals:
        _zone_frame(fig, row=1, col=1); _base_axes(fig, row=1, col=1)
        fig.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=1)
    fig.update_layout(
        title=title, showlegend=False, height=360 * nrows, margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


# Display grid: 5x5 over the nominal zone plus a one-cell shadow ring (7x7).
# Deliberately coarser than called_strike's 0.15 ft model bins -- one catcher
# cannot fill 952 cells, so rendering them would be noise, not information.
ZONE_SIDE_HALF = 0.83
ZONE_H_LO, ZONE_H_HI = 1.5, 3.5
_CELL_W = (2 * ZONE_SIDE_HALF) / 5.0     # 0.332 ft
_CELL_H = (ZONE_H_HI - ZONE_H_LO) / 5.0  # 0.4 ft
_N = 7                                   # 5 zone cells + 1 ring each side

# Real-feet bin centers for the 7 display columns/rows, so the heatmap plots
# in physical space instead of abstract cell indices -- this is what lets
# scaleanchor="x", scaleratio=1 below render the zone's TRUE (non-square)
# aspect ratio instead of an artificial square.
_COL_CENTERS_FT = [(-ZONE_SIDE_HALF - _CELL_W) + (c + 0.5) * _CELL_W for c in range(_N)]
_ROW_CENTERS_FT = [(ZONE_H_LO - _CELL_H) + (r + 0.5) * _CELL_H for r in range(_N)]


def _display_cell(side, height) -> tuple:
    """(col, row) in the 7x7 display grid. Out-of-grid pitches clamp into the
    outer ring so every taken pitch is counted exactly once and the grid
    reconciles with SLAA.

    `side` is NEGATED before binning to match this codebase's catcher-view
    convention, established by the framing scatter directly above this heat
    map on the same tab (`catching.add_framing_cols`'s
    `_x = plate_loc_side * -12`): a positive `plate_loc_side` must draw on
    the LEFT (negative x), not the right. Binning the raw, unnegated side
    here previously left the heat map mirrored relative to the scatter even
    though both are titled "Catcher's View" / "Catcher View".
    """
    s = -float(side)
    col = int(math.floor((s - (-ZONE_SIDE_HALF - _CELL_W)) / _CELL_W))
    row = int(math.floor((float(height) - (ZONE_H_LO - _CELL_H)) / _CELL_H))
    return (min(_N - 1, max(0, col)), min(_N - 1, max(0, row)))


def slaa_location_figure(df: pd.DataFrame, *, lookup=None) -> go.Figure:
    """Heat map of (actual - expected) called strikes by zone region.

    Diverging around zero: positive = strikes gained, negative = lost. Every
    taken pitch (with a placeable location) clamps into one of the 7x7
    display cells (see `_display_cell`), so the grid total reconciles
    exactly with a LOCAL `catching_caps.slaa_summary` computed on this same
    `df` -- surfaced as the figure's subtitle. `df` is scoped by whatever the
    caller passed (e.g. the Framing tab's own Game dropdown), which is not
    necessarily the same scope as the sidebar's season-wide SLAA tile, so the
    subtitle deliberately labels its number "this selection" rather than
    implying it always matches the sidebar.
    """
    z = np.zeros((_N, _N), dtype=float)
    if df is None:
        taken = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    else:
        taken = df[cs.is_taken(df)]
        taken = taken[taken["plate_loc_side"].notna()
                      & taken["plate_loc_height"].notna()]
    if not taken.empty:
        exp = cs.expected_called_strikes(taken, lookup=lookup)
        act = cs.is_called_strike(taken).astype(float)
        diff = act - exp
        for s, h, d in zip(taken["plate_loc_side"],
                           taken["plate_loc_height"], diff):
            c, r = _display_cell(s, h)
            z[r][c] += float(d)

    # LOCAL summary on the same (already taken+location-filtered) population
    # feeding the grid above -- not the sidebar's season-wide tile, which can
    # be scoped differently (see docstring).
    summary = catching_caps.slaa_summary(taken, lookup=lookup)
    caption = (f"SLAA {summary['slaa']:+.1f} over {summary['taken']} "
               f"taken pitches, this selection")

    lim = float(max(1.0, np.abs(z).max()))
    fig = go.Figure(go.Heatmap(
        x=_COL_CENTERS_FT, y=_ROW_CENTERS_FT,
        z=z, zmid=0, zmin=-lim, zmax=lim,
        colorscale="RdBu", reversescale=True,
        hovertemplate="strikes gained: %{z:.1f}<extra></extra>",
        colorbar=dict(title="+/- strikes"),
    ))
    # Outline the nominal strike zone at its real bounds (matches pitching.py's
    # _SZ / bullpen/charts.py's _ZONE) -- now that the heatmap plots in real
    # feet, this box's aspect ratio is finally the TRUE, non-square shape.
    fig.add_shape(type="rect", x0=-ZONE_SIDE_HALF, x1=ZONE_SIDE_HALF,
                  y0=ZONE_H_LO, y1=ZONE_H_HI, line=dict(color="#1a1a1a", width=2))
    fig.update_layout(
        title=dict(text="Strikes Gained vs Expected, by Location (Catcher's View)",
                   subtitle=dict(text=caption)),
        showlegend=False,
        xaxis=dict(showticklabels=False, title=None),
        yaxis=dict(showticklabels=False, title=None, scaleanchor="x", scaleratio=1),
        height=420, margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def caught_stealing_trend_fig(trend_df: pd.DataFrame) -> go.Figure:
    """Dual-axis trend: CS% (crimson, left) + Avg Pop time (blue, right) by game date."""
    fig = go.Figure()
    if trend_df is not None and not trend_df.empty:
        x = trend_df["game_date"].astype(str)
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["cs_pct"], name="CS%", yaxis="y",
            mode="markers+lines", marker=dict(color=CRIMSON, size=10),
            line=dict(color=CRIMSON, width=2),
            hovertext=[f"{a} att · {c} caught" for a, c in
                       zip(trend_df["attempts"], trend_df["caught"])],
            hoverinfo="text+y",
        ))
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["avg_pop"], name="Avg Pop (s)", yaxis="y2",
            mode="markers+lines", marker=dict(color="#0076A5", size=9),
            line=dict(color="#0076A5", width=2, dash="dot"),
        ))
    fig.update_layout(
        title="Caught Stealing Trend",
        xaxis=dict(title="Game"),
        yaxis=dict(title="CS%", range=[0, 100], side="left"),
        yaxis2=dict(title="Avg Pop (s)", overlaying="y", side="right",
                    showgrid=False),
        height=340, margin=dict(l=40, r=40, t=40, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=1.12),
    )
    return fig
