"""Transforms feeding the one-page pitcher report. Fixture: game 166, pitcher 1
(live warehouse). Value assertions check invariants/ranges; the LMU-specific
metrics (ea/pre2k/twok_kill/barrel) are provisional so they're only range-checked."""
import pandas as pd
from app.data import pitching as P

GAME_ID, PITCHER_ID = 166, 1


def _df():
    return P.game_pitches(GAME_ID, PITCHER_ID)


def test_pa_count_matches_distinct_inning_pa():
    df = _df()
    expected = df[["inning", "pa_of_inning"]].drop_duplicates().shape[0]
    assert P._pa_count(df) == expected
    assert P._pa_count(df.iloc[0:0]) == 0


def test_header_stat_line_shape_and_values():
    h = P.header_stat_line(_df())
    assert set(h) == {"bf", "bf_r", "bf_l", "outs", "h", "r", "bb", "so", "pitches"}
    df = _df()
    assert h["pitches"] == len(df)
    assert h["bf_r"] + h["bf_l"] == h["bf"]
    assert h["h"] == int(df["play_result"].isin(
        {"Single", "Double", "Triple", "HomeRun"}).sum())
    assert h["so"] == int((df["korbb"] == "Strikeout").sum())
    assert all(isinstance(v, int) for v in h.values())


def test_header_stat_line_empty_safe():
    h = P.header_stat_line(_df().iloc[0:0])
    assert h == {k: 0 for k in h}


def test_strike_and_fps_pct_consistent():
    df = _df()
    pct, cnt = P.strike_pct(df)
    assert cnt == int(df["pitch_call"].isin(P._STRIKE_CALLS).sum())
    assert 0 <= pct <= 100
    fpct, fcnt = P.fps_pct(df)
    assert 0 <= fpct <= 100 and fcnt >= 0


def test_k_bb_pct_use_pa_denominator():
    df = _df()
    pas = P._pa_count(df)
    kpct, kcnt = P.k_pct(df)
    assert kcnt == int((df["korbb"] == "Strikeout").sum())
    assert kpct == (round(100.0 * kcnt / pas, 1) if pas else 0.0)


def test_provisional_metrics_in_range_and_empty_safe():
    df = _df()
    for fn in (P.ea_pct, P.pre2k_pct, P.twok_kill_pct, P.barrel_pct):
        pct, cnt = fn(df)
        assert 0 <= pct <= 100 and cnt >= 0
        epct, ecnt = fn(df.iloc[0:0])
        assert epct == 0.0 and ecnt == 0
