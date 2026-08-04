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
from matplotlib.patches import Ellipse, Wedge
from matplotlib.lines import Line2D

from app.data.pitching import pitch_type

# Strike zone (approx, feet)
_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)
_PALETTE = ["#9A0021", "#2864a8", "#2e8b57", "#e08a1e", "#6a4c93",
            "#00897b", "#c2185b", "#555555"]

# Stable color per pitch-type NAME so the same pitch renders identically across
# all three charts on a report, regardless of which types appear in each subset.
# Colors chosen for maximum separation among the common set (the charts have no
# legend now, so color is the only key). Fastball stays brand crimson; ChangeUp
# is a warm orange (was too close to crimson before); Sinker moved to brown so it
# doesn't collide with ChangeUp.
_PITCH_COLOR = {
    "Fastball": "#9A0021", "Four-Seam": "#9A0021", "FourSeamFastBall": "#9A0021",
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


# Contact-result shape key (color still encodes pitch type):
#   Whiff = circle, Barrel (InPlay & 95+ EV) = X, In Play = square.
_CONTACT_MARKERS = [("Whiff", "o"), ("Barrel", "X"), ("In Play", "s")]


def _contact_classes(df):
    """Per-pitch contact class Series: Whiff / Barrel / In Play / NaN (take)."""
    import pandas as pd
    call = df["pitch_call"]
    ev = (df["exit_speed"] if "exit_speed" in df.columns
          else pd.Series(index=df.index, dtype=float))
    cc = pd.Series(index=df.index, dtype=object)
    cc[call == "StrikeSwinging"] = "Whiff"
    inplay = call == "InPlay"
    cc[inplay & (ev >= 95)] = "Barrel"
    cc[inplay & ~(ev >= 95)] = "In Play"
    return cc


def zone_chart_uri(df, batter_side: str, title: str) -> str:
    d = df[df["batter_side"] == batter_side].dropna(
        subset=["plate_loc_side", "plate_loc_height"]).copy()
    fig, ax = plt.subplots(figsize=(3.1, 3.5))
    _draw_zone(ax)
    if not d.empty:
        d["_pt"] = pitch_type(d)
        d["_cc"] = _contact_classes(d)
        # plain small dots for non-contact pitches (takes/balls/called/foul)
        base = d[d["_cc"].isna()]
        for pt, sub in base.groupby("_pt"):
            ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"], s=20,
                       color=_color_for(pt), edgecolor="white", linewidth=0.3,
                       alpha=0.5, zorder=2, marker=".")
        # shaped markers for contact events (color = pitch type)
        for cc, marker in _CONTACT_MARKERS:
            ev_sub = d[d["_cc"] == cc]
            for pt, sub in ev_sub.groupby("_pt"):
                ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"], s=52,
                           color=_color_for(pt), edgecolor="white", linewidth=0.5,
                           alpha=0.95, zorder=3, marker=marker)
    # shape-only key below the plot (color = pitch type; shape = contact result)
    handles = [Line2D([0], [0], marker=m, color="none", markerfacecolor="#444",
                      markeredgecolor="#444", markersize=6, label=lbl)
               for lbl, m in _CONTACT_MARKERS]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02),
              ncol=3, frameon=False, fontsize=6, handletextpad=0.2,
              columnspacing=0.8)
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
                facecolor=color, alpha=0.18, edgecolor=color, lw=1.4, zorder=2)
    ax.add_patch(e)


def movement_map_uri(df, title: str = "Movement Map") -> str:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    ax.set_axisbelow(True)
    ax.grid(True, color="#eee", lw=0.6)
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
    ax.set_title(title, fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def _donut(ax, values, colors, center_label) -> None:
    pairs = [(v, c) for v, c in zip(values, colors) if v and v > 0]
    ax.set_aspect("equal")
    if pairs:
        vals, cols = [p[0] for p in pairs], [p[1] for p in pairs]
        ax.pie(vals, colors=cols, startangle=90, counterclock=False,
               wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1),
               autopct=lambda p: f"{p:.0f}%" if p >= 6 else "",
               pctdistance=0.78, textprops=dict(fontsize=7, color="#222"))
    else:
        ax.text(0.5, 0.5, "—", ha="center", va="center", transform=ax.transAxes)
    ax.text(0, 0, center_label, ha="center", va="center",
            fontsize=10, fontweight="bold", color="#0076A5")


def _split_donut(ax, vlhh, vrhh, colors) -> None:
    ax.set_xlim(-1.25, 1.25)
    ax.set_ylim(-1.25, 1.25)
    ax.set_aspect("equal")
    ax.axis("off")
    r_out, r_in = 1.0, 0.58

    def _half(vals, start, end):
        tot = sum(v for v in vals if v) or 1
        a = start
        for v, c in zip(vals, colors):
            if not v:
                continue
            sweep = (end - start) * v / tot
            ax.add_patch(Wedge((0, 0), r_out, a, a + sweep, width=r_out - r_in,
                               facecolor=c, edgecolor="white", linewidth=1))
            a += sweep
    _half(vlhh, 90, 270)    # left half = vLHH
    _half(vrhh, -90, 90)    # right half = vRHH
    ax.text(0, 0.05, "Splits", ha="center", va="center",
            fontsize=10, fontweight="bold", color="#0076A5")
    ax.text(0, -0.16, "vLHH | vRHH", ha="center", va="center",
            fontsize=6, color="#555")


def pitch_freq_bar_uri(counts) -> str:
    """Horizontal stacked bar of pitch-type mix (width proportional to count), labeled."""
    fig, ax = plt.subplots(figsize=(6.4, 0.7))
    total = sum(n for _, n in counts) or 1
    left = 0
    for pt, n in counts:
        w = n / total
        ax.barh(0, w, left=left, color=_color_for(pt), edgecolor="white")
        if w > 0.06:
            ax.text(left + w / 2, 0, str(n), ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")
        left += w
    ax.set_xlim(0, 1); ax.set_ylim(-0.5, 0.5); ax.axis("off")
    ax.set_title(f"Pitch Frequency (Total {total if counts else 0})",
                 fontsize=9, color="#9A0021", fontweight="bold", loc="left")
    return _fig_to_uri(fig)


def pitch_usage_donuts_uri(df) -> str:
    """Overall / 2K / Splits(vLHH|vRHH) usage donuts as one PNG data URI."""
    from app.data.pitching import pitch_usage_table
    rows = pitch_usage_table(df)
    fig, axes = plt.subplots(1, 3, figsize=(9.2, 3.2))
    if not rows:
        for ax, lbl in zip(axes, ("Overall", "2K", "Splits")):
            ax.axis("off")
            ax.text(0.5, 0.5, "—", ha="center", va="center", transform=ax.transAxes)
        return _fig_to_uri(fig)
    colors = [_color_for(r["pitch"]) for r in rows]
    _donut(axes[0], [r["usage_pct"] for r in rows], colors, "Overall")
    _donut(axes[1], [r["twok_usage_pct"] for r in rows], colors, "2K")
    _split_donut(axes[2], [r["vlhh"] for r in rows], [r["vrhh"] for r in rows], colors)
    return _fig_to_uri(fig)
