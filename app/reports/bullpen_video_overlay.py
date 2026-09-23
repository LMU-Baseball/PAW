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
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from app.data.bullpen import _EDGE, _SZ
from app.reports.plots import _add_ellipse, _color_for

_LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "static", "reports", "lion.png")
_TEXT_OUTLINE = [pe.withStroke(linewidth=3, foreground="white")]


def _outlined_text(fig, x, y, s, *, fontsize, ha, color, va="center", fontweight="bold"):
    """`color` text with a white outline (2026-09-23, Brad: "make the text
    red and outline white... hard to see" against a busy video background,
    then a follow-up: "keep the text the color of the pitch so it is all
    consistent" -- every text element uses THIS pitch's own color, not a
    fixed red, so the whole overlay reads as one pitch's data). Matplotlib's
    path_effects.withStroke draws the outline as part of the text's own
    rendering, so it stays crisp at any size, not a cheap drop-shadow hack."""
    fig.text(x, y, s, fontsize=fontsize, fontweight=fontweight, color=color,
             ha=ha, va=va, path_effects=_TEXT_OUTLINE)


def _load_logo_rgba(target_px: int) -> np.ndarray:
    """The LMU sun-lion mark (app/static/reports/lion.png, used elsewhere
    as the default player photo) has an OPAQUE WHITE background -- pasted
    as-is it would show as a white square. Thresholds near-white pixels to
    fully transparent, keeping just the crimson lion-sun shape, so it
    composites as a clean watermark. Resized to `target_px` square before
    returning -- `Figure.figimage` (unlike `OffsetImage`) has no `zoom`
    kwarg, so scaling has to happen here, not at placement time."""
    img = Image.open(_LOGO_PATH).convert("RGBA").resize((target_px, target_px),
                                                        Image.LANCZOS)
    arr = np.array(img)
    near_white = (arr[..., 0] > 240) & (arr[..., 1] > 240) & (arr[..., 2] > 240)
    arr[..., 3] = np.where(near_white, 0, arr[..., 3])
    return arr


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
    full_ax = fig.add_axes((0, 0, 1, 1))
    full_ax.set_xlim(0, 1)
    full_ax.set_ylim(0, 1)
    full_ax.axis("off")
    full_ax.set_zorder(0)

    pitch_type = pitch.get("pitch_type") or "—"
    velo = pitch.get("velo")
    vb, hb = pitch.get("vert_break"), pitch.get("horz_break")
    color = _color_for(pitch_type)

    # -- Solid bands top/bottom (2026-09-23, Brad: text was hard to read
    # over the raw video -- "it is okay if the video has some borders with
    # the text") -- a semi-opaque black band behind the text so it's
    # legible regardless of what's in the footage behind it, not just a
    # thin outline floating over a busy frame.
    full_ax.add_patch(plt.Rectangle((0, 0.90), 1, 0.10, facecolor="black",
                                    alpha=0.55, zorder=1, transform=full_ax.transAxes))
    full_ax.add_patch(plt.Rectangle((0, 0), 1, 0.075, facecolor="black",
                                    alpha=0.55, zorder=1, transform=full_ax.transAxes))
    # Panel behind the zone box + movement chart, same reason -- the raw
    # video behind them varies too much for thin white lines alone to read.
    full_ax.add_patch(plt.Rectangle((0.68, 0.06), 0.30, 0.76, facecolor="black",
                                    alpha=0.45, zorder=1, transform=full_ax.transAxes,
                                    edgecolor="white", linewidth=1, joinstyle="round"))

    # -- LMU sun-lion mark, top-left of the top band -----------------------
    logo_px = int(height * 0.075)  # sized to the top band's own height
    logo = _load_logo_rgba(logo_px)
    fig.figimage(logo, xo=int(width * 0.015), yo=height - logo_px - int(height * 0.012),
                alpha=0.95, zorder=2)

    # -- Top band text: pitch type (after the logo) + velo/break (right) --
    logo_frac = (logo_px + width * 0.03) / width
    _outlined_text(fig, 0.015 + logo_frac, 0.945, pitch_type, fontsize=32, ha="left", color=color)
    metrics = []
    if velo is not None and pd.notna(velo):
        metrics.append(f"{velo:.1f} mph")
    if vb is not None and pd.notna(vb):
        metrics.append(f"VB: {vb:.1f}")
    if hb is not None and pd.notna(hb):
        metrics.append(f"HB: {hb:.1f}")
    _outlined_text(fig, 0.97, 0.945, "   ".join(metrics), fontsize=18, ha="right", color=color)

    # -- Right side, upper: strike zone + this pitch's location -----------
    # White lines (not app.reports.plots._draw_zone's black/gray -- that's
    # tuned for a white-paper PDF report, invisible against dark video).
    zone_ax = fig.add_axes((0.715, 0.46, 0.235, 0.32))
    zone_ax.set_facecolor("none")
    x0, x1, y0, y1 = _SZ["x0"], _SZ["x1"], _SZ["y0"], _SZ["y1"]
    zone_ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                                    edgecolor="white", lw=1.8))
    for i in (1, 2):
        zone_ax.plot([x0 + (x1 - x0) * i / 3] * 2, [y0, y1], color="white", lw=0.8, alpha=0.6)
        zone_ax.plot([x0, x1], [y0 + (y1 - y0) * i / 3] * 2, color="white", lw=0.8, alpha=0.6)
    loc_x, loc_y = pitch.get("plate_loc_side"), pitch.get("plate_loc_height")
    if loc_x is not None and loc_y is not None and pd.notna(loc_x) and pd.notna(loc_y):
        zone_ax.scatter([loc_x], [loc_y], s=100, color=color, edgecolor="white",
                        linewidth=1.5, zorder=3)
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
    move_ax.axhline(0, color="white", lw=0.8, alpha=0.5)
    move_ax.axvline(0, color="white", lw=0.8, alpha=0.5)
    others = session_df[session_df["play_id"] != pitch.get("play_id")]
    for pt, sub in others.groupby("pitch_type"):
        xs, ys = sub["horz_break"].to_numpy(), sub["vert_break"].to_numpy()
        _add_ellipse(move_ax, xs, ys, _color_for(pt))
        move_ax.scatter(xs, ys, s=26, color=_color_for(pt), alpha=0.6,
                        edgecolor="white", linewidth=0.3, zorder=2)
    if hb is not None and vb is not None and pd.notna(hb) and pd.notna(vb):
        move_ax.scatter([hb], [vb], s=100, color=color, edgecolor="white",
                        linewidth=1.5, zorder=3)
    move_ax.set_title("Movement", fontsize=11, color="white", fontweight="bold", pad=4)
    move_ax.tick_params(colors="white", labelsize=7)
    for spine in move_ax.spines.values():
        spine.set_color("white")
        spine.set_alpha(0.6)

    # -- Bottom band: player / date / pitch count ---------------------------
    _outlined_text(fig, 0.03, 0.038, player_name, fontsize=15, ha="left", color=color)
    _outlined_text(fig, 0.5, 0.038, date, fontsize=15, ha="center", color=color)
    _outlined_text(fig, 0.97, 0.038, f"Pitch {pitch_index}/{pitch_count}",
                   fontsize=15, ha="right", color=color)

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
