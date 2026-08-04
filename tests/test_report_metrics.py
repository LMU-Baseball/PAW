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
    assert set(h) == {"bf", "bf_r", "bf_l", "outs", "h", "r", "bb", "so",
                       "pitches", "strike_pct", "max_velo"}
    df = _df()
    assert h["pitches"] == len(df)
    assert h["bf_r"] + h["bf_l"] == h["bf"]
    assert h["h"] == int(df["play_result"].isin(
        {"Single", "Double", "Triple", "HomeRun"}).sum())
    assert h["so"] == int((df["korbb"] == "Strikeout").sum())
    int_keys = {"bf", "bf_r", "bf_l", "outs", "h", "r", "bb", "so", "pitches"}
    assert all(isinstance(h[k], int) for k in int_keys)
    assert 0 <= h["strike_pct"] <= 100
    assert h["max_velo"] is None or isinstance(h["max_velo"], float)


def test_header_stat_line_empty_safe():
    h = P.header_stat_line(_df().iloc[0:0])
    assert h == {k: (None if k == "max_velo" else 0) for k in h}


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


def test_process_and_outcome_metric_rows():
    df = _df()
    proc = P.process_metrics(df)
    assert [r["key"] for r in proc] == [
        "strike_pct", "fps_pct", "ea_pct", "pre2k_pct", "twok_kill_pct"]
    for r in proc:
        assert set(r) >= {"metric", "key", "value_pct", "value_count", "vrhh", "vlhh"}
        assert 0 <= r["value_pct"] <= 100
    out = P.outcome_metrics(df)
    assert [r["key"] for r in out] == ["k_pct", "bb_pct", "barrel_pct"]


def test_pitch_usage_table_usage_sums_to_100():
    rows = P.pitch_usage_table(_df())
    assert len(rows) >= 1
    assert abs(sum(r["usage_pct"] for r in rows) - 100.0) < 0.5
    assert rows == sorted(rows, key=lambda r: r["usage_pct"], reverse=True)
    for r in rows:
        assert set(r) >= {"pitch", "strike_pct", "usage_pct", "twok_usage_pct",
                          "vrhh", "vlhh"}


def test_movement_summary_shape():
    rows = P.movement_summary(_df())
    assert len(rows) >= 1
    for r in rows:
        assert set(r) >= {"pitch", "velo_avg", "velo_max", "ivb_avg", "ivb_rhh",
                          "ivb_lhh", "hb_avg", "hb_rhh", "hb_lhh", "vaa"}
        assert "spread" not in r
        assert r["velo_max"] is None or r["velo_avg"] is None or \
            r["velo_max"] >= r["velo_avg"]


def test_table_assemblers_empty_safe():
    empty = _df().iloc[0:0]
    assert P.process_metrics(empty) and P.outcome_metrics(empty)  # rows still present
    assert P.pitch_usage_table(empty) == []
    assert P.movement_summary(empty) == []
