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
    # Known fixture: game 166 is LMU hosting SMC, so LMU is home.
    assert ctx["home_team"] == "LMU"
    assert ctx["lmu_is_home"] is True


def test_recent_outings_capped_and_ordered():
    df = P.recent_outings(PITCHER_ID, GAME_ID, n=5)
    assert 1 <= len(df) <= 5
    dates = pd.to_datetime(df["game_date"])
    assert list(dates) == sorted(dates, reverse=True)


def test_pitch_type_prefers_tagged():
    """Unit test (no DB): tagged wins, else auto, else 'Undefined'."""
    df = pd.DataFrame(
        {
            "tagged_pitch_type": ["Slider", None, ""],
            "auto_pitch_type": ["Fastball", "Curveball", None],
        }
    )
    pt = P.pitch_type(df)
    assert list(pt) == ["Slider", "Curveball", "Undefined"]


def test_pitcher_tm_id_resolves():
    assert P.pitcher_tm_id_for(PITCHER_ID) is not None


def test_game_overall_line_counts_are_consistent():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    line = P.game_overall_line(df)
    assert line["pitches"] == len(df)
    assert 0 <= line["strike_pct"] <= 100
    assert line["strikes"] + line["balls"] <= line["pitches"]


def test_game_overall_line_empty_df_no_divide_by_zero():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    line = P.game_overall_line(df.iloc[0:0])
    assert line["pitches"] == 0
    assert line["strike_pct"] == 0.0
    assert line["whiff_pct"] == 0.0
    assert line["first_pitch_strike_pct"] == 0.0


def test_pitch_characteristics_usage_sums_to_100():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    ch = P.pitch_characteristics(df)
    assert len(ch) >= 1
    assert abs(ch["usage_pct"].sum() - 100.0) < 0.5


def test_pitch_usage_sums_to_100():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    u = P.pitch_usage(df)
    assert abs(u["usage_pct"].sum() - 100.0) < 0.5


def test_zone_location_pct_in_range():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    z = P.zone_location(df)
    assert len(z) >= 1
    assert z["in_zone_pct"].between(0, 100).all()


def test_usage_by_count_has_count_state_column():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    uc = P.usage_by_count(df)
    assert "count_state" in uc.columns
    assert len(uc) >= 1


def test_splits_cover_both_sides_keys():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    splits = P.splits_by_batter_side(df)
    assert set(splits.keys()) == {"Left", "Right"}


def test_averages_last5_rowcount_matches_recent():
    recent = P.recent_outings(PITCHER_ID, GAME_ID, n=5)
    avg = P.averages_last5(recent)
    assert len(avg) == len(recent)


import plotly.graph_objects as go


def test_figure_builders_return_figures():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    for fn in (P.fig_velo_by_inning, P.fig_velo_by_pitch, P.fig_movement,
               P.fig_location, P.fig_location_split, P.fig_heatmap_overall):
        fig = fn(df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1


def test_velo_trend_figure():
    trend = P.velo_trend(PITCHER_ID)
    fig = P.fig_velo_trend(trend)
    assert isinstance(fig, go.Figure)


def test_heatmaps_by_pitch_type_labeled():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    items = P.fig_heatmaps_by_pitch_type(df)
    assert len(items) >= 1
    for label, fig in items:
        assert isinstance(label, str)
        assert isinstance(fig, go.Figure)
