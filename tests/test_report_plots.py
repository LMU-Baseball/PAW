import base64
from app.data import pitching as P
from app.reports import plots


def _df():
    return P.game_pitches(166, 1)


def _is_png_uri(uri):
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_zone_chart_returns_png():
    _is_png_uri(plots.zone_chart_uri(_df(), "Right", "vRHH Zone"))


def test_movement_map_returns_png():
    _is_png_uri(plots.movement_map_uri(_df()))


def test_plots_empty_input_safe():
    empty = _df().iloc[0:0]
    _is_png_uri(plots.zone_chart_uri(empty, "Left", "vLHH Zone"))
    _is_png_uri(plots.movement_map_uri(empty))


def test_pitch_colors_stable_per_name():
    assert plots._color_for("Fastball") == plots._color_for("Fastball")
    # an unknown name is deterministic across calls
    assert plots._color_for("Gyroball") == plots._color_for("Gyroball")
