"""CAPS pitching data-access tests.

This file used to hold warehouse-vs-CAPS *parity* tests (each comparing the
``app.data.pitching`` warehouse oracle against ``app.data.pitching_caps``).
The warehouse oracle query functions were removed in the Phase-3 warehouse
drop, so every oracle-comparison test was deleted; what remains here are the
standalone CAPS regression tests that exercise ``pitching_caps`` directly
against the live ``GAMES`` table.
"""
import pandas as pd
import pytest

from app.db import query_df
from app.data import pitching_caps

# Behrens, Adam: raw trackman id 823008, game_id 315 (2026-05-15, LMU @ USD).
RAW_PID = 823008
GAME_ID = 315


def test_sibling_pitcher_ids_includes_raw_id():
    ids = pitching_caps._sibling_pitcher_ids(RAW_PID)
    assert RAW_PID in ids


def test_game_context_derives_season_label_format():
    ctx = pitching_caps.game_context(GAME_ID)
    # GAMES has no season_label column; caps derives "Spring 2026"/"Fall 2025"
    # from Date using the same Jan-Jun/Jul-Dec split as
    # app.dashboards.date_range.season_block. Game 315 is 2026-05-15.
    assert ctx["season_label"] == "Spring 2026"


# --------------------------- velo views -----------------------------------

def test_recent_outings_team_names_from_games():
    new = pitching_caps.recent_outings(RAW_PID, GAME_ID)
    assert (new["home_team_name"].str.len() > 0).all()
    assert (new["away_team_name"].str.len() > 0).all()


def test_recent_outings_empty_for_unknown_pitcher():
    df = pitching_caps.recent_outings(999999999, GAME_ID)
    assert df.empty
    assert list(df.columns) == [
        "game_id", "game_date", "season_label", "game_type",
        "home_team_name", "away_team_name", "appearance_avg_velo",
        "appearance_max_velo", "appearance_min_velo", "pitch_count",
    ]


def test_velo_trend_chronological_order():
    new = pitching_caps.velo_trend(RAW_PID)
    dates = list(new["game_date"].astype(str))
    assert dates == sorted(dates)


def test_velo_trend_empty_for_unknown_pitcher():
    df = pitching_caps.velo_trend(999999999)
    assert df.empty
    assert list(df.columns) == ["game_date", "avg_velo", "max_velo", "pitch_count", "velo_change"]


def test_report_data_version_none_for_unknown_pitcher():
    assert pitching_caps.report_data_version(999999999) == "none"


# --------------------------- identity + roster -----------------------------

def test_pitcher_name_unknown_id_placeholder():
    assert pitching_caps.pitcher_name(999999999) == "Pitcher 999999999"


def test_pitcher_tm_id_for_is_identity():
    assert pitching_caps.pitcher_tm_id_for(RAW_PID) == RAW_PID


def test_lmu_pitchers_columns():
    df = pitching_caps.lmu_pitchers()
    assert list(df.columns) == ["PitcherId", "Pitcher"]


def test_lmu_pitchers_all_have_numeric_game_id_rows():
    # No-ghost property (mirrors catching_caps/hitting_caps's regression):
    # lmu_pitchers used to scope purely by the date-only _RECENT_WINDOW_CLAUSE,
    # so a pitcher whose only in-window games carried legacy composite-string
    # GameIDs would be listed while every numeric-GameID-guarded data function
    # (games_for_pitcher, season_summary, range_summary, velo views) returned
    # empty for them. Checked as a single SQL set-membership query rather than
    # N per-id round trips.
    ids = set(pitching_caps.lmu_pitchers()["PitcherId"].astype(int))
    current_ids = set(query_df(
        "SELECT DISTINCT PitcherId FROM GAMES "
        "WHERE PitcherTeam = :t AND PitcherId IS NOT NULL "
        f"AND {pitching_caps._NUMERIC_GAME_ID_CLAUSE}",
        {"t": pitching_caps.LMU_PITCHER_TEAM},
    )["PitcherId"].astype(int))
    assert ids <= current_ids


def test_report_data_version_present():
    assert hasattr(pitching_caps, "report_data_version")
    assert pitching_caps.report_data_version(RAW_PID) != "none"
