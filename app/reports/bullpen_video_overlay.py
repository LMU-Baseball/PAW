"""LMU-branded pitch-data overlay for a downloadable Edgertronic clip
(2026-09-23, Brad: players want to download their best pitches to share
with recruiters, reference video from the Red Sox showing pitch type/velo/
break up top, a strike-zone box and movement chart on the side).

Two steps, kept separate:
  1. `build_overlay_png` -- a transparent PNG, matplotlib (Agg, headless,
     same idiom as app.reports.plots/bullpen_plots' static report charts),
     sized to exactly match the clip's own resolution so it composites
     pixel-for-pixel with no scaling.
  2. `composite_overlay` -- burns that PNG onto the clip with ffmpeg
     (imageio-ffmpeg's portable binary, same as app.ingest.bullpen_video.
     remux_to_mp4 -- no system ffmpeg install required).
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile

import matplotlib
matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.pyplot as plt
import pandas as pd

from app.data.bullpen import _EDGE, _SZ
from app.reports.plots import _add_ellipse, _color_for, _draw_zone

_CRIMSON = "#9A0021"


class OverlayError(RuntimeError):
    """ffmpeg failed, or isn't installed, while compositing an overlay."""


def _ffmpeg_path() -> str:
    """Portable ffmpeg binary bundled with imageio-ffmpeg -- no system
    install required. Mirrors app.ingest.bullpen_video._ffmpeg_path and
    scripts/pitch_video_clips.py's own copy (same idiom, kept separate --
    three independent entry points)."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def build_overlay_png(pitch: dict, session_df: pd.DataFrame, *, player_name: str,
                      date: str, pitch_index: int, pitch_count: int,
                      width: int, height: int) -> bytes:
    """A transparent `width`x`height` PNG: pitch type + velo/break top,
    strike-zone box (this pitch's location) and a movement scatter (this
    pitch highlighted among `session_df`'s other same-session pitches) on
    the right, player/date/pitch-count on the bottom. `pitch` is one row of
    `app.data.bullpen_video.session_pitch_video_df` (pitch_type, velo,
    horz_break, vert_break, plate_loc_side, plate_loc_height); `session_df`
    is that same DataFrame (every pitch in the session, for the movement
    chart's other dots)."""
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="none")

    pitch_type = pitch.get("pitch_type") or "—"
    velo = pitch.get("velo")
    vb, hb = pitch.get("vert_break"), pitch.get("horz_break")
    color = _color_for(pitch_type)

    # -- Top bar: pitch type (left) + velo/break (right) ------------------
    fig.text(0.03, 0.94, pitch_type, fontsize=34, fontweight="bold", color=color,
             ha="left", va="top")
    metrics = []
    if velo is not None and pd.notna(velo):
        metrics.append(f"{velo:.1f} mph")
    if vb is not None and pd.notna(vb):
        metrics.append(f"VB: {vb:.1f}")
    if hb is not None and pd.notna(hb):
        metrics.append(f"HB: {hb:.1f}")
    fig.text(0.97, 0.94, "   ".join(metrics), fontsize=20, fontweight="bold",
             color=color, ha="right", va="top")

    # -- Right side, upper: strike zone + this pitch's location -----------
    zone_ax = fig.add_axes((0.72, 0.46, 0.25, 0.32))
    zone_ax.set_facecolor("none")
    _draw_zone(zone_ax)
    loc_x, loc_y = pitch.get("plate_loc_side"), pitch.get("plate_loc_height")
    if loc_x is not None and loc_y is not None and pd.notna(loc_x) and pd.notna(loc_y):
        zone_ax.scatter([loc_x], [loc_y], s=90, color=color, edgecolor="white",
                        linewidth=1.2, zorder=3)
    zone_ax.set_xlim(_SZ["x0"] - _EDGE * 2, _SZ["x1"] + _EDGE * 2)
    zone_ax.set_ylim(_SZ["y0"] - _EDGE * 3, _SZ["y1"] + _EDGE * 3)
    zone_ax.set_aspect("equal")
    zone_ax.set_xticks([])
    zone_ax.set_yticks([])
    for spine in zone_ax.spines.values():
        spine.set_visible(False)

    # -- Right side, lower: movement chart, this pitch highlighted --------
    move_ax = fig.add_axes((0.70, 0.08, 0.28, 0.32))
    move_ax.set_facecolor("none")
    move_ax.axhline(0, color="#ccc", lw=0.8)
    move_ax.axvline(0, color="#ccc", lw=0.8)
    others = session_df[session_df["play_id"] != pitch.get("play_id")]
    for pt, sub in others.groupby("pitch_type"):
        xs, ys = sub["horz_break"].to_numpy(), sub["vert_break"].to_numpy()
        _add_ellipse(move_ax, xs, ys, _color_for(pt))
        move_ax.scatter(xs, ys, s=26, color=_color_for(pt), alpha=0.45,
                        edgecolor="none", zorder=2)
    if hb is not None and vb is not None and pd.notna(hb) and pd.notna(vb):
        move_ax.scatter([hb], [vb], s=90, color=color, edgecolor="white",
                        linewidth=1.2, zorder=3)
    move_ax.set_title("Movement", fontsize=11, color="white", fontweight="bold", pad=4)
    move_ax.tick_params(colors="white", labelsize=7)
    for spine in move_ax.spines.values():
        spine.set_color("white")
        spine.set_alpha(0.4)

    # -- Bottom bar: player / date / pitch count ---------------------------
    fig.text(0.03, 0.03, player_name, fontsize=16, color="white", alpha=0.85, ha="left")
    fig.text(0.5, 0.03, date, fontsize=16, color="white", alpha=0.85, ha="center")
    fig.text(0.97, 0.03, f"Pitch {pitch_index}/{pitch_count}", fontsize=16,
             color="white", alpha=0.85, ha="right")

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, transparent=True)
    finally:
        plt.close(fig)
    return buf.getvalue()


def composite_overlay(video_bytes: bytes, overlay_png: bytes) -> bytes:
    """Burns `overlay_png` onto `video_bytes` (both already the same
    resolution -- `build_overlay_png` is always called with the clip's own
    width/height). A real re-encode, not a remux (`app.ingest.bullpen_
    video.remux_to_mp4`'s `-c copy` doesn't apply here -- overlaying
    changes every frame's pixels), so this takes noticeably longer than
    streaming the raw clip; acceptable for an occasional manual download,
    not something run in bulk."""
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "in.mp4")
        overlay_path = os.path.join(tmp, "overlay.png")
        out_path = os.path.join(tmp, "out.mp4")
        with open(video_path, "wb") as f:
            f.write(video_bytes)
        with open(overlay_path, "wb") as f:
            f.write(overlay_png)
        try:
            subprocess.run(
                [_ffmpeg_path(), "-y", "-i", video_path, "-i", overlay_path,
                 "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264",
                 "-crf", "20", "-movflags", "+faststart", "-an", out_path],
                check=True, capture_output=True,
            )
        except FileNotFoundError as e:
            raise OverlayError(
                "ffmpeg not found -- required to burn the pitch-data overlay "
                "onto a downloaded clip") from e
        except subprocess.CalledProcessError as e:
            raise OverlayError(
                f"ffmpeg overlay compositing failed (exit {e.returncode}): "
                f"{e.stderr.decode(errors='replace')[-500:]}") from e
        with open(out_path, "rb") as f:
            return f.read()
