"""Building the Engine's body visual: a simple Da Vinci-style (Vitruvian
Man) line-art figure with the 7 engine metrics marked at their real
anatomical spot -- a cluster of 6 dots at the throwing shoulder (IR/ER/
Scaption/IROM/EROM/TotalArc all measure the same joint) and one dot at the
throwing hand (Grip). Each dot is colored by that metric's flag (see
`app.data.splash_report.engine_flag`) so a coach reads weak spots directly
off the figure instead of only the Base/Now table.

Built as a single inline SVG embedded via a `data:image/svg+xml` URI on an
`html.Img` -- the same idiom `app.dashboards.velo_board.visual.
top_gun_header` uses for its banner, since this Dash version (4.4.1) has no
SVG components in `dash.html` to build one natively. A static image can't
carry hover tooltips reliably (and never on a phone), so a small color-
keyed legend renders underneath with the same information as plain text.
"""
from __future__ import annotations

import base64

from dash import html

from app.data import splash_report as SR

_LINE = "#4a4a4a"
_FLAG_COLOR = {None: "#c9c9c9", "ok": "#4a8f4a", "yellow": "#d9a400", "red": "#c0193a"}

# (metric_key, offset from the shoulder/hand anchor point) -- six metrics
# fan out in a small arc around the shoulder anchor, Grip sits alone at the
# hand anchor. Offsets are in SVG user units, applied AFTER mirroring for
# a left-handed thrower (see `_anchor_x`).
_SHOULDER_METRICS = ("IR", "ER", "Scaption", "IROM", "EROM", "TotalArc")
_SHOULDER_FAN = [(-14, -10), (0, -16), (14, -10), (-14, 8), (0, 14), (14, 8)]


def _anchor_x(x: float, *, mirror: bool) -> float:
    """Mirror an x-coordinate across the figure's centerline (120) when the
    throwing arm is the LEFT one -- the base figure/markers are drawn for a
    right-handed thrower (throwing side on the viewer's left, x < 120)."""
    return 240 - x if mirror else x


def _dot(cx: float, cy: float, color: str, label: str) -> str:
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="{color}" '
           f'stroke="#fff" stroke-width="1.5"><title>{label}</title></circle>')


def _figure_svg(dots: str) -> str:
    # Outer circle (the Vitruvian roundel) + a plain arms-out/legs-apart
    # stick figure inscribed in it -- a nod to the reference without
    # attempting Da Vinci's double-exposed limbs.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 320">
  <circle cx="120" cy="150" r="108" fill="none" stroke="#d8d8d8" stroke-width="2"/>
  <circle cx="120" cy="52" r="20" fill="none" stroke="{_LINE}" stroke-width="3"/>
  <line x1="120" y1="72" x2="120" y2="185" stroke="{_LINE}" stroke-width="3"/>
  <line x1="120" y1="95" x2="26" y2="60" stroke="{_LINE}" stroke-width="3"/>
  <line x1="120" y1="95" x2="214" y2="60" stroke="{_LINE}" stroke-width="3"/>
  <line x1="120" y1="185" x2="55" y2="295" stroke="{_LINE}" stroke-width="3"/>
  <line x1="120" y1="185" x2="185" y2="295" stroke="{_LINE}" stroke-width="3"/>
  {dots}
</svg>"""


def _svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _legend_row(label: str, flag: str | None, now_value, d1_baseline) -> html.Div:
    color = _FLAG_COLOR.get(flag, _FLAG_COLOR[None])
    value_text = "—" if now_value is None else f"{now_value:g}"
    baseline_text = f" · D1 avg {d1_baseline:g}" if d1_baseline is not None else ""
    return html.Div([
        html.Span(style={"display": "inline-block", "width": "10px", "height": "10px",
                         "borderRadius": "50%", "backgroundColor": color,
                         "marginRight": "6px"}),
        html.Span(f"{label}: {value_text}{baseline_text}", style={"fontSize": "12px"}),
    ], style={"display": "flex", "alignItems": "center", "marginBottom": "2px"})


def render(engine_records: list[dict], throws: str | None) -> html.Div:
    """`engine_records` is `data["engine"]` (see `app.data.splash_report.
    read_engine_metrics`) -- already carries `flag`/`now_value`/
    `d1_baseline` per metric, so no DB access here. `throws` ("Left"/
    "Right"/None) picks which side of the figure the throwing-arm markers
    land on; unknown defaults to the right-handed side."""
    by_key = {r["metric_key"]: r for r in (engine_records or [])}
    mirror = str(throws).strip().lower().startswith("l")

    dots = []
    # Shoulder cluster anchor sits close to the shoulder JOINT (120, 95),
    # 22% of the way down the upper-arm line toward the hand (26, 60) --
    # not the line's midpoint, which reads more like an elbow than a
    # shoulder once the 6-dot fan is drawn around it.
    anchor_x = _anchor_x(120 - 0.22 * (120 - 26), mirror=mirror)
    anchor_y = 95 - 0.22 * (95 - 60)
    for key, (dx, dy) in zip(_SHOULDER_METRICS, _SHOULDER_FAN):
        r = by_key.get(key, {})
        color = _FLAG_COLOR.get(r.get("flag"), _FLAG_COLOR[None])
        now_v = r.get("now_value")
        label = f"{SR.ENGINE_METRIC_LABELS.get(key, key)}: {'—' if now_v is None else now_v}"
        mirrored_dx = -dx if mirror else dx
        dots.append(_dot(anchor_x + mirrored_dx, anchor_y + dy, color, label))

    grip = by_key.get("Grip", {})
    grip_color = _FLAG_COLOR.get(grip.get("flag"), _FLAG_COLOR[None])
    grip_now = grip.get("now_value")
    grip_label = f"Grip: {'—' if grip_now is None else grip_now}"
    hand_x, hand_y = _anchor_x(26, mirror=mirror), 60
    dots.append(_dot(hand_x, hand_y, grip_color, grip_label))

    svg = _figure_svg("\n  ".join(dots))
    img = html.Img(src=_svg_data_uri(svg), alt="Body visual — engine metric zones",
                   style={"width": "100%", "maxWidth": "220px", "display": "block",
                          "margin": "0 auto"})
    legend = html.Div(
        [_legend_row(SR.ENGINE_METRIC_LABELS.get(k, k), by_key.get(k, {}).get("flag"),
                    by_key.get(k, {}).get("now_value"), by_key.get(k, {}).get("d1_baseline"))
         for k in SR.ENGINE_METRIC_KEYS],
        style={"marginTop": "8px"})
    return html.Div([img, legend], style={"textAlign": "center"})
