import pandas as pd
import plotly.graph_objects as go
import pytest

from app.data import pitching as P


@pytest.fixture(scope="module")
def outing_df():
    """A small, hand-built pitch DataFrame with the columns the pure transforms
    and figure builders read. Replaces the old warehouse ``game_pitches`` fixture
    (the warehouse loaders moved to ``app.data.pitching_caps``). 4 Fastballs +
    3 Sliders, both batter sides, valid plate locations for every pitch."""
    return pd.DataFrame({
        "pitch_no": [1, 2, 3, 4, 5, 6, 7],
        "tagged_pitch_type": ["Fastball", "Fastball", "Fastball", "Fastball",
                              "Slider", "Slider", "Slider"],
        "auto_pitch_type": ["Fastball", "Fastball", "Fastball", "Fastball",
                            "Slider", "Slider", "Slider"],
        "batter_side": ["Right", "Right", "Left", "Left", "Right", "Left", "Right"],
        "inning": [1, 1, 1, 2, 2, 2, 2],
        "pa_of_inning": [1, 1, 2, 1, 1, 2, 2],
        "pitch_of_pa": [1, 2, 1, 1, 1, 1, 2],
        "balls": [0, 0, 0, 1, 0, 0, 1],
        "strikes": [0, 1, 0, 1, 2, 0, 2],
        "pitch_call": ["StrikeCalled", "InPlay", "BallCalled", "StrikeSwinging",
                       "StrikeSwinging", "BallCalled", "InPlay"],
        "korbb": ["Undefined", "Undefined", "Undefined", "Undefined",
                  "Strikeout", "Undefined", "Undefined"],
        "batters_faced": [1, 1, 2, 3, 4, 5, 5],
        "runs_scored": [0, 0, 0, 0, 0, 0, 1],
        "outs_on_play": [0, 1, 0, 0, 1, 0, 1],
        "play_result": ["Undefined", "Out", "Undefined", "Undefined",
                        "Undefined", "Undefined", "Single"],
        "rel_speed": [91.0, 92.5, 90.0, 93.0, 82.0, 81.0, 83.0],
        "spin_rate": [2200.0, 2250.0, 2180.0, 2300.0, 2400.0, 2380.0, 2420.0],
        "induced_vert_break": [16.0, 17.0, 15.5, 16.5, 4.0, 3.5, 4.5],
        "horz_break": [-8.0, -9.0, -7.5, -8.5, 10.0, 11.0, 9.5],
        "rel_height": [5.8, 5.9, 5.7, 5.85, 5.75, 5.8, 5.82],
        "rel_side": [-1.2, -1.1, -1.3, -1.15, -1.25, -1.2, -1.22],
        "extension": [6.2, 6.3, 6.1, 6.25, 6.0, 6.1, 6.05],
        "izt_zone": ["5", "1", "Ball", "9", "3", "Ball", "7"],
        "plate_loc_side": [0.1, -0.2, 0.5, -0.3, 0.2, 0.6, -0.1],
        "plate_loc_height": [2.5, 2.8, 3.2, 2.2, 2.6, 3.4, 2.9],
        "exit_speed": [None, 85.0, None, None, None, None, 98.0],
        "tagged_hit_type": [None, "GroundBall", None, None, None, None, "LineDrive"],
        "vert_appr_angle": [-5.0, -4.8, -5.2, -4.9, -7.0, -7.2, -6.8],
    })


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


def test_game_overall_line_counts_are_consistent(outing_df):
    line = P.game_overall_line(outing_df)
    assert line["pitches"] == len(outing_df)
    assert 0 <= line["strike_pct"] <= 100
    assert line["strikes"] + line["balls"] <= line["pitches"]


def test_game_overall_line_empty_df_no_divide_by_zero(outing_df):
    line = P.game_overall_line(outing_df.iloc[0:0])
    assert line["pitches"] == 0
    assert line["strike_pct"] == 0.0
    assert line["whiff_pct"] == 0.0
    assert line["first_pitch_strike_pct"] == 0.0


def test_pitch_characteristics_usage_sums_to_100(outing_df):
    ch = P.pitch_characteristics(outing_df)
    assert len(ch) >= 1
    assert abs(ch["usage_pct"].sum() - 100.0) < 0.5


def test_pitch_usage_sums_to_100(outing_df):
    u = P.pitch_usage(outing_df)
    assert abs(u["usage_pct"].sum() - 100.0) < 0.5


def test_zone_location_pct_in_range(outing_df):
    z = P.zone_location(outing_df)
    assert len(z) >= 1
    assert z["in_zone_pct"].between(0, 100).all()


def test_usage_by_count_has_count_state_column(outing_df):
    uc = P.usage_by_count(outing_df)
    assert "count_state" in uc.columns
    assert len(uc) >= 1


def test_fastball_callout():
    df = pd.DataFrame({"tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
                       "rel_speed": [90.0, 92.0, 80.0], "spin_rate": [2200.0, 2300.0, 2400.0]})
    c = P.fastball_callout(df)
    assert c["avg_velo"] == 91.0 and c["max_velo"] == 92.0 and c["avg_spin"] == 2250
    empty = P.fastball_callout(pd.DataFrame({"tagged_pitch_type": ["Slider"],
                                             "rel_speed": [80.0], "spin_rate": [2400.0]}))
    assert empty == {"avg_velo": None, "max_velo": None, "avg_spin": None}


def test_splits_cover_both_sides_keys(outing_df):
    splits = P.splits_by_batter_side(outing_df)
    assert set(splits.keys()) == {"Left", "Right"}


def test_averages_last5_rowcount_matches_recent():
    recent = pd.DataFrame({
        "game_date": ["2026-05-01", "2026-05-08", "2026-05-15"],
        "away_team_name": ["USD", "LMU", "SMC"],
        "home_team_name": ["LMU", "USF", "LMU"],
        "appearance_avg_velo": [90.1, 91.2, 89.8],
        "appearance_max_velo": [93.0, 94.1, 92.5],
        "pitch_count": [80, 75, 90],
    })
    avg = P.averages_last5(recent)
    assert len(avg) == len(recent)


def test_figure_builders_return_figures(outing_df):
    for fn in (P.fig_velo_by_inning, P.fig_velo_by_pitch, P.fig_movement,
               P.fig_location, P.fig_location_split, P.fig_heatmap_overall):
        fig = fn(outing_df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1


def test_velo_trend_figure():
    trend = pd.DataFrame({
        "game_date": ["2026-04-01", "2026-04-08", "2026-04-15"],
        "avg_velo": [90.0, 91.0, 90.5],
    })
    fig = P.fig_velo_trend(trend)
    assert isinstance(fig, go.Figure)


def test_heatmaps_by_pitch_type_labeled(outing_df):
    items = P.fig_heatmaps_by_pitch_type(outing_df)
    assert len(items) >= 1
    for label, fig in items:
        assert isinstance(label, str)
        assert isinstance(fig, go.Figure)


def test_pitch_color_stable_and_hex():
    c = P.pitch_color("Fastball")
    assert c.startswith("#") and c == P.pitch_color("Fastball")


def test_fig_velo_by_pitch_uses_1_based_sequence(outing_df):
    fig = P.fig_velo_by_pitch(outing_df)
    xs = [x for tr in fig.data for x in (tr.x if tr.x is not None else [])]
    assert xs and min(xs) == 1  # per-outing sequence starts at 1, not game pitch_no


def test_fig_outings_velo_trend_two_lines():
    recent = pd.DataFrame({
        "game_date": ["2026-05-01", "2026-05-08", "2026-05-15"],
        "appearance_avg_velo": [90.1, 91.2, 89.8],
        "appearance_max_velo": [93.0, 94.1, 92.5],
    })
    fig = P.fig_outings_velo_trend(recent)
    names = {tr.name for tr in fig.data}
    assert {"Avg Velo", "Max Velo"} <= names


def test_pitching_figs_have_labeled_hovers():
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
    assert P.format_ip(0) == "0.0"
    assert P.format_ip(1) == "0.1"
    assert P.format_ip(3) == "1.0"
    assert P.format_ip(8) == "2.2"


def test_barrel_pct_ev_drops_la_qualifier():
    # 3 balls in play: two at 95+ (one GroundBall — excluded by the report's
    # LD/FB def but INCLUDED here), one under 95.
    df = pd.DataFrame({
        "pitch_call": ["InPlay", "InPlay", "InPlay", "StrikeCalled"],
        "exit_speed": [98.0, 96.0, 80.0, None],
        "tagged_hit_type": ["GroundBall", "LineDrive", "FlyBall", None]})
    pct, n = P.barrel_pct_ev(df)
    assert n == 2 and pct == round(100 * 2 / 3, 1)


def test_header_stat_line_has_strike_and_maxvelo():
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
