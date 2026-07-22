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


# ============ Landing-page helpers (recent_games / pitchers_for_game) ========

def test_recent_games_newest_first_and_capped():
    df = P.recent_games(limit=10)
    assert isinstance(df, pd.DataFrame)
    assert 1 <= len(df) <= 10
    dates = pd.to_datetime(df["game_date"])
    assert list(dates) == sorted(dates, reverse=True)


def test_recent_games_all_involve_lmu():
    df = P.recent_games(limit=25)
    involved = (df["home_team"] == "LMU") | (df["away_team"] == "LMU")
    assert involved.all()


def test_pitchers_for_game_lists_known_pitcher():
    df = P.pitchers_for_game(GAME_ID)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert (df["game_id"] == GAME_ID).all()
    assert {"player_id", "display_name"}.issubset(df.columns)
    assert PITCHER_ID in set(df["player_id"])


def test_pitchers_for_game_alpha_sorts_by_name():
    df = P.pitchers_for_game(GAME_ID, sort="alpha")
    assert list(df["display_name"]) == sorted(df["display_name"])


def test_pitchers_for_game_pitch_order_is_by_first_pitch():
    """Pitch-order sort must rank pitchers by when they entered the game."""
    from app.db import query_df
    df = P.pitchers_for_game(GAME_ID, sort="pitch")
    assert len(df) >= 2  # need at least two to have a meaningful order
    firsts = query_df(
        "SELECT pitcher_id, MIN(pitch_no) AS fp "
        "FROM fact_tm_game_pitch WHERE game_id = :g GROUP BY pitcher_id",
        {"g": GAME_ID},
    ).set_index("pitcher_id")["fp"].to_dict()
    seq = [firsts[pid] for pid in df["player_id"] if pid in firsts]
    assert seq == sorted(seq)  # non-decreasing first-pitch order


# ============ Dashboard data-layer additions (Task 3) ========================

def _a_real_lmu_pitcher_id():
    from app.data import pitching as P
    from app.db import query_df
    df = query_df(
        """
        SELECT pitcher_id FROM fact_tm_game_pitch
         WHERE pitcher_team = 'LOY_LIO' AND pitcher_id IS NOT NULL
         GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "pitcher_id"])


def test_wh_lmu_pitchers_has_rows_and_columns():
    from app.data import pitching as P
    df = P.wh_lmu_pitchers()
    assert not df.empty
    assert {"PitcherId", "Pitcher"} <= set(df.columns)
    assert df["PitcherId"].is_unique


def test_games_for_pitcher_newest_first():
    from app.data import pitching as P
    pid = _a_real_lmu_pitcher_id()
    g = P.games_for_pitcher(pid)
    assert not g.empty
    assert {"game_id", "GameLabel"} <= set(g.columns)


def test_pitcher_profile_and_season_summary_keys():
    from app.data import pitching as P
    pid = _a_real_lmu_pitcher_id()
    prof = P.pitcher_profile(pid)
    assert set(prof) >= {"name", "class_year", "position", "throws", "jersey", "photo"}
    summ = P.season_summary(pid)
    assert set(summ) >= {"appearances", "pitches", "k", "bb"}
