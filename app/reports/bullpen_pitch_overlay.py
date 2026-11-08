"""Pitch Overlay video: 1-3 bullpen pitches' Edgertronic clips lined up at
release, next to their Trackman flight paths, rendered to one MP4.

Pitching staff use it two ways (2026-11-07): tunneling (different pitch
types from the same pen) and mechanics (the same pitch from two different
pens, e.g. Monday's 95 vs Friday's 88). Two layouts:

  - "overlay": the clips stacked into one ghosted frame, each tinted its
    own color. Only reads well when the camera didn't move between clips,
    i.e. pitches from the same bullpen.
  - "side": the clips tiled next to each other, still release-synced. The
    Edger gets moved between pens (different mound, zoom, angle), so this
    is the layout for comparing across days.

Release is found per clip from the arm-speed motion peak, not a fixed
frame: clip length (0.8-1.5 s) changes between sessions, and with it the
release frame. A per-clip `nudge` (in 240 fps frames) corrects a miss.

The flight panel is drawn with PIL rather than matplotlib -- a full
matplotlib redraw per output frame made one render take over a minute.
"""
from __future__ import annotations

import functools
import os
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.reports.bullpen_video_overlay import (_ENCODE_THREADS, _FONT_DIR, OverlayError,
                                                _encode_slot, _ffmpeg_path)

COLORS = [(255, 77, 77), (77, 163, 255), (255, 210, 63)]
MAX_PITCHES = len(COLORS)
MODES = ("overlay", "side")

SRC_FPS = 240.0
OUT_FPS = 30
PRE, POST, HOLD = 150, 140, 45
GW, GH = 720, 566
TW, TH = 480, 378
PW, H = 560, 760
BG = (21, 23, 28)
# The motion peak lands ~2 frames before the ball is out of the hand
# (checked by eye on 11 clips across 0.8-1.5 s clip lengths).
REL_AFTER_PEAK = 2
PLATE_FRONT_Y = 17 / 12
TUNNEL_Y = 23.8


@dataclass
class OverlayClip:
    pitch: dict
    data: bytes
    nudge: int = 0


@functools.lru_cache(maxsize=32)
def _font(size: int, weight: str = "Medium") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(_FONT_DIR, f"Teko-{weight}.ttf"), size)


def detect_release(energy: np.ndarray) -> int:
    """Release frame from a clip's per-frame motion energy: the strongest
    smoothed motion in the middle of the clip (the arm whip), searched only
    between 35% and 85% of the way through so a camera bump at either end
    can't win."""
    n = len(energy) + 1
    if n < 10:
        return n // 2
    smooth = np.convolve(energy, np.ones(5) / 5, mode="same")
    lo, hi = int(n * 0.35), max(int(n * 0.85), int(n * 0.35) + 1)
    return min(lo + int(np.argmax(smooth[lo:hi])) + REL_AFTER_PEAK, n - 1)


def box_blur(a: np.ndarray, r: int = 2) -> np.ndarray:
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(p, 0)
    c = np.concatenate([c[k - 1:k], c[k:] - c[:-k]], 0)
    c = np.cumsum(c, 1)
    c = np.concatenate([c[:, k - 1:k], c[:, k:] - c[:, :-k]], 1)
    return c / (k * k)


def flight_path(p: dict, n: int = 150):
    """(t since release, x, y, z) in feet from Trackman's 9-parameter fit,
    release (y = 60.5 - Extension) to the front of the plate. x is already
    the catcher's view (+ = 1B side; a righty releases at negative x), the
    mirror of Trackman's pitcher's-view PlateLocSide/RelSide. None when the
    pitch has no trajectory fit."""
    keys = ("x0", "y0", "z0", "vx0", "vy0", "vz0", "ax0", "ay0", "az0")
    try:
        x0, y0, z0, vx0, vy0, vz0, ax0, ay0, az0 = (float(p[k]) for k in keys)
    except (KeyError, TypeError, ValueError):
        return None
    if not np.isfinite([x0, y0, z0, vx0, vy0, vz0, ax0, ay0, az0]).all() or ay0 == 0:
        return None
    ext = p.get("extension")
    ext = float(ext) if ext is not None and np.isfinite(float(ext)) else 6.0
    a = 0.5 * ay0

    def t_at(yy):
        disc = vy0 ** 2 - 4 * a * (y0 - yy)
        return (-vy0 - np.sqrt(max(disc, 0.0))) / (2 * a)

    t_rel, t_pl = t_at(60.5 - ext), t_at(PLATE_FRONT_Y)
    t = np.linspace(t_rel, t_pl, n)
    x = x0 + vx0 * t + 0.5 * ax0 * t * t
    y = y0 + vy0 * t + 0.5 * ay0 * t * t
    z = z0 + vz0 * t + 0.5 * az0 * t * t
    return t - t_rel, x, y, z


def separation_in(path_a, path_b, y_ft: float) -> float | None:
    if path_a is None or path_b is None:
        return None
    pts = []
    for _, x, y, z in (path_a, path_b):
        i = int(np.argmin(np.abs(y - y_ft)))
        pts.append((x[i], z[i]))
    return 12 * float(np.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]))


def _decode(path: str, w: int, h: int, gray: bool):
    fmt, ch = ("gray", 1) if gray else ("rgb24", 3)
    proc = subprocess.Popen(
        [_ffmpeg_path(), "-v", "error", "-i", path, "-vf", f"scale={w}:{h},format={fmt}",
         "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * ch
    shape = (h, w) if gray else (h, w, 3)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(shape)
    finally:
        proc.stdout.close()
        proc.wait()


class _Stream:
    """Sequential frame access that holds the first frame before the clip
    starts and the last frame after it ends, so clips of different length
    stay in lockstep around release."""

    def __init__(self, frames):
        self._it = frames
        self._idx = -1
        self._cur = None

    def at(self, i: int) -> np.ndarray:
        while self._idx < max(i, 0):
            nxt = next(self._it, None)
            if nxt is None:
                break
            self._cur, self._idx = nxt, self._idx + 1
        return self._cur


_LUT_OVERLAY = (255 * (np.arange(256) / 255) ** 0.45).astype(np.uint8)
_LUT_SIDE = (255 * (np.arange(256) / 255) ** 0.65).astype(np.uint8)


def _scan(path: str, w: int, h: int, gray: bool, keep_every: int):
    """One pass over a clip: motion energy per frame (for release) plus a
    sparse sample of frames (for the overlay's shared background)."""
    energy, samples, prev = [], [], None
    for i, f in enumerate(_decode(path, w, h, gray)):
        small = (f if gray else f.mean(axis=2))[::4, ::4].astype(np.float32)
        small = _LUT_OVERLAY[small.astype(np.uint8)].astype(np.float32)
        if prev is not None:
            energy.append(float(np.abs(small - prev).mean()))
        prev = small
        if keep_every and i % keep_every == 0:
            samples.append(_LUT_OVERLAY[f] if gray else f)
    return np.array(energy), samples


def _player_name(raw: str | None) -> str:
    if not raw:
        return ""
    last, _, first = str(raw).partition(", ")
    return f"{first} {last}".strip()


def _fmt(v, spec: str) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if not np.isfinite(f) else format(f, spec)


def pitch_label(p: dict) -> str:
    d = str(p.get("date") or "")
    md = f"{d[5:7]}/{d[8:10]}" if len(d) >= 10 else d
    return f"{md} {p.get('pitch_type') or 'Pitch'} {_fmt(p.get('velo'), '.1f')}"


class _FlightPanel:
    """Catcher's-view perspective + side view, drawn at 2x and downsampled
    for antialiasing. The static parts (zone, plate, axes) are drawn once."""

    S = 2
    CAM = (0.0, -7.0, 3.4)
    FOC = 330.0
    SCALE = 3.36
    TOP_V = 45.0
    # Low pitches project below the side view's top edge; the catcher's
    # view is drawn on a layer cropped here so they can't spill into it.
    VIEW_BOTTOM = 486

    def __init__(self, paths, colors):
        self.paths, self.colors = paths, colors
        s = self.S
        self.base = Image.new("RGB", (PW * s, H * s), BG)
        d = ImageDraw.Draw(self.base)
        d.text((PW * s // 2, 24 * s), "Catcher's view", fill=(200, 204, 212),
               font=_font(22 * s), anchor="mt")
        zx = [-0.83, 0.83, 0.83, -0.83, -0.83]
        zz = [1.5, 1.5, 3.5, 3.5, 1.5]
        d.line([self._cv(x, PLATE_FRONT_Y, z) for x, z in zip(zx, zz)], fill=(138, 143, 153), width=2 * s)
        x0, x1, y0, y1 = self._side_box()
        d.rectangle([x0, y0, x1, y1], outline=(58, 63, 72), width=s)
        tick = _font(16 * s)
        for ft in range(0, 61, 10):
            u = self._sv(ft, 0)[0]
            d.line([u, y1, u, y1 + 5 * s], fill=(138, 143, 153), width=s)
            d.text((u, y1 + 7 * s), str(ft), fill=(138, 143, 153), font=tick, anchor="mt")
        for ft in (0, 2, 4, 6):
            v = self._sv(0, ft)[1]
            d.text((x0 - 6 * s, v), str(ft), fill=(138, 143, 153), font=tick, anchor="rm")
        zt, zb = self._sv(0, 3.5)[1], self._sv(0, 1.5)[1]
        d.rectangle([x1 - 6 * s, zt, x1, zb], fill=(90, 94, 102))
        d.text((PW * s // 2, y1 + 26 * s), "Side view  ·  feet from home plate", fill=(138, 143, 153),
               font=tick, anchor="mt")

    def _side_box(self):
        s = self.S
        return 46 * s, (PW - 16) * s, 506 * s, 716 * s

    def _sv(self, y_ft, z_ft):
        x0, x1, y0, y1 = self._side_box()
        return x0 + (62 - y_ft) / 63 * (x1 - x0), y1 - z_ft / 7.5 * (y1 - y0)

    def _cv(self, x, y, z):
        d = y - self.CAM[1]
        u, v = self.FOC * (x - self.CAM[0]) / d, self.FOC * (z - self.CAM[2]) / d
        s = self.S
        return (PW / 2 + u * self.SCALE) * s, (60 + (self.TOP_V - v) * self.SCALE) * s

    def frame(self, tt: float) -> np.ndarray:
        img = self.base.copy()
        s = self.S
        view = img.crop((0, 0, PW * s, self.VIEW_BOTTOM * s))
        dv = ImageDraw.Draw(view)
        d = ImageDraw.Draw(img)
        for path, col in zip(self.paths, self.colors):
            if path is None or tt < 0:
                continue
            t, x, y, z = path
            m = int(np.searchsorted(t, tt, side="right"))
            if m < 2:
                continue
            pts = [self._cv(x[i], y[i], z[i]) for i in range(m)]
            for i in range(m - 1):
                dist = y[i] - self.CAM[1]
                dv.line([pts[i], pts[i + 1]], fill=col, width=int(np.clip(110 / dist, 1, 14) * s))
            dist = y[m - 1] - self.CAM[1]
            r = float(np.clip(np.sqrt(2500 / dist) * 0.75, 3, 10)) * s
            cx, cy = pts[-1]
            dv.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255), outline=col, width=2 * s)
            side = [self._sv(y[i], z[i]) for i in range(m)]
            d.line(side, fill=col, width=3 * s)
            cx, cy = side[-1]
            d.ellipse([cx - 5 * s, cy - 5 * s, cx + 5 * s, cy + 5 * s], fill=(255, 255, 255),
                      outline=col, width=2 * s)
        img.paste(view, (0, 0))
        return np.asarray(img.resize((PW, H), Image.LANCZOS))


def _ghost(frames, bg, colors) -> np.ndarray:
    """Each clip's moving parts (where it differs from the shared
    background), tinted its color, over a dimmed background. In-place
    float32 per channel -- this runs once per output frame and dominates
    the render time."""
    out = np.empty(bg.shape + (3,), np.float32)
    out[:] = (bg * 0.45)[..., None]
    for f, col in zip(frames, colors):
        alpha = box_blur(np.abs(f - bg))
        alpha -= 12
        alpha *= 0.75 / 20
        np.clip(alpha, 0, 0.75, out=alpha)
        lum = f * (0.5 / 255)
        lum += 0.5
        for c in range(3):
            ch = out[..., c]
            ch += alpha * (lum * col[c] - ch)
    return np.clip(out, 0, 255).astype(np.uint8)


def _captions(img: Image.Image, top: int, pitches, paths, colors) -> None:
    d = ImageDraw.Draw(img)
    title_font, line_font, small = _font(30, "SemiBold"), _font(24), _font(21)
    names = {_player_name(p.get("pitcher")) for p in pitches}
    who = next(iter(names)) if len(names) == 1 else "Pitch comparison"
    d.text((16, top + 6), f"{who}  ·  bullpen pitch overlay  ·  aligned at release",
           fill=(235, 236, 240), font=title_font)
    y = top + 44
    for p, col in zip(pitches, colors):
        d.rectangle([16, y + 6, 34, y + 22], fill=col)
        line = (f"{pitch_label(p)} mph    IVB {_fmt(p.get('ind_vert_break'), '.1f')}    "
                f"HB {_fmt(p.get('horz_break'), '.1f')}    spin {_fmt(p.get('spin'), '.0f')}    "
                f"ext {_fmt(p.get('extension'), '.1f')}")
        if len(names) > 1:
            line = f"{_player_name(p.get('pitcher'))}  ·  {line}"
        d.text((44, y), line, fill=(222, 224, 230), font=line_font)
        y += 30
    for path, col in list(zip(paths, colors))[1:]:
        at24 = separation_in(paths[0], path, TUNNEL_Y)
        at_plate = separation_in(paths[0], path, 1.42)
        if at24 is None or at_plate is None:
            continue
        d.text((16, y + 4), f"vs first pitch:  {at24:.1f} in apart at 24 ft,  {at_plate:.1f} in apart at the plate",
               fill=col, font=small)
        y += 26


def _timer(img: Image.Image, x_right: int, tt: float) -> None:
    d = ImageDraw.Draw(img)
    label = "before release" if tt < 0 else f"+{tt:.3f} s after release"
    d.text((x_right, 10), label, fill=(255, 255, 255), font=_font(30, "SemiBold"), anchor="ra")
    d.text((x_right, 44), "8x slow motion", fill=(170, 175, 185), font=_font(22), anchor="ra")


def render(clips: list[OverlayClip], mode: str = "overlay") -> bytes:
    """MP4 bytes for 1-3 clips. Raises OverlayError if ffmpeg fails."""
    if not 1 <= len(clips) <= MAX_PITCHES:
        raise ValueError(f"need 1-{MAX_PITCHES} clips, got {len(clips)}")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    colors = COLORS[:len(clips)]
    pitches = [c.pitch for c in clips]
    paths = [flight_path(p) for p in pitches]
    overlay = mode == "overlay"
    vw, vh = (GW, GH) if overlay else (TW, TH)
    left_w = GW if overlay else max(GW, TW * len(clips))
    canvas_w = left_w + PW
    n_out = PRE + POST

    with tempfile.TemporaryDirectory() as tmp, _encode_slot():
        srcs = []
        for i, c in enumerate(clips):
            src = os.path.join(tmp, f"in{i}.mp4")
            with open(src, "wb") as fh:
                fh.write(c.data)
            srcs.append(src)

        releases, samples = [], []
        for src, c in zip(srcs, clips):
            energy, kept = _scan(src, vw, vh, overlay, 6 if overlay else 0)
            releases.append(detect_release(energy) + int(c.nudge or 0))
            samples.append(kept)

        bg = None
        if overlay:
            ref = np.mean(samples[0]) if samples[0] else 1.0
            gains = [ref / max(np.mean(s), 1.0) if s else 1.0 for s in samples]
            bg = np.median(np.concatenate([np.stack(s).astype(np.float32) * g
                                           for s, g in zip(samples, gains) if s]),
                           axis=0).astype(np.float32)
        del samples

        streams = [_Stream(_decode(src, vw, vh, overlay)) for src in srcs]
        panel = _FlightPanel(paths, colors)
        out_path = os.path.join(tmp, "out.mp4")
        enc = subprocess.Popen(
            [_ffmpeg_path(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{canvas_w}x{H}", "-r", str(OUT_FPS), "-i", "-", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "21", "-threads", _ENCODE_THREADS,
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            frame = None
            for k in range(n_out + HOLD):
                kk = min(k, n_out - 1)
                tt = (kk - PRE) / SRC_FPS
                if k < n_out:
                    raw = [s.at(r - PRE + kk) for s, r in zip(streams, releases)]
                    left = Image.new("RGB", (left_w, H), BG)
                    if overlay:
                        g = [np.clip(_LUT_OVERLAY[f].astype(np.float32) * np.float32(gain), 0, 255)
                             for f, gain in zip(raw, gains)]
                        left.paste(Image.fromarray(_ghost(g, bg, colors)), (0, 0))
                        _timer(left, GW - 14, tt)
                        _captions(left, GH, pitches, paths, colors)
                    else:
                        x0 = (left_w - TW * len(clips)) // 2
                        d = ImageDraw.Draw(left)
                        for i, (f, col, p) in enumerate(zip(raw, colors, pitches)):
                            left.paste(Image.fromarray(_LUT_SIDE[f]), (x0 + i * TW, 70))
                            d.rectangle([x0 + i * TW, 70 + TH - 6, x0 + (i + 1) * TW - 1, 70 + TH - 1], fill=col)
                            d.text((x0 + i * TW + 8, 70 + TH - 10), pitch_label(p), fill=(255, 255, 255),
                                   font=_font(24, "SemiBold"), anchor="lb", stroke_width=2, stroke_fill=(0, 0, 0))
                        _timer(left, left_w - 14, tt)
                        _captions(left, 70 + TH + 8, pitches, paths, colors)
                    frame = np.concatenate([np.asarray(left), panel.frame(tt)], axis=1)
                else:
                    frame = np.concatenate([frame[:, :left_w], panel.frame(
                        (n_out - 1 - PRE) / SRC_FPS + (k - n_out + 1) / SRC_FPS)], axis=1)
                enc.stdin.write(np.ascontiguousarray(frame).tobytes())
            enc.stdin.close()
            err = enc.stderr.read()
            if enc.wait() != 0:
                raise OverlayError(err.decode(errors="replace")[-500:])
        except BrokenPipeError as exc:
            enc.wait()
            raise OverlayError(enc.stderr.read().decode(errors="replace")[-500:]) from exc
        finally:
            for s in streams:
                s._it.close()
        with open(out_path, "rb") as fh:
            return fh.read()
