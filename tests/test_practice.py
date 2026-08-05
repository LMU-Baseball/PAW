"""Unit tests for HitTrax practice transforms (synthetic — no DB)."""
import pandas as pd

from app.data import practice as P


def _pitches():
    return pd.DataFrame([
        {"player_name": "Doe, John", "session_id": 1, "result": -4,
         "px": 0.0, "py": 2.5, "exit_velocity": None, "distance_feet": None,
         "zone_section": 5, "play_timestamp": "2026-04-01 10:00:00",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": False},
        {"player_name": "Doe, John", "session_id": 1, "result": 1,
         "px": 0.1, "py": 2.4, "exit_velocity": 88.0, "distance_feet": 220.0,
         "zone_section": 5, "play_timestamp": "2026-04-01 10:00:05",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": True},
        {"player_name": "Doe, John", "session_id": 1, "result": -4,
         "px": 1.2, "py": 3.8, "exit_velocity": None, "distance_feet": None,
         "zone_section": 11, "play_timestamp": "2026-04-01 10:00:10",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": False},
        {"player_name": "Doe, John", "session_id": 1, "result": 2,
         "px": 1.1, "py": 3.7, "exit_velocity": 92.0, "distance_feet": 280.0,
         "zone_section": 11, "play_timestamp": "2026-04-01 10:00:15",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": True},
    ])


def test_trim_to_first_contact_drops_leading_takes():
    d = P.trim_to_first_contact(_pitches())
    # First row is a take before first contact — dropped
    assert len(d) == 3
    assert d.iloc[0]["is_contact"]


def test_contact_summary():
    s = P.contact_summary(_pitches())
    assert s["pitches"] == 4
    assert s["contacts"] == 2
    assert s["contact_pct"] == 50.0


def test_swing_decision_score():
    s = P.swing_decision_score(_pitches())
    assert s["in_zone_pct"] is not None
    assert s["chase_pct"] is not None
    assert s["score"] == round(s["in_zone_pct"] - s["chase_pct"], 1)


def test_swing_decision_score_default_in_zones_matches_1_through_9():
    # Default (no arg) must reproduce the legacy 1-9 in-zone / 10-13 chase behavior.
    df = _pitches()
    assert P.swing_decision_score(df) == P.swing_decision_score(df, in_zones=range(1, 10))


def test_swing_decision_score_custom_in_zones_changes_result():
    # zone 3 = in-zone contact; zone 5 = in-zone miss; zone 11 = chase contact;
    # zone 12 = chase miss.  Default (1-9): in-zone 1/2=50, chase 1/2=50, score 0.
    df = pd.DataFrame([
        {"zone_section": 3, "result": 1},
        {"zone_section": 5, "result": -4},
        {"zone_section": 11, "result": 1},
        {"zone_section": 12, "result": -4},
    ])
    df["is_contact"] = df["result"] != -4
    assert P.swing_decision_score(df)["score"] == 0.0
    # Restrict in-zone to just zone 3: in-zone 1/1=100; chase = zones 5,11,12 ->
    # 1 contact / 3 = 33.3; score 66.7.
    custom = P.swing_decision_score(df, in_zones={3})
    assert custom["in_zone_pct"] == 100.0
    assert custom["chase_pct"] == 33.3
    assert custom["score"] == 66.7


def test_swing_decision_trend_respects_in_zones():
    df = pd.DataFrame([
        {"play_date": "2026-04-01", "zone_section": 3, "result": 1},   # in-zone contact
        {"play_date": "2026-04-01", "zone_section": 11, "result": -4},  # chase miss
    ])
    df["is_contact"] = df["result"] != -4
    # Default (1-9): iz 100, chase 0, score 100.
    assert P.swing_decision_trend(df).iloc[0]["score"] == 100.0
    # In-zone = {11} only: iz (zone 11) 0%, chase (zone 3) 100%, score -100.
    t = P.swing_decision_trend(df, in_zones={11})
    assert t.iloc[0]["score"] == -100.0


def test_zone_contact_table():
    z = P.zone_contact_table(_pitches())
    assert set(z["Zone"]) >= {5, 11}
    assert {"Pitches", "Contacts", "Contact%"} <= set(z.columns)


def test_heatmap_shape():
    z, xe, ye = P.heatmap_contact_rate(_pitches(), bins=10)
    assert z.shape == (10, 10)
    assert len(xe) == 11 and len(ye) == 11


def test_apply_filters_player_and_session():
    d = _pitches()
    out = P.apply_filters(d, player="Doe, John", start=None, end=None,
                          session="Hitting — BP")
    assert len(out) == 4
    out2 = P.apply_filters(d, player="Nobody", start=None, end=None, session=None)
    assert out2.empty


def test_hit_type_counts():
    plays = pd.DataFrame({"hit_type": [0, 1, 2, 2, 3]})
    c = P.hit_type_counts(plays)
    assert "Line Drive" in set(c["Hit Type"])


def test_swing_decision_trend():
    import pandas as pd
    from app.data import practice as P
    df = pd.DataFrame([
        # 2026-04-01: 1 in-zone contact, 1 chase miss -> iz 100, chase 0, score 100
        {"play_date": "2026-04-01", "zone_section": 5, "result": 1},
        {"play_date": "2026-04-01", "zone_section": 11, "result": -4},
        # 2026-04-08: 1 in-zone miss -> iz 0, chase None -> score None (excluded)
        {"play_date": "2026-04-08", "zone_section": 3, "result": -4},
    ])
    df["is_contact"] = df["result"] != -4
    t = P.swing_decision_trend(df)
    assert list(t["play_date"]) == ["2026-04-01"]
    assert t.iloc[0]["score"] == 100.0


def test_heatmap_metric_ev_and_distance():
    import numpy as np, pandas as pd
    from app.data import practice as P
    df = pd.DataFrame([
        {"px": 0.0, "py": 2.5, "result": 1, "exit_velocity": 90.0, "distance_feet": 300.0},
        {"px": 0.0, "py": 2.5, "result": 1, "exit_velocity": 80.0, "distance_feet": 100.0},
    ])
    z_ev, xe, ye = P.heatmap_metric(df, "ev")
    z_dist, _, _ = P.heatmap_metric(df, "distance")
    # the one populated bin averages the two rows
    assert np.nanmax(z_ev) == 85.0
    assert np.nanmax(z_dist) == 200.0


def test_spray_points_sign_and_filter():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -45.0, "distance_feet": 100.0, "hit_type": 2},  # left, LD
        {"horizontal_angle": 45.0, "distance_feet": 100.0, "hit_type": 3},   # right, FB
        {"horizontal_angle": 0.0, "distance_feet": 0.0, "hit_type": 0},      # miss -> dropped
    ])
    s = P.spray_points(plays)
    assert len(s) == 2  # miss excluded
    assert s.iloc[0]["x"] < 0 and s.iloc[1]["x"] > 0  # neg angle = left
    assert set(s["hit_type_label"]) == {"Line Drive", "Fly Ball"}


def test_spray_points_carries_distance_and_ev():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -20.0, "distance_feet": 200.0, "exit_velocity": 95.0, "hit_type": 2},
        {"horizontal_angle": 10.0, "distance_feet": 350.0, "exit_velocity": 101.0, "hit_type": 3},
        {"horizontal_angle": 0.0, "distance_feet": 0.0, "exit_velocity": 0.0, "hit_type": 0},
    ])
    pts = P.spray_points(plays)
    assert list(pts.columns) == ["x", "y", "hit_type_label", "distance_feet", "exit_velocity", "is_foul", "is_hr"]
    assert len(pts) == 2  # hit_type 0 excluded
    assert set(pts["exit_velocity"]) == {95.0, 101.0}


def test_spray_fan_15_cells_and_pct_sums_100():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -40.0, "distance_feet": 120.0, "hit_type": 1},   # Left / Infield
        {"horizontal_angle": 0.0, "distance_feet": 200.0, "hit_type": 2},     # Center / Outfield
        {"horizontal_angle": 30.0, "distance_feet": 360.0, "hit_type": 3},    # Right / Deep
        {"horizontal_angle": 5.0, "distance_feet": 50.0, "hit_type": 0},      # excluded (miss)
    ])
    fan = P.spray_fan(plays)
    assert len(fan) == 15
    assert round(fan["pct"].sum(), 1) == 100.0
    assert int(fan["count"].sum()) == 3  # miss excluded
    # empty df -> 15 zero cells, no crash
    fan0 = P.spray_fan(pd.DataFrame(columns=["horizontal_angle", "distance_feet", "hit_type"]))
    assert len(fan0) == 15 and fan0["count"].sum() == 0


def test_fence_distance_interpolates_lmu_dimensions():
    import numpy as np
    from app.data import practice as P
    assert round(float(P.fence_distance(0.0))) == 406
    assert round(float(P.fence_distance(-45.0))) == 326
    assert round(float(P.fence_distance(45.0))) == 321
    # interpolates between LF line (326) and LF-center (362)
    mid = float(P.fence_distance(-33.75))
    assert 326 < mid < 362
    # clamps beyond the fair range
    assert float(P.fence_distance(-60.0)) == float(P.fence_distance(-45.0))
    # array input
    out = P.fence_distance(np.array([0.0, 45.0]))
    assert list(np.round(out)) == [406, 321]


def test_spray_points_foul_and_hr_flags():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -45.0, "distance_feet": 340.0, "exit_velocity": 100.0, "hit_type": 3},  # fair, over 326 -> HR
        {"horizontal_angle": -22.5, "distance_feet": 340.0, "exit_velocity": 100.0, "hit_type": 3},  # fair, under 362 -> not HR
        {"horizontal_angle": -60.0, "distance_feet": 250.0, "exit_velocity": 80.0, "hit_type": 2},   # foul
        {"horizontal_angle": 0.0, "distance_feet": 100.0, "exit_velocity": 70.0, "hit_type": 1},     # fair infield
    ])
    pts = P.spray_points(plays)
    assert {"is_foul", "is_hr"} <= set(pts.columns)
    assert list(pts["is_hr"]) == [True, False, False, False]
    assert list(pts["is_foul"]) == [False, False, True, False]


def test_spray_fan_hr_ring_and_averages():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -40.0, "distance_feet": 120.0, "exit_velocity": 85.0, "hit_type": 1},   # Left infield
        {"horizontal_angle": 0.0, "distance_feet": 200.0, "exit_velocity": 90.0, "hit_type": 2},     # Center outfield (fence 406)
        {"horizontal_angle": -40.0, "distance_feet": 360.0, "exit_velocity": 102.0, "hit_type": 3},  # Left HR (fence ~334)
    ])
    fan = P.spray_fan(plays)
    assert len(fan) == 15
    assert round(fan["pct"].sum(), 1) == 100.0
    assert "HR" in set(fan["ring"])
    hr = fan[(fan["ring"] == "HR") & (fan["count"] > 0)]
    assert len(hr) == 1 and int(hr.iloc[0]["count"]) == 1
    assert hr.iloc[0]["avg_ev"] == 102.0 and hr.iloc[0]["avg_dist"] == 360.0
    # empty df -> 15 zero cells, averages None
    fan0 = P.spray_fan(pd.DataFrame(columns=["horizontal_angle", "distance_feet", "hit_type"]))
    assert len(fan0) == 15 and fan0["count"].sum() == 0 and fan0["avg_ev"].isna().all()
