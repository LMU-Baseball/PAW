"""LMU-branded pitch-data overlay for a downloadable Edgertronic clip
(2026-09-23, Brad: players want to download their best pitches to share
with recruiters, reference video from the Red Sox showing pitch type/velo/
break up top, a strike-zone box and movement chart on the side).

The layout is a real letterbox, not a transparent overlay floating on top
of the footage: `compute_layout` shrinks the video and reserves solid
white top/right bars (Brad, after seeing dark bullpen footage swallow a
semi-transparent dark band: "make sure its not covering the video, you
can shrink the video so that it all fits on one frame" + "I would like
the white top bar and right side bar so that the text and pitch locations
can be seen easier"). Three steps:
  1. `compute_layout` -- one geometry calculation (video's shrunk size/
     position, bar sizes) shared by the other two, so the drawn overlay
     and the actual video placement can never drift apart.
  2. `build_overlay_png` -- a transparent PNG (matplotlib, Agg, headless,
     same idiom as app.reports.plots/bullpen_plots' static report charts)
     holding just the text/charts/logo, positioned within the layout's bar
     regions. White bars/backgrounds come from ffmpeg's `pad` in the next
     step, not drawn here -- this stays transparent everywhere else so it
     never obscures the video.
  3. `composite_overlay` -- ffmpeg scales the clip down to the layout's
     video size, pads it onto a white canvas at the video's position, then
     overlays this PNG on top (imageio-ffmpeg's portable binary, same as
     app.ingest.bullpen_video.remux_to_mp4 -- no system ffmpeg install
     required).
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile

import matplotlib
matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from app.data.bullpen import _EDGE, _SZ
from app.reports.plots import _add_ellipse, _color_for, _draw_zone

_LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "static", "reports", "lion.png")
_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "reports")
TOP_FRAC = 0.12    # top bar height, as a fraction of the frame's own height
RIGHT_FRAC = 0.19  # right bar width, as a fraction of the frame's own width -- narrower
                   # than the original 0.25 (Brad: "shrink the movement chart a tiny
                   # bit" + "the white space isn't needed at the bottom"): the bottom
                   # margin is leftover from fitting the video's own aspect ratio into
                   # the width left after the right bar, so a narrower right bar both
                   # shrinks the chart real estate AND grows the video's fitted height,
                   # shrinking the bottom leftover -- one knob, both asks.


def _teko(weight: str) -> font_manager.FontProperties:
    """Registers app/static/reports/Teko-*.ttf with matplotlib's font
    manager on first use and returns a FontProperties for one weight --
    the same font family the web app uses (`fontFamily: "Teko, sans-serif"`,
    Brad: "is the font the same font from the web app? if not can it be?").
    Uses `fname=` (an exact file), not family-name matching, since Teko's
    weight files aren't guaranteed to register as distinct matplotlib
    family/weight combinations."""
    path = os.path.join(_FONT_DIR, f"Teko-{weight}.ttf")
    font_manager.fontManager.addfont(path)
    return font_manager.FontProperties(fname=path)


_TEKO_BOLD = _teko("Bold")
_TEKO_SEMIBOLD = _teko("SemiBold")


class OverlayError(RuntimeError):
    """ffmpeg failed, or isn't installed, while compositing an overlay."""


def _ffmpeg_path() -> str:
    """Portable ffmpeg binary bundled with imageio-ffmpeg -- no system
    install required. Mirrors app.ingest.bullpen_video._ffmpeg_path and
    scripts/pitch_video_clips.py's own copy (same idiom, kept separate --
    three independent entry points)."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def compute_layout(width: int, height: int) -> dict:
    """Reserves a solid white top bar (TOP_FRAC of height) and right bar
    (RIGHT_FRAC of width), then fits the video -- shrunk, aspect ratio
    preserved -- into the remaining rectangle, flush against the top bar's
    bottom edge and the frame's left edge. Whatever's left below the video
    becomes a bottom margin (used for the player/date/pitch-count text --
    not a fixed band of its own, just whatever room the aspect-correct fit
    leaves over). Dimensions are rounded to even numbers throughout -- h264
    requires it, and ffmpeg's scale/pad filters reject odd target sizes."""
    def _even(n: int) -> int:
        return n - (n % 2)

    top_h = _even(int(height * TOP_FRAC))
    right_w = _even(int(width * RIGHT_FRAC))
    content_w = width - right_w
    content_h = height - top_h
    scale = min(content_w / width, content_h / height)
    video_w = _even(int(width * scale))
    video_h = _even(int(height * scale))
    video_x, video_y = 0, top_h
    return {
        "width": width, "height": height, "top_h": top_h, "right_w": right_w,
        "video_w": video_w, "video_h": video_h, "video_x": video_x, "video_y": video_y,
        "bottom_y0": video_y + video_h, "bottom_h": height - (video_y + video_h),
    }


def _load_logo_rgba(target_px: int) -> np.ndarray:
    """The LMU sun-lion mark (app/static/reports/lion.png, used elsewhere
    as the default player photo) has an OPAQUE WHITE background -- fine
    now that it's sitting on the layout's own white top bar, so unlike an
    earlier version of this function, the background is NOT stripped to
    transparent here. Resized to `target_px` square before returning --
    `Figure.figimage` (unlike `OffsetImage`) has no `zoom` kwarg, so
    scaling has to happen here, not at placement time."""
    img = Image.open(_LOGO_PATH).convert("RGBA").resize((target_px, target_px),
                                                        Image.LANCZOS)
    return np.array(img)


def build_overlay_png(pitch: dict, session_df: pd.DataFrame, *, player_name: str,
                      date: str, pitch_index: int, pitch_count: int,
                      width: int, height: int) -> bytes:
    """A transparent `width`x`height` PNG holding only the text/charts/
    logo -- the white bars themselves come from `composite_overlay`'s
    ffmpeg pad step (see `compute_layout`), so this stays transparent
    everywhere else and never obscures the video. Pitch type + velo/break
    in the top bar; strike-zone box (this pitch's location) and a movement
    scatter (this pitch highlighted among `session_df`'s other same-
    session pitches) in the right bar; player/date/pitch-count in the
    bottom margin below the shrunk video. `pitch` is one row of
    `app.data.bullpen_video.session_pitch_video_df` (pitch_type, velo,
    horz_break, vert_break, plate_loc_side, plate_loc_height); `session_df`
    is that same DataFrame."""
    layout = compute_layout(width, height)
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="none")

    pitch_type = pitch.get("pitch_type") or "—"
    velo = pitch.get("velo")
    vb, hb = pitch.get("vert_break"), pitch.get("horz_break")
    color = _color_for(pitch_type)

    top_frac = layout["top_h"] / height
    right_x_frac = (width - layout["right_w"]) / width

    # -- LMU sun-lion mark, top-left of the top bar -------------------------
    logo_px = int(layout["top_h"] * 0.8)
    logo = _load_logo_rgba(logo_px)
    fig.figimage(logo, xo=int(width * 0.015),
                yo=height - int(layout["top_h"] * 0.9), zorder=2)

    # -- Top bar text: pitch type (after the logo) + velo/break (right) ----
    text_y = 1 - top_frac / 2
    logo_edge_frac = (int(width * 0.015) + logo_px + width * 0.02) / width
    fig.text(logo_edge_frac, text_y, pitch_type, fontsize=int(layout["top_h"] * 0.4),
             fontproperties=_TEKO_BOLD, color=color, ha="left", va="center")
    metrics = []
    if velo is not None and pd.notna(velo):
        metrics.append(f"{velo:.1f} mph")
    if vb is not None and pd.notna(vb):
        metrics.append(f"VB: {vb:.1f}")
    if hb is not None and pd.notna(hb):
        metrics.append(f"HB: {hb:.1f}")
    fig.text(0.97, text_y, "   ".join(metrics), fontsize=int(layout["top_h"] * 0.22),
             fontproperties=_TEKO_SEMIBOLD, color=color, ha="right", va="center")

    # -- Right bar, upper: strike zone + this pitch's location -------------
    # Plain app.reports.plots._draw_zone (black/gray lines) -- the right
    # bar is solid white now, so the PDF report's own zone-box styling
    # (built for a white page) is exactly right here too.
    zone_ax = fig.add_axes((right_x_frac + 0.02, 0.50, layout["right_w"] / width - 0.05, 0.32))
    zone_ax.set_facecolor("none")
    _draw_zone(zone_ax)
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

    # -- Right bar, lower: movement chart, this pitch highlighted ----------
    # Left margin is still bigger than the zone box's (0.032 vs 0.02) -- the
    # y-axis tick labels here (unlike the zone box, which hides its ticks)
    # render just left of the axes' own left edge, and too small a buffer
    # lets that text cross right_x_frac into the video itself (Brad, from a
    # downloaded clip: "it bleeds into the video a bit"). Widened close to
    # that same edge on both sides since (2026-09-23 round 2, Brad, a later
    # clip): "widen the movement tab just a tiny bit... fill in the white
    # space without bleeding into the video."
    move_ax = fig.add_axes((right_x_frac + 0.032, 0.12, layout["right_w"] / width - 0.062, 0.28))
    move_ax.set_facecolor("none")
    move_ax.axhline(0, color="#ccc", lw=0.8)
    move_ax.axvline(0, color="#ccc", lw=0.8)
    others = session_df[session_df["play_id"] != pitch.get("play_id")]
    for pt, sub in others.groupby("pitch_type"):
        xs, ys = sub["horz_break"].to_numpy(), sub["vert_break"].to_numpy()
        _add_ellipse(move_ax, xs, ys, _color_for(pt))
        move_ax.scatter(xs, ys, s=26, color=_color_for(pt), alpha=0.6,
                        edgecolor="white", linewidth=0.3, zorder=2)
    if hb is not None and vb is not None and pd.notna(hb) and pd.notna(vb):
        move_ax.scatter([hb], [vb], s=100, color=color, edgecolor="white",
                        linewidth=1.5, zorder=3)
    move_ax.set_title("Movement", fontsize=11, color="#9A0021",
                      fontproperties=_TEKO_SEMIBOLD, pad=4)
    move_ax.tick_params(labelsize=7)

    # -- Bottom margin (below the shrunk video): player / date / pitch count
    if layout["bottom_h"] > 0:
        bottom_y = layout["bottom_h"] / 2 / height
        fig.text(0.03, bottom_y, player_name, fontsize=15, fontproperties=_TEKO_BOLD,
                 color=color, ha="left", va="center")
        fig.text(right_x_frac / 2, bottom_y, date, fontsize=15, fontproperties=_TEKO_BOLD,
                 color=color, ha="center", va="center")
        fig.text(right_x_frac - 0.02, bottom_y, f"Pitch {pitch_index}/{pitch_count}",
                 fontsize=15, fontproperties=_TEKO_BOLD, color=color, ha="right", va="center")

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, transparent=True)
    finally:
        plt.close(fig)
    return buf.getvalue()


def composite_overlay(video_bytes: bytes, overlay_png: bytes, layout: dict) -> bytes:
    """Scales the clip down to `layout`'s video size, pads it onto a white
    canvas at `layout`'s video position (the actual letterbox -- solid
    white top/right bars that never sit on top of the footage), then burns
    `overlay_png` on top for the text/charts. `layout` must be the exact
    dict `compute_layout` returned for this same width/height, so the
    video placement and the overlay's own element positions agree. A real
    re-encode, not a remux (`app.ingest.bullpen_video.remux_to_mp4`'s
    `-c copy` doesn't apply here -- scaling and padding touch every
    frame), so this takes noticeably longer than streaming the raw clip;
    acceptable for an occasional manual download, not something run in
    bulk."""
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "in.mp4")
        overlay_path = os.path.join(tmp, "overlay.png")
        out_path = os.path.join(tmp, "out.mp4")
        with open(video_path, "wb") as f:
            f.write(video_bytes)
        with open(overlay_path, "wb") as f:
            f.write(overlay_png)
        filter_complex = (
            f"[0:v]scale={layout['video_w']}:{layout['video_h']},"
            f"pad={layout['width']}:{layout['height']}:"
            f"{layout['video_x']}:{layout['video_y']}:white[bg];"
            f"[bg][1:v]overlay=0:0"
        )
        try:
            subprocess.run(
                [_ffmpeg_path(), "-y", "-i", video_path, "-i", overlay_path,
                 "-filter_complex", filter_complex, "-c:v", "libx264",
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
