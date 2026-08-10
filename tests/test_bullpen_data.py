import pandas as pd

from app.data import bullpen as B

GEIS = 824645  # raw Trackman PitcherId for Jake Geis in BULLPEN
WINDOW = ("2025-09-01", "2026-05-13")  # bounded window covering the loaded data


def test_lmu_pitchers_include_geis():
    p = B.lmu_bullpen_pitchers()
    assert not p.empty
    assert GEIS in set(int(x) for x in p["pitcher_id"])
    assert {"pitcher_id", "pitcher", "sessions"} <= set(p.columns)


def test_lmu_bullpen_pitchers_scopes_by_date():
    everyone = set(B.lmu_bullpen_pitchers()["pitcher_id"])
    ranged = set(B.lmu_bullpen_pitchers(start="1900-01-01", end="1900-01-02")["pitcher_id"])
    assert ranged == set()          # no bullpens in 1900
    assert everyone                 # sanity: unscoped still returns pitchers


def test_lmu_bullpen_pitchers_scoped_within_window_matches_geis():
    scoped = set(int(x) for x in B.lmu_bullpen_pitchers(start=WINDOW[0], end=WINDOW[1])["pitcher_id"])
    assert GEIS in scoped


def test_sessions_and_pitches_for_geis():
    s = B.sessions_for(GEIS)
    assert not s.empty and {"date", "pitches"} <= set(s.columns)
    date = s.iloc[0]["date"]
    d = B.session_pitches(GEIS, date)
    assert not d.empty
    for col in ("pitch_no", "tagged_pitch_type", "rel_speed", "spin_rate",
                "tilt", "ind_vert_break", "horz_break", "rel_height",
                "rel_side", "extension", "plate_loc_side", "plate_loc_height"):
        assert col in d.columns


def test_summary_by_pitch_type_shape():
    s = B.sessions_for(GEIS)
    d = B.session_pitches(GEIS, s.iloc[0]["date"])
    rows = B.summary_by_pitch_type(d)
    assert rows and {"pitch", "qty", "velo_avg", "spin_avg"} <= set(rows[0])
    assert sum(r["qty"] for r in rows) == len(d)


def test_max_date_reflects_backfill():
    # BULLPEN repopulated 2026-08-03; data now runs through 2026.
    assert str(B.bullpen_data_max_date()) >= "2026-01-01"


def test_pitcher_name_for_geis():
    assert B.pitcher_name(GEIS)  # non-empty "Last, First"
    assert B.pitcher_name(-1) is None


def test_session_options_within_window_newest_first():
    df = B.session_options(GEIS, *WINDOW)
    assert not df.empty and {"date", "pitches"} <= set(df.columns)
    dates = list(df["date"])
    assert dates == sorted(dates, reverse=True)          # newest first
    assert all("2025-09-01" <= d <= "2026-05-13" for d in dates)


def test_bullpen_session_summary_shape():
    s = B.bullpen_session_summary(GEIS, *WINDOW)
    assert set(s) == {"sessions", "pitches", "strike_pct", "avg_fb_velo", "last_date"}
    assert s["sessions"] >= 1 and s["pitches"] >= 1


def test_bullpen_session_summary_empty_pitcher():
    s = B.bullpen_session_summary(-1, *WINDOW)
    assert s == {"sessions": 0, "pitches": 0, "strike_pct": None,
                 "avg_fb_velo": None, "last_date": "—"}


def test_strike_pct_zone_plus_edge():
    df = pd.DataFrame({  # 3 in zone-ish, 1 far outside
        "plate_loc_side": [0.0, 0.5, -0.9, 3.0],
        "plate_loc_height": [2.5, 3.0, 2.0, 2.5]})
    v = B.strike_pct(df)
    assert v == 75.0  # first three within zone+~2.9in buffer, last far out
    assert B.strike_pct(pd.DataFrame({"plate_loc_side": [], "plate_loc_height": []})) is None


def test_avg_fb_velo():
    df = pd.DataFrame({"tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
                       "rel_speed": [90.0, 92.0, 80.0]})
    assert B.avg_fb_velo(df) == 91.0
    assert B.avg_fb_velo(pd.DataFrame({"tagged_pitch_type": ["Slider"], "rel_speed": [80.0]})) is None


def test_session_summary_has_new_tiles():
    s = B.bullpen_session_summary(GEIS, "2025-09-01", "2026-05-13")
    assert set(s) == {"sessions", "pitches", "strike_pct", "avg_fb_velo", "last_date"}


def test_trend_by_session_columns_and_sorting():
    df = B.trend_by_session(GEIS, *WINDOW)
    assert not df.empty
    assert {"date", "tagged_pitch_type", "pitches", "velo_avg", "velo_max",
            "spin_avg", "eff_avg", "ivb_avg", "hb_avg", "loc_spread"} <= set(df.columns)
    # grouped/sorted by (type, date)
    assert list(df[["tagged_pitch_type", "date"]].itertuples(index=False, name=None)) == \
        sorted(df[["tagged_pitch_type", "date"]].itertuples(index=False, name=None))
