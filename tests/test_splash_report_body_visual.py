"""Building the Engine's body visual (app.dashboards.splash_report.body_visual):
pure-function SVG dot coloring/mirroring, no DB access."""
from __future__ import annotations

from app.dashboards.splash_report import body_visual


def _records(**flags):
    """{"IR": "red", "Grip": "yellow", ...} -> engine_records shaped like
    app.data.splash_report.read_engine_metrics's output."""
    return [{"metric_key": k, "now_value": 40, "flag": v, "d1_baseline": 50}
           for k, v in flags.items()]


def test_render_is_safe_with_no_data_at_all():
    out = body_visual.render([], None)
    s = str(out)
    assert "data:image/svg+xml" in s
    assert "IR:" in s  # legend always lists every metric, even with nothing recorded


def test_flag_colors_appear_in_the_generated_svg():
    out = str(body_visual.render(_records(IR="red", Grip="yellow"), "Right"))
    assert body_visual._FLAG_COLOR["red"] in out
    assert body_visual._FLAG_COLOR["yellow"] in out
    assert body_visual._FLAG_COLOR[None] in out  # every other metric has no flag yet


def test_unknown_or_missing_throws_defaults_to_right_handed_side():
    right = str(body_visual.render(_records(IR="red"), "Right"))
    default = str(body_visual.render(_records(IR="red"), None))
    assert right == default


def test_left_handed_mirrors_the_marker_positions():
    right = str(body_visual.render(_records(IR="red"), "Right"))
    left = str(body_visual.render(_records(IR="red"), "Left"))
    assert right != left  # dot x-coordinates differ once mirrored
    # same legend either way -- only the SVG marker positions change
    assert "IR:" in right and "IR:" in left
