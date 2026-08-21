"""Season-over-season pitcher development data layer.

Everything here monkeypatches the two underlying reads
(``pitching_caps._season_pitch_df`` and ``pitching_caps._compute_season_rollup``)
plus ``seasons.available_seasons``, so the tests are deterministic and never
touch the live ``GAMES`` table. That matters most for the redshirt-skip case:
the whole point is a season with ZERO rows sitting between two seasons that
have data, and no live fixture pitcher reliably has that shape.
"""
import pandas as pd
import plotly.graph_objects as go
import pytest

from app.data import pitcher_development as D
from app.data import pitching as P
from app.data import pitching_caps, seasons

PID = 4242


def _pitch_rows(pitch_types, speeds):
    """Minimal season pitch frame -- just the columns the velo path reads."""
    return pd.DataFrame({
        "tagged_pitch_type": list(pitch_types),
        "auto_pitch_type": list(pitch_types),
        "rel_speed": list(speeds),
    })


def _install(monkeypatch, seasons_by_label, rollups=None):
    """Point the module's two reads at in-memory dicts keyed by season label.

    ``seasons_by_label`` maps label -> pitch DataFrame (an EMPTY frame means
    "this season exists in GAMES but the pitcher threw nothing in it").
    ``rollups`` maps label -> the display-string dict
    ``_compute_season_rollup`` returns.
    """
    labels = sorted(seasons_by_label, reverse=True)   # newest-first, as live
    monkeypatch.setattr(seasons, "available_seasons", lambda: labels)
    monkeypatch.setattr(
        pitching_caps, "_season_pitch_df",
        lambda pid, season=None: seasons_by_label.get(season, pd.DataFrame()))
    monkeypatch.setattr(
        pitching_caps, "_compute_season_rollup",
        lambda pid, season=None: (rollups or {}).get(season, {}))


# --------------------- previous-season selection ---------------------------

def test_season_comparison_skips_empty_intervening_season(monkeypatch):
    """2024/2025 is a redshirt year (zero pitches) -- the comparison must reach
    back past it to 2023/2024, NOT diff against the empty year."""
    _install(monkeypatch, {
        "2025/2026": _pitch_rows(["Fastball"] * 3, [93.0, 94.0, 95.0]),
        "2024/2025": _pitch_rows([], []),                      # redshirt / injury
        "2023/2024": _pitch_rows(["Fastball"] * 3, [88.0, 89.0, 90.0]),
    }, rollups={
        "2025/2026": {"k_pct": "28.0%", "bb_pct": "7.0%", "barrel_pct": "4.0%"},
        "2023/2024": {"k_pct": "20.0%", "bb_pct": "11.0%", "barrel_pct": "9.0%"},
    })

    out = D.season_comparison(PID, "2025/2026")

    assert out["previous"] is not None
    assert out["previous"]["label"] == "2023/2024"      # skipped 2024/2025
    assert out["current"]["label"] == "2025/2026"
    assert out["deltas"]["avg_velo"] == pytest.approx(5.0)
    assert out["deltas"]["max_velo"] == pytest.approx(5.0)
    assert out["deltas"]["k_pct"] == pytest.approx(8.0)
    assert out["deltas"]["bb_pct"] == pytest.approx(-4.0)   # signed, not polarized
    assert out["deltas"]["barrel_pct"] == pytest.approx(-5.0)


def test_previous_season_with_data_returns_the_label(monkeypatch):
    _install(monkeypatch, {
        "2025/2026": _pitch_rows(["Fastball"], [93.0]),
        "2024/2025": _pitch_rows([], []),
        "2023/2024": _pitch_rows(["Fastball"], [88.0]),
    })
    assert D.previous_season_with_data(PID, "2025/2026") == "2023/2024"


def test_previous_season_ignores_later_seasons(monkeypatch):
    """A season AFTER the requested one must never be picked as 'previous'."""
    _install(monkeypatch, {
        "2025/2026": _pitch_rows(["Fastball"], [95.0]),
        "2024/2025": _pitch_rows(["Fastball"], [90.0]),
    })
    assert D.previous_season_with_data(PID, "2024/2025") is None


def test_first_year_pitcher_has_no_previous_and_no_deltas(monkeypatch):
    _install(monkeypatch, {
        "2025/2026": _pitch_rows(["Fastball"] * 2, [92.0, 94.0]),
        "2024/2025": _pitch_rows([], []),
        "2023/2024": _pitch_rows([], []),
    }, rollups={"2025/2026": {"k_pct": "25.0%", "bb_pct": "8.0%",
                              "barrel_pct": "5.0%"}})

    out = D.season_comparison(PID, "2025/2026")
    assert out["previous"] is None
    assert out["deltas"] == {}
    assert out["current"]["max_velo"] == pytest.approx(94.0)


def test_season_defaults_to_current_season(monkeypatch):
    _install(monkeypatch, {"2025/2026": _pitch_rows(["Fastball"], [93.0])})
    monkeypatch.setattr(seasons, "current_season", lambda: "2025/2026")
    assert D.season_comparison(PID)["current"]["label"] == "2025/2026"


# ------------------------------ None-safety --------------------------------

def test_deltas_skip_metrics_missing_on_one_side(monkeypatch):
    """Previous season has no tracked velo and an em-dash barrel tile; those
    metrics get NO delta entry, while the ones present on both sides still do."""
    _install(monkeypatch, {
        "2025/2026": _pitch_rows(["Fastball"] * 2, [93.0, 95.0]),
        "2024/2025": _pitch_rows(["Curveball"], [78.0]),   # no Fastball/Sinker
    }, rollups={
        "2025/2026": {"k_pct": "30.0%", "bb_pct": "6.0%", "barrel_pct": "3.0%"},
        "2024/2025": {"k_pct": "22.0%", "bb_pct": None, "barrel_pct": "—"},
    })

    out = D.season_comparison(PID, "2025/2026")
    assert out["previous"]["avg_velo"] is None
    assert out["previous"]["barrel_pct"] is None
    assert "avg_velo" not in out["deltas"]        # missing previous -> no delta
    assert "max_velo" not in out["deltas"]
    assert "bb_pct" not in out["deltas"]          # None tile -> no delta
    assert "barrel_pct" not in out["deltas"]      # em-dash tile -> no delta
    assert out["deltas"]["k_pct"] == pytest.approx(8.0)


def test_empty_previous_season_metrics_collapse_to_no_comparison(monkeypatch):
    """A prior season with pitches but nothing measurable is not a comparison."""
    _install(monkeypatch, {
        "2025/2026": _pitch_rows(["Fastball"], [93.0]),
        "2024/2025": _pitch_rows(["Curveball"], [None]),
    }, rollups={"2025/2026": {"k_pct": "30.0%"},
                "2024/2025": {"k_pct": "—", "bb_pct": "—", "barrel_pct": "—"}})
    out = D.season_comparison(PID, "2025/2026")
    assert out["previous"] is None
    assert out["deltas"] == {}


def test_missing_rollup_keys_do_not_raise(monkeypatch):
    _install(monkeypatch, {"2025/2026": _pitch_rows(["Fastball"], [91.0])},
             rollups={"2025/2026": {}})
    out = D.season_comparison(PID, "2025/2026")
    assert out["current"]["k_pct"] is None
    assert out["current"]["avg_velo"] == pytest.approx(91.0)


# -------------------------------- velo -------------------------------------

def test_velo_restricted_to_fastball_and_sinker(monkeypatch):
    """A 99 mph Curveball must not become max_velo -- velo is Fastball/Sinker
    rel_speed only, matching velo_board / _pitcher_velo_appearances."""
    _install(monkeypatch, {"2025/2026": _pitch_rows(
        ["Fastball", "Sinker", "Curveball", "Slider"],
        [92.0, 90.0, 99.0, 84.0])})

    cur = D.season_comparison(PID, "2025/2026")["current"]
    assert cur["max_velo"] == pytest.approx(92.0)     # not the 99 mph curveball
    assert cur["avg_velo"] == pytest.approx(91.0)     # mean of 92 and 90 only


def test_velo_pitch_types_derived_from_velo_board():
    from app.data import velo_board
    assert D.VELO_PITCH_TYPES == ("Fastball", "Sinker")
    # single source of truth: parsed from the board's SQL fragment
    for pt in D.VELO_PITCH_TYPES:
        assert f"'{pt}'" in velo_board._VELO_PITCH_TYPES


def test_velo_is_none_when_no_fastballs(monkeypatch):
    _install(monkeypatch, {"2025/2026": _pitch_rows(["Changeup"], [82.0])})
    cur = D.season_comparison(PID, "2025/2026")["current"]
    assert cur["avg_velo"] is None and cur["max_velo"] is None


# ---------------------------- season_movement -------------------------------

def test_season_movement_returns_empty_dataframe_not_none(monkeypatch):
    _install(monkeypatch, {})   # no season has data
    out = D.season_movement(PID, "2019/2020")
    assert isinstance(out, pd.DataFrame)
    assert out is not None and out.empty


def test_season_movement_handles_a_none_read(monkeypatch):
    monkeypatch.setattr(pitching_caps, "_season_pitch_df",
                        lambda pid, season=None: None)
    out = D.season_movement(PID, "2025/2026")
    assert isinstance(out, pd.DataFrame) and out.empty


def test_season_movement_delegates_to_season_pitch_df(monkeypatch):
    frame = _pitch_rows(["Fastball"], [93.0])
    calls = []

    def fake(pid, season=None):
        calls.append((pid, season))
        return frame

    monkeypatch.setattr(pitching_caps, "_season_pitch_df", fake)
    out = D.season_movement(PID, "2025/2026")
    assert calls == [(PID, "2025/2026")]        # delegated, no new SQL
    assert len(out) == 1


def test_season_movement_feeds_fig_movement(monkeypatch):
    """The frame handed back must go straight into pitching.fig_movement."""
    df = pd.DataFrame({
        "tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
        "auto_pitch_type": ["Fastball", "Fastball", "Slider"],
        "horz_break": [-8.0, -9.0, 10.0],
        "induced_vert_break": [16.0, 17.0, 4.0],
    })
    monkeypatch.setattr(pitching_caps, "_season_pitch_df",
                        lambda pid, season=None: df)
    fig = P.fig_movement(D.season_movement(PID, "2025/2026"))
    assert isinstance(fig, go.Figure)


# ------------------------------ fig_release ---------------------------------

def _release_df():
    pts = ["Fastball", "Fastball", "Fastball", "Slider", "Slider", "Curveball"]
    return pd.DataFrame({
        "tagged_pitch_type": pts,
        "auto_pitch_type": pts,
        "rel_side": [-1.2, -1.1, -1.3, -1.4, -1.25, -1.35],
        "rel_height": [5.8, 5.9, 5.7, 5.6, 5.75, 5.65],
    })


def test_fig_release_one_trace_per_pitch_type():
    fig = P.fig_release(_release_df())
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3                       # Fastball, Slider, Curveball
    assert {t.name for t in fig.data} == {"Fastball", "Slider", "Curveball"}
    assert all(t.mode == "markers" for t in fig.data)
    # markers only -- no covariance ellipses on this plot
    assert not any(getattr(t, "fill", None) == "toself" for t in fig.data)


def test_fig_release_axis_titles_and_hover():
    fig = P.fig_release(_release_df())
    assert fig.layout.xaxis.title.text == "Release Side (ft)"
    assert fig.layout.yaxis.title.text == "Release Height (ft)"
    assert any("Rel Side:" in (t.hovertemplate or "") and
               "Rel Height:" in (t.hovertemplate or "") for t in fig.data)


def test_fig_release_x_axis_symmetric_about_zero():
    """Arm side only reads correctly when 0 (the middle of the rubber) is the
    middle of the panel -- a lefty's cluster must NOT be recentred."""
    fig = P.fig_release(_release_df())
    lo, hi = fig.layout.xaxis.range
    assert lo == pytest.approx(-hi)
    assert hi >= 1.4                       # widest release point is inside
    # ...and the cluster is genuinely off-centre, so this isn't a free pass
    assert _release_df()["rel_side"].mean() < -1.0


def test_fig_release_preserves_aspect_ratio():
    fig = P.fig_release(_release_df())
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1


def test_fig_release_survives_all_nan_frame():
    df = pd.DataFrame({
        "tagged_pitch_type": ["Fastball", "Slider"],
        "auto_pitch_type": ["Fastball", "Slider"],
        "rel_side": [None, None],
        "rel_height": [None, None],
    })
    fig = P.fig_release(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0                    # empty state, no traces
    lo, hi = fig.layout.xaxis.range              # and not a degenerate range
    assert lo < 0 < hi
    assert fig.layout.xaxis.title.text == "Release Side (ft)"


def test_fig_release_empty_frame():
    df = pd.DataFrame({"tagged_pitch_type": [], "auto_pitch_type": [],
                       "rel_side": [], "rel_height": []})
    fig = P.fig_release(df)
    assert isinstance(fig, go.Figure) and len(fig.data) == 0
