"""UI wiring for the pitcher development visuals.

Companion to ``tests/test_pitcher_development.py`` (which covers the data
layer). Everything here monkeypatches ``app.data.pitcher_development`` so the
tests are fast, deterministic and never touch the live warehouse -- the point
is the RENDERING decisions (which figures get built, which delta reads as an
improvement, whether the year-over-year panel appears at all), not the numbers.

The test that matters most is ``test_delta_polarity_is_per_metric``: a rising
BB% or Barrel% is a REGRESSION even though the number went up, and colouring it
green would quietly tell a pitcher that walking more batters is progress.
"""
import pandas as pd
import pytest

from app.data import pitcher_development as PD
from app.dashboards.pitching import layout
from app.dashboards.pitching.tabs import location_movement as LM
from app.dashboards.pitching.tabs import pitch_breakdown

PID = 4242
CUR, PREV = "2025/2026", "2024/2025"


# ------------------------------ helpers -----------------------------------

def _walk(node):
    """Every component in a Dash tree, depth first."""
    yield node
    kids = getattr(node, "children", None)
    if kids is None:
        return
    if not isinstance(kids, (list, tuple)):
        kids = [kids]
    for k in kids:
        yield from _walk(k)


def _figures(tree):
    """Every `dcc.Graph` figure in a rendered tree."""
    return [n.figure for n in _walk(tree) if getattr(n, "figure", None) is not None]


def _fig_titles(tree):
    return [str(f.layout.title.text or "") for f in _figures(tree)]


def _badge_classes(tree):
    """{metric label -> delta-badge className} for the development callout.

    A card is `[label, big value, badge, previous]`, so the badge is the third
    child of any Div whose first child is a plain-string label.
    """
    out = {}
    for node in _walk(tree):
        kids = getattr(node, "children", None)
        if not isinstance(kids, list) or len(kids) < 3:
            continue
        label = getattr(kids[0], "children", None)
        cls = getattr(kids[2], "className", None)
        if isinstance(label, str) and cls:
            out[label] = cls
    return out


def _pitch_df(n=6):
    """A minimal pitch frame carrying every column the breakdown tab reads."""
    return pd.DataFrame({
        "pitch_no": list(range(1, n + 1)),
        "tagged_pitch_type": (["Fastball", "Slider"] * n)[:n],
        "auto_pitch_type": (["Fastball", "Slider"] * n)[:n],
        "rel_speed": [92.0, 84.0, 93.0, 85.0, 91.5, 83.5][:n],
        "spin_rate": [2200, 2400, 2250, 2380, 2190, 2410][:n],
        "induced_vert_break": [16.0, 2.0, 15.0, 1.0, 17.0, 3.0][:n],
        "horz_break": [10.0, -6.0, 11.0, -7.0, 9.0, -5.0][:n],
        "rel_height": [5.9, 5.8, 6.0, 5.85, 5.95, 5.75][:n],
        "rel_side": [1.8, 1.7, 1.85, 1.75, 1.9, 1.65][:n],
        "extension": [6.2, 6.0, 6.3, 6.1, 6.25, 6.05][:n],
        "balls": [0, 1, 2, 0, 1, 3][:n],
        "strikes": [0, 2, 1, 1, 2, 0][:n],
        "plate_loc_side": [0.1, -0.3, 0.2, -0.1, 0.0, 0.4][:n],
        "plate_loc_height": [2.5, 3.0, 2.2, 2.8, 3.1, 2.0][:n],
        "pitch_call": ["StrikeCalled", "BallCalled"] * (n // 2),
        "batter_side": ["Right", "Left"] * (n // 2),
    })


def _movement_df(hb, ivb):
    return pd.DataFrame({
        "horz_break": list(hb), "induced_vert_break": list(ivb),
        "tagged_pitch_type": ["Fastball"] * len(hb),
        "auto_pitch_type": ["Fastball"] * len(hb),
    })


def _comparison(current, previous=None):
    """Build the `season_comparison` shape, mirroring the data layer's rule
    that a metric missing on either side is ABSENT from `deltas`."""
    deltas = {}
    if previous:
        for m in PD.DELTA_METRICS:
            if current.get(m) is not None and previous.get(m) is not None:
                deltas[m] = current[m] - previous[m]
    return {"current": dict(current, label=CUR),
            "previous": dict(previous, label=PREV) if previous else None,
            "deltas": deltas}


# ------------------- 1. homepage movement + release ------------------------

def test_breakdown_tab_renders_movement_and_release():
    titles = _fig_titles(pitch_breakdown.render(_pitch_df()))
    assert "Pitch Movement" in titles
    assert "Release Point" in titles


def test_breakdown_chart_pair_stacks_on_narrow_screens():
    """The pair must carry `paw-chart-row` -- that class is the ONLY thing that
    stacks the two scatters on a phone (see shell.py's <=720px media query)."""
    classes = [getattr(n, "className", None) for n in _walk(pitch_breakdown.render(_pitch_df()))]
    assert "paw-chart-row" in classes


# --------------------- 2. sidebar development callout ----------------------

def _install_comparison(monkeypatch, comp):
    monkeypatch.setattr(PD, "season_comparison", lambda pid, season=None: comp)


def test_callout_renders_deltas_when_previous_season_exists(monkeypatch):
    _install_comparison(monkeypatch, _comparison(
        {"avg_velo": 91.8, "max_velo": 95.0, "k_pct": 28.0, "bb_pct": 7.0,
         "barrel_pct": 4.0},
        {"avg_velo": 89.0, "max_velo": 93.0, "k_pct": 20.0, "bb_pct": 11.0,
         "barrel_pct": 9.0}))
    tree = layout.development_callout(PID, CUR)
    text = str(tree)
    for label in ("Avg Velo", "Max Velo", "K%", "BB%", "Barrel%"):
        assert label in text
    assert "+2.8" in text          # avg velo delta
    assert "91.8" in text          # current value
    assert "89.0" in text          # previous value, muted row
    assert "▲" in text and "▼" in text


def test_delta_polarity_is_per_metric(monkeypatch):
    """THE test. Every metric moves UP by the same amount; velo/K% must read as
    improvements and BB%/Barrel% as regressions. Colouring by the raw sign
    would tell a pitcher that walking more batters is progress."""
    _install_comparison(monkeypatch, _comparison(
        {"avg_velo": 92.0, "max_velo": 96.0, "k_pct": 24.0, "bb_pct": 12.0,
         "barrel_pct": 10.0},
        {"avg_velo": 90.0, "max_velo": 94.0, "k_pct": 22.0, "bb_pct": 10.0,
         "barrel_pct": 8.0}))
    got = _badge_classes(layout.development_callout(PID, CUR))
    assert got["Avg Velo"] == layout._BETTER_CLASS
    assert got["Max Velo"] == layout._BETTER_CLASS
    assert got["K%"] == layout._BETTER_CLASS
    assert got["BB%"] == layout._WORSE_CLASS, "a rising BB% is NOT an improvement"
    assert got["Barrel%"] == layout._WORSE_CLASS, "a rising Barrel% is NOT an improvement"


def test_delta_polarity_inverts_when_the_rates_fall(monkeypatch):
    """The mirror image: falling BB%/Barrel% is better, a lost tick of velo and
    a lower K% are worse. Guards against a map that merely hardcodes 'red'."""
    _install_comparison(monkeypatch, _comparison(
        {"avg_velo": 90.0, "max_velo": 94.0, "k_pct": 22.0, "bb_pct": 10.0,
         "barrel_pct": 8.0},
        {"avg_velo": 92.0, "max_velo": 96.0, "k_pct": 24.0, "bb_pct": 12.0,
         "barrel_pct": 10.0}))
    got = _badge_classes(layout.development_callout(PID, CUR))
    assert got["Avg Velo"] == layout._WORSE_CLASS
    assert got["K%"] == layout._WORSE_CLASS
    assert got["BB%"] == layout._BETTER_CLASS
    assert got["Barrel%"] == layout._BETTER_CLASS


def test_callout_first_year_pitcher_has_no_arrows(monkeypatch):
    """`previous=None` -> current values only. No arrows, no previous row, and
    no 'N/A' apology text."""
    _install_comparison(monkeypatch, _comparison(
        {"avg_velo": 90.5, "max_velo": 94.2, "k_pct": 19.0, "bb_pct": 9.0,
         "barrel_pct": 6.0}))
    tree = layout.development_callout(PID, CUR)
    text = str(tree)
    assert "90.5" in text                       # still shows this season
    assert "▲" not in text and "▼" not in text  # ...with no comparison arrows
    assert "N/A" not in text and PREV not in text
    assert _badge_classes(tree) == {}


def test_callout_skips_a_metric_missing_on_one_side(monkeypatch):
    """A metric absent from `deltas` renders its current value with no arrow --
    the data layer omits the key rather than returning None for it."""
    _install_comparison(monkeypatch, _comparison(
        {"avg_velo": 91.0, "max_velo": None, "k_pct": 25.0, "bb_pct": 8.0,
         "barrel_pct": 5.0},
        {"avg_velo": 90.0, "max_velo": 93.0, "k_pct": 21.0, "bb_pct": 9.0,
         "barrel_pct": 5.0}))
    got = _badge_classes(layout.development_callout(PID, CUR))
    assert "Max Velo" not in got                 # no current value -> no card
    assert got["Avg Velo"] == layout._BETTER_CLASS
    assert got["Barrel%"] == layout._FLAT_CLASS  # unchanged -> neither colour


def test_sidebar_includes_the_callout_under_the_tiles(monkeypatch):
    """End to end through `sidebar()`: the tiles stay, the callout lands below
    them, and the optional `season` argument is what the callout is scoped to."""
    from app.data import pitching_caps
    monkeypatch.setattr(pitching_caps, "pitcher_profile",
                        lambda p: {"name": "Doe, John", "class_year": "Jr.",
                                   "position": "RHP", "throws": "R",
                                   "jersey": "21", "photo": ""})
    monkeypatch.setattr(pitching_caps, "range_summary",
                        lambda p, *a, **k: {"appearances": 12, "ip": "30.1",
                                            "k_pct": "28.0%", "bb_pct": "7.0%",
                                            "barrel_pct": "4.0%"})
    seen = {}

    def fake(pid, season=None):
        seen["season"] = season
        return _comparison(
            {"avg_velo": 91.8, "max_velo": 95.0, "k_pct": 28.0, "bb_pct": 7.0,
             "barrel_pct": 4.0},
            {"avg_velo": 89.0, "max_velo": 93.0, "k_pct": 20.0, "bb_pct": 11.0,
             "barrel_pct": 9.0})

    monkeypatch.setattr(PD, "season_comparison", fake)
    text = str(layout.sidebar(PID, "2025-09-01", "2026-05-13", CUR))
    for label in ("APP", "IP", "K%", "BB%", "Barrel%"):     # tiles untouched
        assert label in text
    assert "Development" in text and "+2.8" in text
    assert seen["season"] == CUR                            # season threaded through


def test_sidebar_defaults_season_when_not_passed(monkeypatch):
    """The pre-existing 3-arg signature keeps working and falls back to the
    current season rather than passing None down."""
    from app.data import pitching_caps, seasons
    monkeypatch.setattr(seasons, "current_season", lambda: CUR)
    monkeypatch.setattr(pitching_caps, "pitcher_profile",
                        lambda p: {"name": "Doe, John", "class_year": "", "position": "",
                                   "throws": "", "jersey": "", "photo": ""})
    monkeypatch.setattr(pitching_caps, "range_summary",
                        lambda p, *a, **k: {"appearances": 0, "ip": 0, "k_pct": "—",
                                            "bb_pct": "—", "barrel_pct": "—"})
    seen = {}

    def fake(pid, season=None):
        seen["season"] = season
        return _comparison({"avg_velo": 90.0, "max_velo": 94.0, "k_pct": None,
                            "bb_pct": None, "barrel_pct": None})

    monkeypatch.setattr(PD, "season_comparison", fake)
    assert layout.sidebar(PID, "2025-09-01", "2026-05-13") is not None
    assert seen["season"] == CUR


# ------------------ 3. year-over-year movement comparison ------------------

def _install_seasons(monkeypatch, prev_label, frames):
    monkeypatch.setattr(PD, "previous_season_with_data",
                        lambda pid, season: prev_label)
    monkeypatch.setattr(PD, "season_movement",
                        lambda pid, season: frames.get(season, pd.DataFrame()))


def test_yoy_panel_absent_for_a_first_year_pitcher(monkeypatch):
    _install_seasons(monkeypatch, None, {})
    assert LM.yoy_movement(PID, CUR) is None
    tree = LM.render(_pitch_df(), PID, CUR)
    assert "Year Over Year Movement" not in str(tree)
    # ...and only the single-season movement + location pair is drawn.
    assert [t for t in _fig_titles(tree) if t.startswith("Movement · ")] == []
    assert _fig_titles(tree)[0] == "Pitch Movement"


def test_yoy_panel_present_for_a_returning_pitcher(monkeypatch):
    _install_seasons(monkeypatch, PREV, {
        PREV: _movement_df([-4.0, -2.0], [8.0, 12.0]),
        CUR: _movement_df([6.0, 14.0], [16.0, 20.0]),
    })
    tree = LM.render(_pitch_df(), PID, CUR)
    text = str(tree)
    assert "Year Over Year Movement" in text
    assert PREV in text and CUR in text
    titles = _fig_titles(tree)
    # previous season LEFT, current RIGHT (after the single-season pair)
    assert titles[-2:] == [f"Movement · {PREV}", f"Movement · {CUR}"]


def test_yoy_plots_share_identical_axis_ranges(monkeypatch):
    """Without a shared range each panel autoranges to its own data and the
    tighter season looks like it moved MORE -- the comparison becomes a lie."""
    _install_seasons(monkeypatch, PREV, {
        PREV: _movement_df([-4.0, -2.0], [8.0, 12.0]),
        CUR: _movement_df([6.0, 14.0], [16.0, 20.0]),
    })
    left, right = _figures(LM.yoy_movement(PID, CUR))
    assert left.layout.xaxis.range == right.layout.xaxis.range
    assert left.layout.yaxis.range == right.layout.yaxis.range
    # ...and that shared range is the UNION of both seasons, not one of them.
    assert left.layout.xaxis.range == (-4.0 - LM._YOY_PAD, 14.0 + LM._YOY_PAD)
    assert left.layout.yaxis.range == (8.0 - LM._YOY_PAD, 20.0 + LM._YOY_PAD)


def test_yoy_panel_survives_an_empty_previous_season(monkeypatch):
    """`previous_season_with_data` said there ARE pitches, but the frame comes
    back without break columns -- render the pair anyway rather than raising."""
    _install_seasons(monkeypatch, PREV, {
        PREV: pd.DataFrame({"horz_break": [], "induced_vert_break": [],
                            "tagged_pitch_type": [], "auto_pitch_type": []}),
        CUR: _movement_df([6.0, 14.0], [16.0, 20.0]),
    })
    panel = LM.yoy_movement(PID, CUR)
    assert panel is not None
    left, right = _figures(panel)
    assert left.layout.xaxis.range == right.layout.xaxis.range


def test_yoy_needs_both_a_pitcher_and_a_season():
    assert LM.yoy_movement(None, CUR) is None
    assert LM.yoy_movement(PID, None) is None


def test_location_tab_still_renders_without_ids():
    """The old single-arg call site keeps working -- just no YoY panel."""
    tree = LM.render(_pitch_df())
    assert tree is not None
    assert "Year Over Year Movement" not in str(tree)


def test_callbacks_thread_pitcher_and_season_into_the_location_tab():
    import inspect
    from app.dashboards.pitching import callbacks
    src = inspect.getsource(callbacks.register_callbacks)
    assert 'location_movement.render(df, sel.get("pitcher_id"),' in src
    assert 'Input("pit-season", "value")' in src and "def _on_sidebar(pitcher_id, start, end, season)" in src
