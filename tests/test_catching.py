"""Unit tests for catching transforms (synthetic DataFrames — no DB)."""
import pandas as pd

from app.data import catching as C


def _pitches():
    return pd.DataFrame([
        # Heart take — called strike
        {"pitch_call": "StrikeCalled", "play_result": "Undefined",
         "plate_loc_side": 0.0, "plate_loc_height": 2.5, "batter_side": "Right",
         "inning": 1, "balls": 0, "strikes": 0, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        # Shadow take — ball
        {"pitch_call": "BallCalled", "play_result": "Undefined",
         "plate_loc_side": 1.0, "plate_loc_height": 2.5, "batter_side": "Left",
         "inning": 1, "balls": 0, "strikes": 1, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        # Shadow take — called strike
        {"pitch_call": "StrikeCalled", "play_result": "Undefined",
         "plate_loc_side": 0.9, "plate_loc_height": 2.5, "batter_side": "Right",
         "inning": 1, "balls": 1, "strikes": 1, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        # Swing — excluded from framing
        {"pitch_call": "StrikeSwinging", "play_result": "Undefined",
         "plate_loc_side": 0.2, "plate_loc_height": 2.4, "batter_side": "Right",
         "inning": 2, "balls": 1, "strikes": 1, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        # Dirt blocked
        {"pitch_call": "BallinDirt", "play_result": "Undefined",
         "plate_loc_side": 0.1, "plate_loc_height": 0.8, "batter_side": "Left",
         "inning": 3, "balls": 0, "strikes": 2, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        # Passed ball
        {"pitch_call": "BallCalled", "play_result": "PassedBall",
         "plate_loc_side": 0.0, "plate_loc_height": 0.5, "batter_side": "Right",
         "inning": 4, "balls": 1, "strikes": 2, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        # Throw attempts
        {"pitch_call": "InPlay", "play_result": "StolenBase",
         "plate_loc_side": 0.3, "plate_loc_height": 2.2, "batter_side": "Right",
         "inning": 5, "balls": 0, "strikes": 0, "pitcher_name": "A, B",
         "pop_time": 1.95, "exchange_time": 0.72, "throw_speed": 78.5},
        {"pitch_call": "InPlay", "play_result": "CaughtStealing",
         "plate_loc_side": -0.2, "plate_loc_height": 2.1, "batter_side": "Left",
         "inning": 6, "balls": 1, "strikes": 1, "pitcher_name": "A, B",
         "pop_time": 1.88, "exchange_time": 0.68, "throw_speed": 80.0},
    ])


def test_takes_filters_swings():
    t = C.takes(_pitches())
    assert set(t["pitch_call"]) <= C._TAKE_CALLS
    assert "StrikeSwinging" not in set(t["pitch_call"])


def test_framing_by_zone_shape():
    z = C.framing_by_zone(_pitches())
    assert list(z["Zone"]) == ["Heart", "Shadow", "Chase", "Waste"]
    assert {"Takes", "CalledStrikes", "CS%"} <= set(z.columns)
    heart = z.loc[z["Zone"] == "Heart"].iloc[0]
    assert heart["Takes"] >= 1
    assert heart["CalledStrikes"] >= 1


def test_framing_overall():
    o = C.framing_overall(_pitches())
    assert o["takes"] >= 2
    assert o["called_strikes"] >= 1
    assert 0.0 <= o["cs_pct"] <= 100.0


def test_framing_shadow():
    s = C.framing_shadow(_pitches())
    assert s["takes"] >= 1
    assert s["cs_pct"] is not None


def test_framing_by_batter_side():
    sp = C.framing_by_batter_side(_pitches())
    assert list(sp["Split"]) == ["vs LHH", "vs RHH"]
    assert sp["Takes"].sum() >= 2


def test_blocking_summary():
    s = C.blocking_summary(_pitches())
    assert s["dirt"] >= 2
    assert s["blocked"] >= 1
    assert s["passed_wild"] >= 1
    assert s["block_pct"] is not None


def test_dirt_events_outcomes():
    ev = C.dirt_events(_pitches())
    assert "BlockOutcome" in ev.columns
    assert set(ev["BlockOutcome"]) <= {"Blocked", "Passed/Wild"}


def test_throws_summary():
    s = C.throws_summary(_pitches())
    assert s["attempts"] == 2
    assert s["avg_pop"] is not None
    assert s["min_pop"] == 1.88
    assert s["avg_throw_speed"] is not None


def test_throw_attempts_empty_without_cols():
    df = pd.DataFrame([{"pitch_call": "StrikeCalled", "play_result": "Undefined"}])
    assert C.throw_attempts(df).empty


def test_empty_df_transforms_safe():
    empty = pd.DataFrame()
    assert C.framing_overall(empty)["takes"] == 0
    assert C.framing_shadow(empty)["takes"] == 0
    assert C.blocking_summary(empty)["dirt"] == 0
    assert C.throws_summary(empty)["attempts"] == 0
    assert C.framing_by_zone(empty).shape[0] == 4
    assert C.framing_by_batter_side(empty).shape[0] == 2


def _framing_rows():
    import pandas as pd
    # side_ft, height_ft chosen so |side*12|,|height*12-30| land in/out of the box.
    return pd.DataFrame([
        # In zone (x=0, y=0), called ball -> Lost Strike
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "BallCalled",
         "batter_side": "Right", "pitcher_throws": "Left", "tagged_pitch_type": "Fastball"},
        # Out of zone (x=24in), called strike -> Stolen Strike
        {"plate_loc_side": 2.0, "plate_loc_height": 2.5, "pitch_call": "StrikeCalled",
         "batter_side": "Left", "pitcher_throws": "Right", "tagged_pitch_type": "Slider"},
        # In zone, called strike -> Correct Call
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "StrikeCalled",
         "batter_side": "Right", "pitcher_throws": "Right", "tagged_pitch_type": "ChangeUp"},
        # Swing (InPlay) -> Correct Call regardless of zone
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "InPlay",
         "batter_side": "Left", "pitcher_throws": "Left", "tagged_pitch_type": "Curveball"},
    ])


def test_add_framing_cols_classifies_call_type():
    from app.data import catching as C
    out = C.add_framing_cols(_framing_rows())
    assert list(out["CallType"]) == [
        "Lost Strike", "Stolen Strike", "Correct Call", "Correct Call"]
    assert list(out["InZone"]) == [True, False, True, True]
    assert out.loc[0, "Zone"] == "Heart"
    # catcher-view coords
    assert out.loc[1, "_x"] == -24.0


def test_add_framing_cols_pitch_speed_recode():
    from app.data import catching as C
    out = C.add_framing_cols(_framing_rows())
    assert list(out["PitchSpeed"]) == [
        "Fastball", "Offspeed", "Offspeed", "Offspeed"]


def test_add_framing_cols_empty():
    import pandas as pd
    from app.data import catching as C
    assert C.add_framing_cols(pd.DataFrame()).empty


def test_apply_framing_filters():
    from app.data import catching as C
    df = C.add_framing_cols(_framing_rows())
    assert len(C.apply_framing_filters(df)) == 4  # all "All"
    assert len(C.apply_framing_filters(df, bat_side="Left")) == 2
    assert len(C.apply_framing_filters(df, pitch_speed="Fastball")) == 1
    # rows 0,2,3 are side=0 -> x=0 -> Heart; row 1 is side=2.0 -> x=24in -> Waste
    assert len(C.apply_framing_filters(df, zone="Heart")) == 3
