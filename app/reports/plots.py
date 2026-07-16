"""matplotlib plot builders for the pitcher one-pager (static PNG data URIs).

In-process rendering (Agg) — no headless browser, unlike the Plotly/kaleido
path. Each builder returns a self-contained base64 PNG data: URI.
"""
from __future__ import annotations

import base64
import io
import zlib

import matplotlib
matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse

from app.data.pitching import pitch_type

# Strike zone (approx, feet)
_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)
_PALETTE = ["#9A0021", "#2864a8", "#2e8b57", "#e08a1e", "#6a4c93",
            "#00897b", "#c2185b", "#555555"]

# Stable color per pitch-type NAME so the same pitch renders identically across
# all three charts on a report, regardless of which types appear in each subset.
_PITCH_COLOR = {
    "Fastball": "#9A0021", "Four-Seam": "#9A0021", "FourSeamFastBall": "#9A0021",
    "Sinker": "#e08a1e", "TwoSeamFastBall": "#e08a1e",
    "Cutter": "#6a4c93",
    "Slider": "#2864a8", "Sweeper": "#00897b",
    "Curveball": "#2e8b57", "ChangeUp": "#c2185b", "Changeup": "#c2185b",
    "Splitter": "#555555",
}


def _color_for(pt: str) -> str:
    if pt in _PITCH_COLOR:
        return _PITCH_COLOR[pt]
    # deterministic (crc32 is stable across runs, unlike hash()) fallback
    return _PALETTE[zlib.crc32(str(pt).encode()) % len(_PALETTE)]


def _fig_to_uri(fig) -> str:
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    finally:
        plt.close(fig)


def _draw_zone(ax) -> None:
    x0, x1, y0, y1 = _SZ["x0"], _SZ["x1"], _SZ["y0"], _SZ["y1"]
    ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                               edgecolor="black", lw=1.5))
    for i in (1, 2):  # 3x3 grid
        ax.plot([x0 + (x1 - x0) * i / 3] * 2, [y0, y1], color="#bbb", lw=0.8)
        ax.plot([x0, x1], [y0 + (y1 - y0) * i / 3] * 2, color="#bbb", lw=0.8)
    # home plate outline below the zone
    ax.plot([-0.7, 0.7, 0.7, 0, -0.7, -0.7],
            [0.2, 0.2, 0.5, 0.75, 0.5, 0.2], color="#888", lw=1)


def zone_chart_uri(df, batter_side: str, title: str) -> str:
    d = df[df["batter_side"] == batter_side].dropna(
        subset=["plate_loc_side", "plate_loc_height"]).copy()
    fig, ax = plt.subplots(figsize=(3.1, 3.5))
    _draw_zone(ax)
    if not d.empty:
        d["_pt"] = pitch_type(d)
        for pt, sub in d.groupby("_pt"):
            ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"],
                       s=28, color=_color_for(pt), edgecolor="white", linewidth=0.4,
                       label=pt, zorder=3)
        ax.legend(fontsize=6, loc="upper right", framealpha=0.7)
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def _add_ellipse(ax, xs, ys, color) -> None:
    if len(xs) < 3:
        return
    cov = np.cov(xs, ys)
    if not np.all(np.isfinite(cov)):
        return
    vals, vecs = np.linalg.eigh(cov)
    order = vals.argsort()[::-1]
    vals, vecs = vals[order], vecs[:, order]
    angle = np.degrees(np.arctan2(*vecs[:, 0][::-1]))
    w, h = 2 * np.sqrt(np.maximum(vals, 0))  # 1 sigma
    e = Ellipse((np.mean(xs), np.mean(ys)), width=w, height=h, angle=angle,
                facecolor=color, alpha=0.15, edgecolor=color, lw=1)
    ax.add_patch(e)


def movement_map_uri(df, title: str = "Movement Map") -> str:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    ax.axhline(0, color="#ccc", lw=0.8)
    ax.axvline(0, color="#ccc", lw=0.8)
    if not d.empty:
        d["_pt"] = pitch_type(d)
        for pt, sub in d.groupby("_pt"):
            color = _color_for(pt)
            ax.scatter(sub["horz_break"], sub["induced_vert_break"],
                       s=24, color=color, edgecolor="white", linewidth=0.3,
                       label=pt, zorder=3)
            _add_ellipse(ax, sub["horz_break"].to_numpy(),
                         sub["induced_vert_break"].to_numpy(), color)
        ax.legend(fontsize=6, loc="upper right", framealpha=0.7)
    ax.set_xlim(-25, 25)
    ax.set_ylim(-25, 25)
    ax.set_aspect("equal")
    ax.set_xlabel("HB (in)", fontsize=8)
    ax.set_ylabel("IVB (in)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)
