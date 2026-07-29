from app.data import bullpen as B

GEIS = 824645  # raw Trackman PitcherId for Jake Geis in BULLPEN


def test_lmu_pitchers_include_geis():
    p = B.lmu_bullpen_pitchers()
    assert not p.empty
    assert GEIS in set(int(x) for x in p["pitcher_id"])
    assert {"pitcher_id", "pitcher", "sessions"} <= set(p.columns)


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


def test_max_date_is_stale_2025():
    assert str(B.bullpen_data_max_date()).startswith("2025")
