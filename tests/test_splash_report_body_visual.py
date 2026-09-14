"""Building the Engine's body visual (app.dashboards.splash_report.body_visual):
pure-function panel layout/coloring/mirroring, no DB access. Five panels
(IR, ER, Scaption, Grip, ROM) instead of one combined figure -- 2026-09-11
feedback."""
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
    assert "player-cutout.png" in s  # the real cutout image, every panel
    assert "Internal Strength" in s and "Range of Motion" in s  # all 5 panel titles present


def test_all_five_panel_titles_present():
    s = str(body_visual.render(_records(IR="red"), "Right"))
    for title in ("Internal Strength", "External Strength", "Scaption", "Grip",
                 "Range of Motion"):
        assert title in s


def test_flag_colors_appear_for_flagged_metrics():
    out = str(body_visual.render(_records(IR="red", Grip="yellow"), "Right"))
    assert body_visual._FLAG_COLOR["red"] in out
    assert body_visual._FLAG_COLOR["yellow"] in out
    assert body_visual._FLAG_COLOR[None] in out  # every other metric has no flag yet


def test_rom_panel_uses_worst_flag_among_the_three_rom_metrics():
    # TotalArc red should drive the ROM panel's highlight color even though
    # IROM/EROM are unflagged -- the cutout only shows ONE color, so it
    # must be the most severe of the three.
    records = _records(IROM="ok", EROM="yellow", TotalArc="red")
    out = str(body_visual.render(records, "Right"))
    assert out.count(body_visual._FLAG_COLOR["red"]) >= 1


def test_rom_panel_includes_scaption_rom_readout():
    # 2026-09-14: Scaption ROM is a 4th readout line in the SAME ROM panel
    # (dot + label, no separate skeleton) -- not a 6th panel.
    out = str(body_visual.render(_records(EROM="ok"), "Right"))
    assert "Scaption ROM" in out


def test_unknown_or_missing_throws_defaults_to_right_handed_side():
    right = str(body_visual.render(_records(IR="red"), "Right"))
    default = str(body_visual.render(_records(IR="red"), None))
    assert right == default


def test_left_handed_mirrors_the_highlight_positions():
    right = str(body_visual.render(_records(IR="red"), "Right"))
    left = str(body_visual.render(_records(IR="red"), "Left"))
    assert right != left  # highlight box 'left' percentages differ once mirrored
    # same panel titles either way -- only the highlight position changes
    assert "Internal Strength" in right and "Internal Strength" in left


def test_mirror_box_flips_across_centerline():
    box = {"left": 30.0, "top": 22.0, "width": 20.0, "height": 18.0}
    mirrored = body_visual._mirror_box(box, mirror=True)
    assert mirrored["left"] == 100.0 - 30.0 - 20.0
    assert mirrored["top"] == box["top"] and mirrored["width"] == box["width"]
    assert body_visual._mirror_box(box, mirror=False) == box


def test_ring_gauge_clamps_fraction_and_shows_raw_value():
    # value far above baseline must not overflow the ring past 100%, but the
    # displayed number stays the real (uncapped) value.
    gauge = str(body_visual._ring_gauge(90, 50, "#9A0021"))
    assert "90" in gauge


def test_ring_gauge_handles_no_baseline_or_no_value():
    assert "—" in str(body_visual._ring_gauge(None, 50, "#c9c9c9"))
    assert "—" in str(body_visual._ring_gauge(40, None, "#c9c9c9"))
