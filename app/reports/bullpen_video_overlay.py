"""LMU-branded pitch-data overlay for a downloadable Edgertronic clip
(2026-09-23, Brad: players want to download their best pitches to share
with recruiters, reference video from the Red Sox showing pitch type/velo/
break up top, a strike-zone box and movement chart on the side).

2026-09-27 redesign (Brad, from a broadcast-style reference mockup): a
pre-made banner across the top -- LMU crest, adidas mark, LA skyline, the
VELO/IVB/HB labels and MPH/IN units all baked into the art -- with only the
pitch type and the three numbers drawn onto it, plus a dark textured
sidebar holding location + movement. Mostly white and red.

The overlay never covers the footage: the clip keeps its native size and
the banner/sidebar are added AROUND it, so the output frame is larger than
the clip. Three steps:
  1. `compute_layout` -- one geometry calculation (output frame size, video
     position, banner/sidebar sizes) shared by the other two, so the drawn
     overlay and the actual video placement can never drift apart.
  2. `build_overlay_png` -- a full-frame PNG: opaque banner + sidebar,
     fully transparent over the video region.
  3. `composite_overlay` -- ffmpeg pads the clip onto the larger frame at
     the video's position, then overlays this PNG on top (imageio-ffmpeg's
     portable binary, same as app.ingest.bullpen_video.remux_to_mp4 -- no
     system ffmpeg install required).
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
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from PIL import Image, ImageDraw, ImageFont

from app.data.bullpen import _EDGE, _SZ
from app.reports.plots import _add_ellipse

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "reports")
_FONT_DIR = _ASSETS_DIR
_BANNER_PATH = os.path.join(_ASSETS_DIR, "bullpen-video-banner.png")
# Brad's sidebar art was generated as another landscape strip; this asset is
# its dark, red-splattered right half rotated upright, so the red lands at
# the top-right corner where the reference mockup has it.
_SIDEBAR_PATH = os.path.join(_ASSETS_DIR, "bullpen-video-sidebar.png")
# Hey August (khurasan) -- free for commercial use, see
# HeyAugust-LICENSE.txt. The closest match found, Brush King, is
# personal-use only and can't ship in this public repo without a paid
# license; swapping it in later only means changing this path.
_PITCH_FONT_PATH = os.path.join(_ASSETS_DIR, "HeyAugust.ttf")
_NUMBER_FONT_PATH = os.path.join(_ASSETS_DIR, "Teko-SemiBold.ttf")

# Slot positions measured in the banner PNG's own pixels (1456x176), scaled
# to the rendered banner size at draw time.
_BANNER_SRC_W, _BANNER_SRC_H = 1456, 176
_PITCH_TEXT_X = (408, 935)        # between the adidas mark and the VELO column
_PITCH_TEXT_CY = 88
_PITCH_TEXT_CAP_H = 74
_METRIC_CENTERS_X = (1011, 1137, 1252)   # VELO / IVB / HB
_METRIC_CY = 127                  # between the labels (y<=100) and the units (y>=152)
_METRIC_CAP_H = 34
_METRIC_MAX_W = 96              # inside the 124px-wide columns, clear of the dividers

RIGHT_FRAC = 0.22  # sidebar width as a fraction of the output frame's width
RED = "#D0142C"    # the banner art's own MPH/IN red, rather than CRIMSON


def _teko(weight: str) -> font_manager.FontProperties:
    """Registers app/static/reports/Teko-*.ttf with matplotlib's font
    manager on first use and returns a FontProperties for one weight --
    the same font family the web app uses. Uses `fname=` (an exact file),
    not family-name matching, since Teko's weight files aren't guaranteed
    to register as distinct matplotlib family/weight combinations."""
    path = os.path.join(_FONT_DIR, f"Teko-{weight}.ttf")
    font_manager.fontManager.addfont(path)
    return font_manager.FontProperties(fname=path)


_TEKO_BOLD = _teko("Bold")
_TEKO_MEDIUM = _teko("Medium")


class OverlayError(RuntimeError):
    """ffmpeg failed, or isn't installed, while compositing an overlay."""


def _ffmpeg_path() -> str:
    """Portable ffmpeg binary bundled with imageio-ffmpeg -- no system
    install required. Mirrors app.ingest.bullpen_video._ffmpeg_path and
    scripts/pitch_video_clips.py's own copy (same idiom, kept separate --
    three independent entry points)."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _even(n: float) -> int:
    n = int(round(n))
    return n - (n % 2)


def compute_layout(width: int, height: int) -> dict:
    """Output frame for a `width`x`height` clip: the clip at its native size
    (never shrunk or cropped), a sidebar to its right taking RIGHT_FRAC of
    the final width, and the banner across the full top at the banner art's
    own aspect ratio. Dimensions are even throughout -- h264 requires it,
    and ffmpeg's pad filter rejects odd sizes."""
    video_w, video_h = _even(width), _even(height)
    right_w = _even(video_w * RIGHT_FRAC / (1 - RIGHT_FRAC))
    canvas_w = video_w + right_w
    top_h = _even(canvas_w * _BANNER_SRC_H / _BANNER_SRC_W)
    canvas_h = top_h + video_h
    return {
        "width": canvas_w, "height": canvas_h, "top_h": top_h, "right_w": right_w,
        "video_w": video_w, "video_h": video_h, "video_x": 0, "video_y": top_h,
    }


def _fit_font(path: str, text: str, cap_h: float, max_w: float) -> ImageFont.FreeTypeFont:
    """Largest size whose ink is at most `cap_h` tall and `max_w` wide, so a
    long pitch name shrinks to fit its slot instead of running into VELO."""
    probe = ImageFont.truetype(path, 200)
    x0, y0, x1, y1 = probe.getbbox(text)
    scale = min(cap_h / max(y1 - y0, 1), max_w / max(x1 - x0, 1))
    return ImageFont.truetype(path, max(int(200 * scale), 8))


def _draw_centered(img: Image.Image, text: str, font, cx: float, cy: float) -> None:
    """Centers the text's actual ink box (not the font's line box) on
    (cx, cy) -- line boxes include ascender/descender space, which would
    sit the numbers visibly off-center between the labels and units."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    d.text((cx - (x0 + x1) / 2, cy - (y0 + y1) / 2), text, font=font, fill="white")


def _brush_swoosh(w: int, h: int, seed: int = 7) -> Image.Image:
    """The red dry-brush underline under the pitch name in the reference:
    a thick ragged left end tapering to a point on the right, rising
    slightly. Drawn at 4x then downsampled for smooth edges, with random
    horizontal streaks for the dry-brush texture (fixed seed, so every
    clip gets the same stroke)."""
    ss = 4
    W, H = w * ss, h * ss
    t = np.linspace(0, 1, 80)
    center = H * (0.62 - 0.30 * t)
    ramp = np.where(t < 0.08, t / 0.08, 1 - (t - 0.08) / 0.92)
    thick = H * 0.5 * np.clip(ramp, 0.02, 1) ** 0.8
    xs = t * W
    poly = list(zip(xs, center - thick / 2)) + list(zip(xs[::-1], (center + thick / 2)[::-1]))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    rng = np.random.default_rng(seed)
    rows = rng.uniform(0.55, 1.0, size=(H, 1))
    rows[rng.random((H, 1)) < 0.12] = 0.15
    streaks = np.clip(rows + rng.normal(0, 0.08, size=(H, W)), 0, 1)
    out = Image.new("RGBA", (W, H), RED)
    out.putalpha(Image.fromarray((np.asarray(mask, float) * streaks).astype(np.uint8)))
    return out.resize((w, h), Image.LANCZOS)


def _fmt(v) -> str:
    return f"{v:.1f}" if v is not None and pd.notna(v) else "—"


def _render_banner(pitch: dict, w: int, h: int) -> Image.Image:
    banner = Image.open(_BANNER_PATH).convert("RGBA").resize((w, h), Image.LANCZOS)
    sx, sy = w / _BANNER_SRC_W, h / _BANNER_SRC_H

    name = str(pitch.get("pitch_type") or "Pitch").upper()
    x0, x1 = _PITCH_TEXT_X[0] * sx, _PITCH_TEXT_X[1] * sx
    cap_h = _PITCH_TEXT_CAP_H * sy
    font = _fit_font(_PITCH_FONT_PATH, name, cap_h, x1 - x0)
    bx0, _, bx1, _ = ImageDraw.Draw(banner).textbbox((0, 0), name, font=font)
    text_w = bx1 - bx0
    cy = _PITCH_TEXT_CY * sy
    # Swoosh first so the lettering sits on top of it, as in the reference.
    swoosh = _brush_swoosh(max(int(text_w * 0.95), 8), max(int(cap_h * 0.36), 4))
    banner.alpha_composite(swoosh, (int(x0 + text_w * 0.10), int(cy + cap_h * 0.40)))
    _draw_centered(banner, name, font, x0 + text_w / 2, cy)

    for cx, key in zip(_METRIC_CENTERS_X, ("velo", "ind_vert_break", "horz_break")):
        text = _fmt(pitch.get(key))
        # Same height for every value unless it would crowd the column's
        # dividers (a wide negative like "-14.9"); then it shrinks to fit.
        font = _fit_font(_NUMBER_FONT_PATH, text, _METRIC_CAP_H * sy, _METRIC_MAX_W * sx)
        _draw_centered(banner, text, font, cx * sx, _METRIC_CY * sy)

    ImageDraw.Draw(banner).rectangle((0, h - max(int(2 * sy), 1), w, h), fill="#e8e8e8")
    return banner


def _cover_top_left(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to fill `w`x`h` keeping aspect, cropping only the bottom/right
    overflow so the sidebar art's red top-right corner always survives."""
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))),
                     Image.LANCZOS)
    return img.crop((0, 0, w, h))


def _present(*vals) -> bool:
    return all(v is not None and pd.notna(v) for v in vals)


def _render_sidebar(pitch: dict, session_df: pd.DataFrame, *, player_name: str, date: str,
                    pitch_index: int, pitch_count: int, w: int, h: int) -> Image.Image:
    """LOCATION (zone grid + this pitch), MOVEMENT (the session's pitches of
    this pitch's type in white inside their red ellipse, this pitch as a red
    target dot), then player/date/pitch count."""
    panel = _cover_top_left(Image.open(_SIDEBAR_PATH).convert("RGBA"), w, h)

    dpi = 100
    k = w / 362  # sizes below were tuned on a 1280-wide clip's 362px sidebar
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi, facecolor="none")

    def fy(px: float) -> float:
        return 1 - px / h

    fig.add_artist(Line2D([0.07, 0.07], [fy(h * 0.03), fy(h * 0.97)],
                          color="white", lw=1.4 * k, alpha=0.9))
    left = 0.20

    def heading(label: str, top_px: float) -> None:
        # Spaced-out capitals stand in for the reference's wide letter
        # tracking, which matplotlib text has no setting for.
        fig.text(left, fy(top_px), " ".join(label), fontproperties=_TEKO_MEDIUM,
                 fontsize=17 * k, color="white", ha="left", va="top")
        uy = fy(top_px + 30 * k)
        fig.add_artist(Line2D([left, left + 0.23], [uy, uy], color=RED, lw=1.6 * k))

    def target(ax, x, y) -> None:
        ax.scatter([x], [y], s=260 * k * k, color=RED, edgecolor="none", zorder=4, clip_on=False)
        ax.scatter([x], [y], s=34 * k * k, color="white", edgecolor="none", zorder=5, clip_on=False)

    heading("LOCATION", h * 0.035)
    zone_top = h * 0.035 + 48 * k
    zone_w = 0.72
    zx0, zx1 = _SZ["x0"] - _EDGE * 1.2, _SZ["x1"] + _EDGE * 1.2
    zy0, zy1 = _SZ["y0"] - _EDGE * 1.2, _SZ["y1"] + _EDGE * 1.2
    zone_h_px = zone_w * w * (zy1 - zy0) / (zx1 - zx0)
    zone_ax = fig.add_axes((left, fy(zone_top + zone_h_px), zone_w, zone_h_px / h))
    zone_ax.set_facecolor("none")
    zone_ax.set_xlim(zx0, zx1)
    zone_ax.set_ylim(zy0, zy1)
    zone_ax.set_axis_off()
    zone_ax.add_patch(Rectangle((_SZ["x0"], _SZ["y0"]), _SZ["x1"] - _SZ["x0"],
                                _SZ["y1"] - _SZ["y0"], fill=False, ec="white", lw=1.8 * k))
    for i in (1, 2):
        xi = _SZ["x0"] + (_SZ["x1"] - _SZ["x0"]) * i / 3
        yi = _SZ["y0"] + (_SZ["y1"] - _SZ["y0"]) * i / 3
        zone_ax.plot([xi, xi], [_SZ["y0"], _SZ["y1"]], color="white", lw=0.9 * k, alpha=0.8)
        zone_ax.plot([_SZ["x0"], _SZ["x1"]], [yi, yi], color="white", lw=0.9 * k, alpha=0.8)
    loc_x, loc_y = pitch.get("plate_loc_side"), pitch.get("plate_loc_height")
    if _present(loc_x, loc_y):
        # Clamped into the panel so a wild pitch still shows at the edge.
        target(zone_ax, float(np.clip(loc_x, zx0 + 0.05, zx1 - 0.05)),
               float(np.clip(loc_y, zy0 + 0.05, zy1 - 0.05)))

    move_head = zone_top + zone_h_px + 20 * k
    heading("MOVEMENT", move_head)
    mv_top, mv_bottom = move_head + 50 * k, h * 0.81
    move_ax = fig.add_axes((left + 0.08, fy(mv_bottom), 0.85 - left, (mv_bottom - mv_top) / h))
    move_ax.set_facecolor("none")
    pt_now = pitch.get("pitch_type")
    hb, ivb = pitch.get("horz_break"), pitch.get("ind_vert_break")
    # 2026-09-27, Brad: only this pitch's own type is plotted (a fastball
    # clip shows the session's fastballs, not every pitch type).
    d = session_df.dropna(subset=["horz_break", "ind_vert_break"])
    d = d[d["pitch_type"] == pt_now]
    same = d[d["play_id"] != pitch.get("play_id")]
    _add_ellipse(move_ax, d["horz_break"].to_numpy(), d["ind_vert_break"].to_numpy(), RED)
    for patch in move_ax.patches:
        # Translucent fill with a solid rim, like the reference, instead of
        # _add_ellipse's faint all-over alpha -- and 2 sigma instead of its
        # 1, so it wraps most of the pitch type's cluster the way the
        # reference's does rather than just its core.
        patch.set_width(patch.get_width() * 2)
        patch.set_height(patch.get_height() * 2)
        patch.set_alpha(None)
        patch.set_facecolor(to_rgba(RED, 0.45))
        patch.set_edgecolor(to_rgba(RED, 0.95))
        patch.set_linewidth(1.4 * k)
        patch.set_zorder(1)
    move_ax.scatter(same["horz_break"], same["ind_vert_break"], s=40 * k * k, color="white",
                    alpha=0.7, edgecolor="none", zorder=3)
    xs = list(d["horz_break"]) + ([hb] if _present(hb) else [])
    ys = list(d["ind_vert_break"]) + ([ivb] if _present(ivb) else [])
    # Fixed -20..20 / -5..25 like the reference unless the session's
    # pitches actually fall outside it.
    xlim = max(20.0, max((abs(v) for v in xs), default=0) + 4)
    move_ax.set_xlim(-xlim, xlim)
    move_ax.set_ylim(min(-5.0, min(ys, default=0) - 4), max(25.0, max(ys, default=0) + 4))
    if _present(hb, ivb):
        target(move_ax, hb, ivb)
    move_ax.grid(True, color="white", alpha=0.14, lw=0.8 * k)
    for side in ("top", "right"):
        move_ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        move_ax.spines[side].set_color("white")
        move_ax.spines[side].set_alpha(0.8)
        move_ax.spines[side].set_linewidth(1.0 * k)
    move_ax.tick_params(colors="white", length=0, pad=6 * k)
    for lbl in move_ax.get_xticklabels() + move_ax.get_yticklabels():
        lbl.set_fontproperties(_TEKO_MEDIUM)
        lbl.set_fontsize(12 * k)
    move_ax.set_xlabel("HORIZONTAL BREAK (IN)", fontproperties=_TEKO_MEDIUM,
                       fontsize=12 * k, color="white", labelpad=2 * k)
    move_ax.set_ylabel("VERTICAL BREAK (IN)", fontproperties=_TEKO_MEDIUM,
                       fontsize=12 * k, color="white", labelpad=2 * k)

    fig.text(left, fy(h * 0.9), player_name.upper(), fontproperties=_TEKO_BOLD,
             fontsize=20 * k, color="white", ha="left", va="top")
    fig.text(left, fy(h * 0.9 + 30 * k), f"{date}   ·   PITCH {pitch_index}/{pitch_count}",
             fontproperties=_TEKO_MEDIUM, fontsize=14 * k, color=RED, ha="left", va="top")

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, transparent=True)
    finally:
        plt.close(fig)
    panel.alpha_composite(Image.open(buf).convert("RGBA").resize((w, h)))
    return panel


def build_overlay_png(pitch: dict, session_df: pd.DataFrame, *, player_name: str,
                      date: str, pitch_index: int, pitch_count: int,
                      width: int, height: int) -> bytes:
    """The full-frame overlay for a `width`x`height` clip, sized to
    `compute_layout(width, height)`'s output frame (larger than the clip):
    opaque banner and sidebar, fully transparent over the video region.
    `pitch` is one row of `app.data.bullpen_video.session_pitch_video_df`
    (pitch_type, velo, horz_break, ind_vert_break, plate_loc_side,
    plate_loc_height); `session_df` is that same DataFrame. Vertical break
    is INDUCED vert break (IVB), not raw -- pairs with HB the way pitching
    actually reads movement (2026-09-24, Brad: "IVB needs to be used with
    HB")."""
    layout = compute_layout(width, height)
    canvas = Image.new("RGBA", (layout["width"], layout["height"]), (0, 0, 0, 0))
    canvas.alpha_composite(_render_banner(pitch, layout["width"], layout["top_h"]), (0, 0))
    sidebar = _render_sidebar(
        pitch, session_df, player_name=player_name, date=str(date),
        pitch_index=pitch_index, pitch_count=pitch_count,
        w=layout["right_w"], h=layout["height"] - layout["top_h"])
    canvas.alpha_composite(sidebar, (layout["width"] - layout["right_w"], layout["top_h"]))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def composite_overlay(video_bytes: bytes, overlay_png: bytes, layout: dict) -> bytes:
    """Pads the clip onto `layout`'s larger output frame at the video's
    position, then burns `overlay_png` on top for the banner/sidebar.
    `layout` must be the exact dict `compute_layout` returned for this same
    clip, so the video placement and the overlay's own element positions
    agree. A real re-encode, not a remux (`app.ingest.bullpen_video.
    remux_to_mp4`'s `-c copy` doesn't apply here -- padding touches every
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
            f"{layout['video_x']}:{layout['video_y']}:black[bg];"
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
