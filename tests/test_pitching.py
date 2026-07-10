import pandas as pd
import pytest

from app.data import pitching as P

GAME_ID = 166
PITCHER_ID = 1


def test_game_pitches_returns_rows_for_known_outing():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert (df["pitcher_id"] == PITCHER_ID).all()
    assert (df["game_id"] == GAME_ID).all()


def test_game_context_has_score_and_teams():
    ctx = P.game_context(GAME_ID)
    assert ctx["home_team"] and ctx["away_team"]
    assert ctx["lmu_runs"] >= 0 and ctx["opp_runs"] >= 0
    assert isinstance(ctx["lmu_is_home"], bool)


def test_recent_outings_capped_and_ordered():
    df = P.recent_outings(PITCHER_ID, GAME_ID, n=5)
    assert 1 <= len(df) <= 5
    dates = pd.to_datetime(df["game_date"])
    assert list(dates) == sorted(dates, reverse=True)


def test_pitch_type_prefers_tagged():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    pt = P.pitch_type(df)
    assert pt.notna().all()


def test_pitcher_tm_id_resolves():
    assert P.pitcher_tm_id_for(PITCHER_ID) is not None
