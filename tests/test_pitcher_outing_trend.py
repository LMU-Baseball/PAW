"""Data layer for the pitching dashboard's Outing Trend tab.

Everything here monkeypatches the underlying reads (`pitching_caps.
recent_outings`/`range_pitches_for`, `cauldron.read_scoring`, this module's
own team-pitch queries) so the tests are fast, deterministic, and never touch
the live warehouse -- the point is the COMPOSITION (grouping by date, row
order, baseline fallback, velo bucketing), not re-proving pitching.py's
metric math (already covered by tests/test_pitching.py).
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.data import cauldron
from app.data import pitcher_outing_trend as OT
from app.data import pitching_caps as caps


def _pitches(rows: list[dict]) -> pd.DataFrame:
    """Minimal pitch-level frame with every column METRIC_SPECS' functions
    and the velo grouping read, defaulted so each row only needs to override
    what a specific case cares about."""
    base = {
        "pitch_call": "BallCalled", "pitch_of_pa": 1, "korbb": "Undefined",
        "balls": 0, "strikes": 0, "inning": 1, "pa_of_inning": 1,
        "exit_speed": None, "tagged_hit_type": None,
        "rel_speed": 90.0, "tagged_pitch_type": "Fastball", "auto_pitch_type": "Fastball",
        "game_id": "101",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def test_metric_specs_match_reference_report_order():
    keys = [k for k, _l, _f in OT.METRIC_SPECS]
    labels = [lbl for _k, lbl, _f in OT.METRIC_SPECS]
    assert keys == ["strike_pct", "fps_pct", "pre2k_pct", "ea_pct",
                    "k_pct", "bb_pct", "barrel_pct", "twok_kill_pct"]
    assert labels == ["Strike%", "FPS%", "Pre-2K%", "E&A%",
                       "K%", "BB%", "Barrel%", "2K Kill%"]


def test_cauldron_key_map_omits_pre2k_and_covers_the_rest():
    # pre2k_pct has no cauldron equivalent -- cauldron's own "pre2k_zone" is a
    # different metric -- so it must fall back to the season-average baseline.
    assert "pre2k_pct" not in OT._CAULDRON_KEY
    assert set(OT._CAULDRON_KEY) == {
        "strike_pct", "fps_pct", "ea_pct", "twok_kill_pct",
        "k_pct", "bb_pct", "barrel_pct"}


def test_outing_trend_returns_empty_when_pitcher_id_is_none():
    assert OT.outing_trend(None, "101", 5) == {"rows": [], "velo": {"dates": [], "series": {}}}


def test_outing_trend_needs_at_least_two_outings(monkeypatch):
    monkeypatch.setattr(caps, "recent_outings", lambda *a, **k: pd.DataFrame(
        {"game_id": ["101"], "game_date": ["2026-04-01"]}))
    assert OT.outing_trend(1, "101", 5)["rows"] == []


def test_baselines_prefers_cauldron_threshold_over_season_average(monkeypatch):
    OT._baselines.cache_clear()
    monkeypatch.setattr(cauldron, "read_scoring", lambda: pd.DataFrame(
        {"metric": ["strike_pct"], "threshold": [55.0]}))
    monkeypatch.setattr(OT, "_season_team_baselines",
                        lambda season: {k: -1.0 for k, _l, _f in OT.METRIC_SPECS})
    out = OT._baselines("2099/2100")
    assert out["strike_pct"] == 55.0       # cauldron threshold wins
    assert out["pre2k_pct"] == -1.0        # no cauldron key -> season-average fallback


def test_baselines_falls_back_when_cauldron_table_is_empty(monkeypatch):
    OT._baselines.cache_clear()
    monkeypatch.setattr(cauldron, "read_scoring", lambda: pd.DataFrame())
    monkeypatch.setattr(OT, "_season_team_baselines",
                        lambda season: {k: 42.0 for k, _l, _f in OT.METRIC_SPECS})
    out = OT._baselines("2098/2099")
    assert all(v == 42.0 for v in out.values())


def test_outing_trend_happy_path_groups_by_date_and_orders_rows(monkeypatch):
    OT._baselines.cache_clear()
    outings = pd.DataFrame({
        "game_id": ["102", "101"],  # deliberately reverse-chronological input
        "game_date": ["2026-04-08", "2026-04-01"],
    })
    monkeypatch.setattr(caps, "recent_outings", lambda *a, **k: outings)

    player_df = _pitches([
        {"game_id": "101", "pitch_call": "StrikeCalled"},
        {"game_id": "101", "pitch_call": "BallCalled"},
        {"game_id": "102", "pitch_call": "StrikeCalled"},
        {"game_id": "102", "pitch_call": "StrikeCalled"},
    ])
    monkeypatch.setattr(caps, "range_pitches_for", lambda *a, **k: player_df)

    team_df = _pitches([
        {"game_id": "101", "pitch_call": "BallCalled"},
    ])
    team_df["game_date"] = "2026-04-01"
    monkeypatch.setattr(OT, "_team_pitches_on_dates", lambda dates: team_df)
    monkeypatch.setattr(cauldron, "read_scoring", lambda: pd.DataFrame(
        {"metric": ["strike_pct"], "threshold": [55.0]}))
    monkeypatch.setattr(OT, "_season_team_baselines",
                        lambda season: {k: 0.0 for k, _l, _f in OT.METRIC_SPECS})

    result = OT.outing_trend(1, "102", 5)
    strike_row = next(r for r in result["rows"] if r["key"] == "strike_pct")
    assert strike_row["dates"] == ["2026-04-01", "2026-04-08"]  # chronological, not input order
    assert strike_row["player"] == [50.0, 100.0]  # 1/2 strikes, then 2/2 strikes
    assert strike_row["team"] == [0.0, 0.0]        # team only has a Ball on 04-01; nothing on 04-08
    assert strike_row["baseline"] == 55.0
    assert [r["key"] for r in result["rows"]] == [k for k, _l, _f in OT.METRIC_SPECS]


def test_outing_trend_velo_series_grouped_by_pitch_type_with_gaps(monkeypatch):
    OT._baselines.cache_clear()
    outings = pd.DataFrame({"game_id": ["101", "102"],
                            "game_date": ["2026-04-01", "2026-04-08"]})
    monkeypatch.setattr(caps, "recent_outings", lambda *a, **k: outings)

    player_df = _pitches([
        {"game_id": "101", "rel_speed": 90.0, "tagged_pitch_type": "Fastball"},
        {"game_id": "101", "rel_speed": 92.0, "tagged_pitch_type": "Fastball"},
        {"game_id": "102", "rel_speed": 78.0, "tagged_pitch_type": "Slider"},
    ])
    monkeypatch.setattr(caps, "range_pitches_for", lambda *a, **k: player_df)
    monkeypatch.setattr(OT, "_team_pitches_on_dates", lambda dates: pd.DataFrame())
    monkeypatch.setattr(cauldron, "read_scoring", lambda: pd.DataFrame())
    monkeypatch.setattr(OT, "_season_team_baselines",
                        lambda season: {k: 0.0 for k, _l, _f in OT.METRIC_SPECS})

    result = OT.outing_trend(1, "102", 5)
    velo = result["velo"]
    assert velo["dates"] == ["2026-04-01", "2026-04-08"]
    assert velo["series"]["Fastball"] == [91.0, None]   # avg of 90/92 on 04-01, absent 04-08
    assert velo["series"]["Slider"] == [None, 78.0]
