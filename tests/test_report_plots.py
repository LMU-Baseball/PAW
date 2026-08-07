import base64
import matplotlib.pyplot as plt
from app.data import pitching_caps as PC
from app.reports import plots


def _df():
    return PC.game_pitches(166, 1000365469)


def _is_png_uri(uri):
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_zone_chart_returns_png():
    _is_png_uri(plots.zone_chart_uri(_df(), "Right", "vRHH Zone"))


def test_movement_map_returns_png():
    _is_png_uri(plots.movement_map_uri(_df()))


def test_movement_map_has_light_gridlines_behind_data(monkeypatch):
    """Gridlines should aid reading the movement map, drawn behind the points."""
    import pandas as pd

    df = pd.DataFrame({
        "horz_break": [5.0, -3.0, 8.0],
        "induced_vert_break": [12.0, 15.0, 9.0],
        "tagged_pitch_type": ["Fastball", "Slider", "Fastball"],
        "auto_pitch_type": ["Fastball", "Slider", "Fastball"],
        "rel_speed": [92.0, 84.0, 91.5],
    })

    captured = {}
    orig_subplots = plt.subplots

    def spy_subplots(*a, **k):
        fig, ax = orig_subplots(*a, **k)
        captured["ax"] = ax
        return fig, ax

    monkeypatch.setattr(plt, "subplots", spy_subplots)
    _is_png_uri(plots.movement_map_uri(df))

    ax = captured["ax"]
    assert ax.get_axisbelow() is True
    gridlines = list(ax.xaxis.get_gridlines()) + list(ax.yaxis.get_gridlines())
    assert gridlines
    assert all(gl.get_visible() for gl in gridlines)


def test_plots_empty_input_safe():
    empty = _df().iloc[0:0]
    _is_png_uri(plots.zone_chart_uri(empty, "Left", "vLHH Zone"))
    _is_png_uri(plots.movement_map_uri(empty))


def test_contact_classes_mapping():
    import pandas as pd
    df = pd.DataFrame({
        "pitch_call": ["StrikeSwinging", "InPlay", "InPlay", "BallCalled"],
        "exit_speed": [None, 97.0, 80.0, None]})
    cc = list(plots._contact_classes(df))
    assert cc[0] == "Whiff"
    assert cc[1] == "Barrel"     # InPlay & 95+
    assert cc[2] == "In Play"    # InPlay & <95
    assert pd.isna(cc[3])        # take -> plain dot


def test_pitch_usage_donuts_returns_png():
    _is_png_uri(plots.pitch_usage_donuts_uri(_df()))


def test_pitch_usage_donuts_empty_safe():
    _is_png_uri(plots.pitch_usage_donuts_uri(_df().iloc[0:0]))


def test_pitch_colors_stable_per_name():
    assert plots._color_for("Fastball") == plots._color_for("Fastball")
    # an unknown name is deterministic across calls
    assert plots._color_for("Gyroball") == plots._color_for("Gyroball")


def test_pitch_freq_bar_uri():
    uri = plots.pitch_freq_bar_uri([("Fastball", 6), ("Slider", 3), ("ChangeUp", 2)])
    assert uri.startswith("data:image/png")
    assert plots.pitch_freq_bar_uri([]).startswith("data:image/png")
