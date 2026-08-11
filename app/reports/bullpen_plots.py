"""matplotlib chart builders for the bullpen report (snake_case bullpen cols)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.pyplot as plt

from app.reports.plots import _fig_to_uri, _color_for, _draw_zone, _add_ellipse


def _by_type(df):
    return [(pt, sub) for pt, sub in df.groupby("tagged_pitch_type")]


def velo_strip_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    types = list(df.groupby("tagged_pitch_type").groups)
    for i, (pt, sub) in enumerate(_by_type(df)):
        y = len(types) - i
        ax.scatter(sub["rel_speed"], [y] * len(sub), s=40,
                   color=_color_for(pt), alpha=0.8, edgecolor="white", linewidth=0.4)
        m = sub["rel_speed"].mean()
        if m == m:  # not NaN
            ax.annotate(f"{m:.0f}", (m, y + 0.18), ha="center", fontsize=8, color="#222")
    ax.set_yticks(range(1, len(types) + 1))
    ax.set_yticklabels(list(reversed(types)), fontsize=8)
    ax.set_xlabel("mph", fontsize=8)
    ax.set_title("Avg. velocity by pitch type", fontsize=11, color="#9A0021",
                 fontweight="bold")
    ax.grid(axis="x", color="#eee")
    return _fig_to_uri(fig)


def movement_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    ax.set_axisbelow(True)
    ax.grid(True, color="#eee", lw=0.6)
    ax.axhline(0, color="#ccc", lw=0.8)
    ax.axvline(0, color="#ccc", lw=0.8)
    for pt, sub in _by_type(df):
        color = _color_for(pt)
        xs = sub["horz_break"].to_numpy()
        ys = sub["ind_vert_break"].to_numpy()
        # Faint per-pitch-type 1-sigma reference circle (movement trend/consistency),
        # drawn under the scatter — same pattern as the interactive dashboard's
        # movement_fig / _ellipse_xy (app/dashboards/bullpen/charts.py).
        _add_ellipse(ax, xs, ys, color)
        ax.scatter(xs, ys, s=55, color=color, alpha=0.8, edgecolor="white",
                   linewidth=0.5, zorder=3)
    # Equal data aspect (a circle of movement reads the same in both axes)
    # inside a square box that fills the panel. Plain set_aspect("equal")
    # (adjustable="box", the default) shrinks the axes box to fit the data,
    # letterboxing the panel with whitespace next to Release in the report's
    # bottom row; adjustable="datalim" + set_box_aspect(1) instead expands the
    # data limits to fill the fixed square box.
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_box_aspect(1)
    ax.set_xlabel("HB (in)", fontsize=8)
    ax.set_ylabel("IVB (in)", fontsize=8)
    ax.set_title("Movement", fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def release_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    ax.set_axisbelow(True)
    ax.grid(True, color="#eee", lw=0.6)
    for pt, sub in _by_type(df):
        ax.scatter(sub["rel_side"], sub["rel_height"], s=55,
                   color=_color_for(pt), alpha=0.8, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Rel side (ft)", fontsize=8)
    ax.set_ylabel("Rel height (ft)", fontsize=8)
    ax.set_title("Release", fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def location_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.6, 2.6))
    _draw_zone(ax)
    for pt, sub in _by_type(df):
        ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"], s=46,
                   color=_color_for(pt), alpha=0.9, edgecolor="white",
                   linewidth=0.5, zorder=3)
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Location", fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)
