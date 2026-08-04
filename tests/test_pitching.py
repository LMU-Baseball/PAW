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


def test_pretty_result_maps_calls():
    assert P.pretty_result("StrikeSwinging") == "Swinging Strike"
    assert P.pretty_result("BallCalled") == "Ball"
    assert P.pretty_result("InPlay") == "In Play"
    assert P.pretty_result("Nonsense") == "Nonsense"  # unknown passes through


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


# ============ Pitch Breakdown: pitch colors + per-outing velo sequence (Task 3) =

@pytest.fixture(scope="module")
def outing_like_df():
    pid = _a_real_lmu_pitcher_id()          # helper added in Slice 1 task 3
    gid = int(P.games_for_pitcher(pid).iloc[0]["game_id"])
    return P.game_pitches_for(gid, pid)


def test_pitch_color_stable_and_hex():
    from app.data import pitching as P
    c = P.pitch_color("Fastball")
    assert c.startswith("#") and c == P.pitch_color("Fastball")


def test_fig_velo_by_pitch_uses_1_based_sequence(outing_like_df):
    from app.data import pitching as P
    fig = P.fig_velo_by_pitch(outing_like_df)
    xs = [x for tr in fig.data for x in (tr.x if tr.x is not None else [])]
    assert xs and min(xs) == 1  # per-outing sequence starts at 1, not game pitch_no


# ============ Last Outings: preset count + avg/max velo trend (Task 6) =======

@pytest.fixture(scope="module")
def real_pitcher_id_and_game():
    from app.data import pitching as P
    pid = _a_real_lmu_pitcher_id()
    gid = int(P.games_for_pitcher(pid).iloc[0]["game_id"])
    return pid, gid


def test_fig_outings_velo_trend_two_lines(real_pitcher_id_and_game):
    from app.data import pitching as P
    pid, gid = real_pitcher_id_and_game
    recent = P.recent_outings(pid, gid, 5)
    fig = P.fig_outings_velo_trend(recent)
    names = {tr.name for tr in fig.data}
    assert {"Avg Velo", "Max Velo"} <= names


# ============ Date-bounded games + pooled loader (Task 2) =====================

def test_games_for_pitcher_date_filter():
    from app.data import pitching as P
    pit = P.wh_lmu_pitchers()
    if pit.empty:
        import pytest; pytest.skip("no LMU pitchers")
    pid = int(pit.iloc[0]["PitcherId"])
    allg = P.games_for_pitcher(pid)
    assert {"game_id", "game_date", "GameLabel"} <= set(allg.columns)
    if len(allg) >= 2:
        lo = str(allg["game_date"].min())
        hi = str(allg["game_date"].max())
        bounded = P.games_for_pitcher(pid, start=lo, end=hi)
        assert len(bounded) == len(allg)  # full span == all games
        # narrow to only the most recent game's date
        recent = str(allg["game_date"].max())
        narrowed = P.games_for_pitcher(pid, start=recent, end=recent)
        assert len(narrowed) >= 1 and len(narrowed) <= len(allg)


def test_range_pitches_for_unions_range():
    from app.data import pitching as P
    pit = P.wh_lmu_pitchers()
    if pit.empty:
        import pytest; pytest.skip("no LMU pitchers")
    pid = int(pit.iloc[0]["PitcherId"])
    allg = P.games_for_pitcher(pid)
    if allg.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(allg["game_date"].min()), str(allg["game_date"].max())
    pooled = P.range_pitches_for(pid, lo, hi)
    # pooled equals the sum of single-game loads across the range
    single_total = sum(len(P.game_pitches_for(int(g), pid)) for g in allg["game_id"])
    assert len(pooled) == single_total


def test_pitching_figs_have_labeled_hovers():
    import pandas as pd
    from app.data import pitching as P
    df = pd.DataFrame({
        "pitch_no": [1, 2, 3, 4],
        "rel_speed": [90.0, 89.0, 80.0, 81.0],
        "horz_break": [-10.0, -9.0, 12.0, 11.0],
        "induced_vert_break": [22.0, 21.0, 4.0, 5.0],
        "inning": [1, 1, 2, 2],
        "auto_pitch_type": ["Fastball", "Fastball", "Sweeper", "Sweeper"],
        "tagged_pitch_type": ["Fastball", "Fastball", "Sweeper", "Sweeper"],
    })
    velo = P.fig_velo_by_pitch(df)
    assert any("Pitch No:" in (t.hovertemplate or "") for t in velo.data)
    assert any("Velo:" in (t.hovertemplate or "") for t in velo.data)
    mv = P.fig_movement(df)
    assert any("HB:" in (t.hovertemplate or "") and "IVB:" in (t.hovertemplate or "")
               for t in mv.data)
    inn = P.fig_velo_by_inning(df)
    assert any("Avg Velo:" in (t.hovertemplate or "") for t in inn.data)


def test_fig_movement_has_one_ellipse_per_pitch_type():
    import pandas as pd
    from app.data import pitching as P
    rows = []
    for pt, pts in [
        ("Fastball", [(-11, 21), (-9, 23), (-10, 24), (-8, 22)]),
        ("Sweeper", [(11, 4), (13, 6), (12, 3), (14, 5)]),
    ]:
        for hb, ivb in pts:
            rows.append({"horz_break": hb, "induced_vert_break": ivb,
                         "auto_pitch_type": pt, "tagged_pitch_type": pt})
    df = pd.DataFrame(rows)
    fig = P.fig_movement(df)
    ellipses = [t for t in fig.data if getattr(t, "fill", None) == "toself"]
    assert len(ellipses) == 2  # one per pitch type
    assert any(t.mode == "markers" for t in fig.data)


def test_count_states_and_heatmap():
    import pandas as pd
    import plotly.graph_objects as go
    from app.data import pitching as P
    df = pd.DataFrame({
        "balls": [0, 1, 0], "strikes": [0, 2, 0],
        "plate_loc_side": [0.1, -0.4, 0.2], "plate_loc_height": [2.5, 3.0, 2.2],
        "pitch_call": ["StrikeCalled", "BallCalled", "InPlay"],
        "tagged_pitch_type": ["Fastball", "Slider", "Fastball"]})
    assert P.count_states(df) == ["0-0", "1-2"]
    assert isinstance(P.fig_heatmap(df), go.Figure)
    # empty-safe
    assert isinstance(P.fig_heatmap(df.iloc[0:0]), go.Figure)


def test_format_ip():
    from app.data import pitching as P
    assert P.format_ip(0) == "0.0"
    assert P.format_ip(1) == "0.1"
    assert P.format_ip(3) == "1.0"
    assert P.format_ip(8) == "2.2"


def test_barrel_pct_ev_drops_la_qualifier():
    import pandas as pd
    from app.data import pitching as P
    # 3 balls in play: two at 95+ (one GroundBall — excluded by the report's
    # LD/FB def but INCLUDED here), one under 95.
    df = pd.DataFrame({
        "pitch_call": ["InPlay", "InPlay", "InPlay", "StrikeCalled"],
        "exit_speed": [98.0, 96.0, 80.0, None],
        "tagged_hit_type": ["GroundBall", "LineDrive", "FlyBall", None]})
    pct, n = P.barrel_pct_ev(df)
    assert n == 2 and pct == round(100 * 2 / 3, 1)


def test_range_summary_shape_and_date_bounding(real_pitcher_id_and_game):
    from app.data import pitching as P
    pid, _ = real_pitcher_id_and_game
    g = P.games_for_pitcher(pid)
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    full = P.range_summary(pid, start, end)
    assert set(full) == {"appearances", "ip", "k_pct", "bb_pct", "barrel_pct"}
    assert full["k_pct"].endswith("%") and full["ip"]
    one = P.range_summary(pid, start, start)
    assert int(one["appearances"]) <= int(full["appearances"])
    # no-date fallback path (career-wide) returns the same key set + display strings
    nodate = P.range_summary(pid)
    assert set(nodate) == {"appearances", "ip", "k_pct", "bb_pct", "barrel_pct"}
    assert nodate["k_pct"].endswith("%")


def test_header_stat_line_has_strike_and_maxvelo():
    import pandas as pd
    from app.data import pitching as P
    df = pd.DataFrame({
        "batter_side": ["Right", "Left"], "outs_on_play": [0, 1],
        "play_result": ["Out", "Single"], "runs_scored": [0, 0],
        "korbb": ["Undefined", "Undefined"], "pitch_of_pa": [1, 1],
        "pitch_call": ["StrikeCalled", "BallCalled"], "rel_speed": [90.0, 94.4],
        "balls": [0, 1], "strikes": [1, 0], "inning": [1, 1], "pa_of_inning": [1, 2]})
    line = P.header_stat_line(df)
    assert "strike_pct" in line and "max_velo" in line
    assert line["max_velo"] == 94.4
    assert 0 <= line["strike_pct"] <= 100
