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
_PALETTE = ["#AB0C2F", "#2864a8", "#2e8b57", "#e08a1e", "#6a4c93",
            "#00897b", "#c2185b", "#555555"]

# Stable color per pitch-type NAME so the same pitch renders identically across
# all three charts on a report, regardless of which types appear in each subset.
# Colors chosen for maximum separation among the common set (the charts have no
# legend now, so color is the only key). Fastball stays brand crimson; ChangeUp
# is a warm orange (was too close to crimson before); Sinker moved to brown so it
# doesn't collide with ChangeUp.
_PITCH_COLOR = {
    "Fastball": "#AB0C2F", "Four-Seam": "#AB0C2F", "FourSeamFastBall": "#AB0C2F",
    "Sinker": "#7a5230", "TwoSeamFastBall": "#7a5230",
    "Cutter": "#6a4c93",
    "Slider": "#2864a8", "Sweeper": "#00897b",
    "Curveball": "#2e8b57", "ChangeUp": "#e08a1e", "Changeup": "#e08a1e",
    "Splitter": "#555555",
}


def _color_for(pt: str) -> str:
    if pt in _PITCH_COLOR:
        return _PITCH_COLOR[pt]
    # deterministic (crc32 is stable across runs, unlike hash()) fallback
    return _PALETTE[zlib.crc32(str(pt).encode()) % len(_PALETTE)]


def color_for(pt: str) -> str:
    """Public accessor for a pitch type's stable chart color.

    The report table (Pitch Usage / Movement Summary) colors each pitch-type
    name with this so the tables double as the charts' legend — the charts
    themselves no longer draw legends (they hid data points).
    """
    return _color_for(pt)


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
                       s=46, color=_color_for(pt), edgecolor="white", linewidth=0.5,
                       alpha=0.9, zorder=3)
        # No legend — the colored pitch names in the Pitch Usage table are the key
        # (a legend here overlapped and hid data points).
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=11, color="#AB0C2F", fontweight="bold")
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
                facecolor=color, alpha=0.18, edgecolor=color, lw=1.4, zorder=2)
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
            xs = sub["horz_break"].to_numpy()
            ys = sub["induced_vert_break"].to_numpy()
            # Larger, semi-transparent circles so the movement clusters are the
            # focal point (and dense overlaps stay legible).
            ax.scatter(xs, ys, s=70, color=color, edgecolor="white",
                       linewidth=0.6, alpha=0.8, zorder=3)
            _add_ellipse(ax, xs, ys, color)
            # Hollow cluster-mean marker (mirrors the original report).
            ax.scatter(xs.mean(), ys.mean(), s=90, facecolor="white",
                       edgecolor=color, linewidth=1.6, zorder=4)
        # No legend — the colored pitch names in the tables are the key.
        # Frame the data (with padding) instead of a fixed +/-25 box, so the
        # circles fill the panel; always keep the 0,0 axes in view.
        pad = 5.0
        xlo = min(d["horz_break"].min(), 0) - pad
        xhi = max(d["horz_break"].max(), 0) + pad
        ylo = min(d["induced_vert_break"].min(), 0) - pad
        yhi = max(d["induced_vert_break"].max(), 0) + pad
        ax.set_xlim(xlo, xhi)
        ax.set_ylim(ylo, yhi)
    else:
        ax.set_xlim(-25, 25)
        ax.set_ylim(-25, 25)
    ax.set_aspect("equal")
    ax.set_xlabel("HB (in)", fontsize=8)
    ax.set_ylabel("IVB (in)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=11, color="#AB0C2F", fontweight="bold")
    return _fig_to_uri(fig)
