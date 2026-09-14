"""Building the Engine's body visual: five small panels (IR, ER, Scaption,
Grip, ROM) instead of one combined figure -- 2026-09-11 feedback ("each
separate visuals, fit on the white space in the left column"). Each strength
panel pairs the real player-cutout silhouette (a translucent colored blob
positioned over the tested body region, behind the cutout's outline so it
reads as a highlighted zone rather than a floating shape) with a donut/ring
gauge built fresh in CSS (`conic-gradient`, no image) in the site's crimson/
white/Teko language. The ROM panel shares the same shoulder-highlighted
cutout with three plain text readouts instead of three separate gauges.

The cutout (`app/static/reports/player-cutout.png`, a transparent-
background line-art outline, 200x200) is Brad's own asset from last year's
tool -- swapped in in place of a from-scratch SVG figure because a
programmatically-drawn body doesn't read as well as reused real art.
Coordinates below were picked by inspecting the PNG's actual ink (alpha>10)
per row/column, then confirmed by rendering in a browser -- see this
module's originating fork report for the pixel analysis.
"""
from __future__ import annotations

from dash import html

from app.data import splash_report as SR
from app.dashboards.shell import CRIMSON

_CUTOUT_SRC = "/static/reports/player-cutout.png"
_TRACK_COLOR = "#e6e6e6"
_FLAG_COLOR = {None: "#c9c9c9", "ok": "#4a8f4a", "yellow": "#d9a400", "red": "#c0193a"}

# Highlight blobs, in PERCENT of the (square) cutout image -- {left, top,
# width, height} of the box the blob fills, drawn for a RIGHT-handed
# thrower (throwing arm on the viewer's LEFT, i.e. the smaller-x side of
# the 200x200 source image; see `_mirror_box`). Picked from the source
# PNG's actual ink extent: shoulder cap centered ~(80, 62) of 200, hand/
# forearm centered ~(65, 100) of 200 (the outstretched arm's widest point).
_SHOULDER_BOX = {"left": 30.0, "top": 22.0, "width": 20.0, "height": 18.0}
_HAND_BOX = {"left": 24.0, "top": 42.0, "width": 15.0, "height": 15.0}

# (metric_key, panel title, highlight box) for the four strength panels.
# IR/ER titled "Internal/External Strength" (2026-09-14, Brad: "Rotation"
# read as a range-of-motion term next to the actual ROM panel) -- the
# metric_key stays "IR"/"ER" (matches app.data.splash_report), only the
# displayed title changed.
_STRENGTH_PANELS = [
    ("IR", "Internal Strength", _SHOULDER_BOX),
    ("ER", "External Strength", _SHOULDER_BOX),
    ("Scaption", "Scaption", _SHOULDER_BOX),
    ("Grip", "Grip", _HAND_BOX),
]


def _mirror_box(box: dict, *, mirror: bool) -> dict:
    """Flip a {left, top, width, height} box across the image's vertical
    centerline (50%) for a left-handed thrower. All panels are drawn for a
    right-handed thrower by default (throwing side = smaller x = viewer's
    left), matching the convention the old single-figure version used."""
    if not mirror:
        return box
    return {**box, "left": 100.0 - box["left"] - box["width"]}


def _highlighted_cutout(box: dict, color: str, *, size_px: int = 150) -> html.Div:
    """The cutout image with a translucent colored blob behind it, clipped
    to sit inside the silhouette -- the blob is a plain rounded rect (not a
    tight body-part shape; the transparent PNG interior means anything
    behind it only shows through the areas the outline doesn't cover, so a
    soft-edged box reads as "this region of the body" without needing a
    precise anatomical mask). ~55% fill-opacity: strong enough to read as
    highlighted, translucent enough that the outline stroke drawn on top
    (and the page background through the image's own transparent parts)
    both stay visible, per Brad's "opaque enough to see through the body.\""""
    blob = html.Div(style={
        "position": "absolute", "left": f"{box['left']}%", "top": f"{box['top']}%",
        "width": f"{box['width']}%", "height": f"{box['height']}%",
        "backgroundColor": color, "opacity": "0.55", "borderRadius": "45%",
        "filter": "blur(1.5px)",
    })
    img = html.Img(src=_CUTOUT_SRC, style={
        "position": "relative", "width": f"{size_px}px", "height": f"{size_px}px",
        "display": "block",
    })
    return html.Div([blob, img], style={
        "position": "relative", "width": f"{size_px}px", "height": f"{size_px}px",
        "flexShrink": "0",
    })


def _ring_gauge(value, baseline, color, *, size_px: int = 112) -> html.Div:
    """A donut/ring gauge built from a CSS conic-gradient (no image, no raw
    SVG -- this Dash version has no SVG components in `dash.html`, and
    Brad asked for a fresh simplified icon here rather than reusing the
    cutout art). Fill fraction = value/baseline, clamped to [0, 100]% so a
    player who exceeds the D1 average still just shows a full ring instead
    of overflowing it; the raw number is always the actual value, not the
    clamped fraction."""
    if value is None or baseline in (None, 0):
        pct = 0.0
        text = "—"
    else:
        pct = max(0.0, min(1.0, float(value) / float(baseline))) * 100.0
        text = f"{value:g}"
    ring_bg = f"conic-gradient({color} {pct:.0f}%, {_TRACK_COLOR} {pct:.0f}%)"
    # Font scales with the ring itself (2026-09-14: at the compact grid's
    # smaller gauge_px, the old fixed 30px overflowed past the ring's inner
    # white circle) -- ~0.27x the ring diameter matches the original 112px
    # ring's 30px text, floored so 3-digit values (e.g. "140") stay legible.
    font_px = max(13, round(size_px * 0.27))
    return html.Div([
        html.Div(style={
            "width": f"{size_px - 10}px", "height": f"{size_px - 10}px",
            "borderRadius": "50%", "backgroundColor": "#fff",
            "display": "flex", "alignItems": "center", "justifyContent": "center",
            "fontFamily": "Teko, sans-serif", "fontSize": f"{font_px}px", "fontWeight": "bold",
            "color": CRIMSON,
        }, children=text),
    ], style={
        "width": f"{size_px}px", "height": f"{size_px}px", "borderRadius": "50%",
        "background": ring_bg, "display": "flex", "alignItems": "center",
        "justifyContent": "center", "flexShrink": "0",
    })


def _strength_panel(key: str, title: str, box: dict, row: dict, *, mirror: bool,
                    compact: bool = False) -> html.Div:
    flag = row.get("flag")
    color = _FLAG_COLOR.get(flag, _FLAG_COLOR[None])
    # 2026-09-14: Brad wants the skeleton bigger and the number-ring smaller
    # in the compact grid -- there's room since compact already stacks
    # cutout above gauge instead of side by side. Round 2 (Brad, after
    # adding the Scaption ROM readout row): the ROM panel is now taller
    # than these four (an extra text line), which left visible white space
    # under the shorter panels in their shared flex row -- sizing the ring
    # back up a bit (46 -> 60px) adds height back to close that gap.
    size_px = 130 if compact else 150
    gauge_px = 60 if compact else 112
    cutout = _highlighted_cutout(_mirror_box(box, mirror=mirror), color, size_px=size_px)
    gauge = _ring_gauge(row.get("now_value"), row.get("d1_baseline"), color, size_px=gauge_px)
    # Compact (2026-09-14 layout test, 3-col right-wall grid): cutout+gauge
    # stack vertically instead of side by side -- at this width, a flex ROW
    # of the two would be wider than a 1fr column in a 3-col grid, forcing
    # the grid to overflow the right column instead of the 3 panels sitting
    # side by side like Brad asked.
    title_style = {"fontWeight": "bold", "color": CRIMSON,
                  "textTransform": "uppercase", "marginBottom": "6px"}
    if compact:
        pair_style = {"display": "flex", "flexDirection": "column",
                     "alignItems": "center", "gap": "6px"}
        title_style = {**title_style, "fontSize": "12px", "textAlign": "center"}
        wrap_style = {}
    else:
        pair_style = {"display": "flex", "alignItems": "center", "gap": "14px"}
        title_style = {**title_style, "fontSize": "14px"}
        wrap_style = {"marginBottom": "20px"}
    return html.Div([
        html.Div(title, style=title_style),
        html.Div([cutout, gauge], style=pair_style),
    ], style=wrap_style)


def _rom_readout(label: str, row: dict) -> html.Div:
    flag = row.get("flag")
    color = _FLAG_COLOR.get(flag, _FLAG_COLOR[None])
    now_v = row.get("now_value")
    text = "—" if now_v is None else f"{now_v:g}°"
    return html.Div([
        html.Span(style={"display": "inline-block", "width": "10px", "height": "10px",
                         "borderRadius": "50%", "backgroundColor": color,
                         "marginRight": "6px"}),
        html.Span(f"{label}: {text}", style={"fontSize": "14px"}),
    ], style={"marginBottom": "4px"})


def _rom_panel(by_key: dict, *, mirror: bool, compact: bool = False) -> html.Div:
    # Same shoulder region as IR/ER/Scaption -- IROM/EROM/ScaptionROM/
    # TotalArc test the same joint. Worst (most severe) flag among the four
    # drives the highlight color, so the cutout still shows red if any one
    # of them is red even though the readouts list all four individually.
    # ScaptionROM (2026-09-14, Brad: "measuring Scaption ROM as well, not
    # just strength") reuses this SAME panel/cutout -- just another dot +
    # readout line, no separate skeleton.
    _SEVERITY = {"red": 3, "yellow": 2, "ok": 1, None: 0}
    rom_keys = ("IROM", "EROM", "ScaptionROM", "TotalArc")
    worst = max((by_key.get(k, {}).get("flag") for k in rom_keys),
               key=lambda f: _SEVERITY.get(f, 0), default=None)
    color = _FLAG_COLOR.get(worst, _FLAG_COLOR[None])
    size_px = 130 if compact else 150
    cutout = _highlighted_cutout(_mirror_box(_SHOULDER_BOX, mirror=mirror), color,
                                 size_px=size_px)
    readouts = html.Div([_rom_readout(SR.ENGINE_METRIC_LABELS.get(k, k), by_key.get(k, {}))
                         for k in rom_keys])
    title_style = {"fontWeight": "bold", "color": CRIMSON,
                  "textTransform": "uppercase", "marginBottom": "6px"}
    if compact:
        pair_style = {"display": "flex", "flexDirection": "column",
                     "alignItems": "center", "gap": "6px"}
        title_style = {**title_style, "fontSize": "12px", "textAlign": "center"}
        wrap_style = {}
    else:
        pair_style = {"display": "flex", "alignItems": "center", "gap": "14px"}
        title_style = {**title_style, "fontSize": "14px"}
        wrap_style = {"marginBottom": "20px"}
    return html.Div([
        html.Div("Range of Motion", style=title_style),
        html.Div([cutout, readouts], style=pair_style),
    ], style=wrap_style)


def render(engine_records: list[dict], throws: str | None, *, compact: bool = False) -> html.Div:
    """`engine_records` is `data["engine"]` (see `app.data.splash_report.
    read_engine_metrics`) -- already carries `flag`/`now_value`/
    `d1_baseline` per metric, so no DB access here. `throws` ("Left"/
    "Right"/None) mirrors which side of the cutout gets highlighted;
    unknown defaults to the right-handed side. `compact` (2026-09-14
    right-wall layout test, see layout.render_from_data): lays the 5 panels
    out as a 3-column CSS grid at reduced size instead of one stacked
    column, so they fit side by side in a page column instead of the full
    left sidebar."""
    by_key = {r["metric_key"]: r for r in (engine_records or [])}
    mirror = str(throws).strip().lower().startswith("l")
    panels = [_strength_panel(key, title, box, by_key.get(key, {}), mirror=mirror,
                              compact=compact)
             for key, title, box in _STRENGTH_PANELS]
    panels.append(_rom_panel(by_key, mirror=mirror, compact=compact))
    if not compact:
        return html.Div(panels)
    # 2026-09-14 round 3 (Brad: still a lot of white space on a big monitor;
    # wants a single row of 5 when there's room, wrapping to 3x2 / 2x2x1 /
    # 1x5 as the column narrows -- on a phone or a smaller window). A fixed
    # grid (previous rounds' 3-col-then-2 split) can't do that: CSS Grid's
    # column count is fixed once set, so it never grows to 5-across on a
    # wide screen. Flexbox with wrap solves both asks at once and needs no
    # media queries: each panel's natural content width (~150px) is its
    # flex-basis, so the container fits as many per row as its OWN actual
    # width allows -- 5 across on a wide right column, fewer as it narrows,
    # down to 1 per row on a phone. `justifyContent: center` also means an
    # incomplete last row (e.g. 2 of 5) centers itself instead of left-
    # packing with a dangling gap on the right -- the "missing piece" look
    # from earlier rounds -- at every column count, not just 3.
    return html.Div(panels, style={"display": "flex", "flexWrap": "wrap",
                                   "justifyContent": "center", "alignItems": "flex-start",
                                   "rowGap": "24px", "columnGap": "20px"})
