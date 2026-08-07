"""Unit tests for catching transforms (synthetic DataFrames — no DB)."""
import pandas as pd

from app.data import catching as C


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


def _framing_table_rows():
    import pandas as pd
    # Build explicit CallType/Zone mixes. height=2.5 -> y=0 (in vert range);
    # x sets the zone: 0in Heart, 24in Waste, 11in Shadow.
    def row(side, height, call):
        return {"plate_loc_side": side, "plate_loc_height": height,
                "pitch_call": call, "batter_side": "Right",
                "pitcher_throws": "Right", "tagged_pitch_type": "Fastball"}
    return pd.DataFrame([
        row(0.0, 2.5, "StrikeCalled"),   # Heart, in-zone strike -> Correct
        row(0.0, 2.5, "BallCalled"),     # Heart, in-zone ball  -> Lost (heart)
        row(2.0, 2.5, "StrikeCalled"),   # Waste(24in), out strike -> Stolen (waste)
        row(0.9167, 2.5, "StrikeCalled"),  # ~11in Shadow, out-of-box strike -> Stolen (shadow)
        # Non-take (swing) pitch with a valid location: must be INCLUDED in the
        # steal% denominator (Heart, Correct Call) even though it isn't a "take".
        row(0.0, 2.5, "StrikeSwinging"),
        # Invalid plate location (NaN): must be EXCLUDED from the denominator
        # entirely, regardless of pitch_call, per the legacy valid-loc filter.
        row(None, None, "BallCalled"),
    ])


def test_framing_table_math():
    from app.data import catching as C
    df = C.add_framing_cols(_framing_table_rows())
    t = C.framing_table(df)
    # stolen = 2 (waste + shadow), lost = 1 (heart) -> net = 1
    assert t["net_strikes"] == 1
    # Steal% = lost / count(valid plate-loc pitches) * 100.
    # Valid-loc rows = 5 (the NaN-loc row is excluded from the denominator,
    # the StrikeSwinging non-take row is included): 1/5*100 = 20.0
    assert t["steal_pct"] == 20.0
    assert t["shadow_net"] == 1
    assert t["heart_net"] == -1
    # Heart zone = rows 0 (Correct), 1 (Lost), 4 (Correct, non-take swing)
    # -> 1 lost / 3 heart valid-loc pitches = 33.3
    # (matches legacy src/app.R: denom is ALL heart-zone valid-loc pitches,
    # not just lost+stolen, and not restricted to "takes")
    assert t["heart_loss_pct"] == 33.3


def test_framing_table_empty():
    import pandas as pd
    from app.data import catching as C
    t = C.framing_table(pd.DataFrame())
    assert t["net_strikes"] == 0 and t["steal_pct"] is None


def test_caught_stealing_summary():
    import pandas as pd
    from app.data import catching as C
    df = pd.DataFrame([
        {"play_result": "StolenBase", "pop_time": 2.0, "exchange_time": 0.7,
         "throw_speed": 78.0, "inning": 1, "pitcher_name": "A, B"},
        {"play_result": "CaughtStealing", "pop_time": 1.9, "exchange_time": 0.66,
         "throw_speed": 80.0, "inning": 3, "pitcher_name": "A, B"},
        {"play_result": "Single", "pop_time": None, "exchange_time": None,
         "throw_speed": None, "inning": 4, "pitcher_name": "A, B"},
    ])
    ev = C.caught_stealing_events(df)
    assert len(ev) == 2
    assert list(ev["Caught"]) == [False, True]
    s = C.caught_stealing_summary(df)
    assert s["attempts"] == 2 and s["caught"] == 1
    assert s["cs_pct"] == 50.0
    assert s["avg_pop"] == 1.95


def test_caught_stealing_empty():
    import pandas as pd
    from app.data import catching as C
    s = C.caught_stealing_summary(pd.DataFrame())
    assert s["attempts"] == 0 and s["cs_pct"] is None


def test_caught_stealing_trend():
    import pandas as pd
    from app.data import catching as C
    df = pd.DataFrame([
        {"play_result": "CaughtStealing", "pop_time": 1.9, "exchange_time": 0.7,
         "throw_speed": 80.0, "game_date": "2026-04-01"},
        {"play_result": "StolenBase", "pop_time": 2.1, "exchange_time": 0.75,
         "throw_speed": 78.0, "game_date": "2026-04-01"},
        {"play_result": "StolenBase", "pop_time": None, "exchange_time": None,
         "throw_speed": None, "game_date": "2026-04-08"},
        {"play_result": "Single", "pop_time": None, "exchange_time": None,
         "throw_speed": None, "game_date": "2026-04-08"},
    ])
    t = C.caught_stealing_trend(df)
    assert list(t["game_date"]) == ["2026-04-01", "2026-04-08"]
    assert list(t["attempts"]) == [2, 1]
    assert list(t["caught"]) == [1, 0]
    assert t.iloc[0]["cs_pct"] == 50.0 and t.iloc[1]["cs_pct"] == 0.0
    assert t.iloc[0]["avg_pop"] == 2.0 and t.iloc[1]["avg_pop"] is None


def test_caught_stealing_trend_empty():
    import pandas as pd
    from app.data import catching as C
    assert C.caught_stealing_trend(pd.DataFrame()).empty
    # df with no CS attempts -> empty trend
    only_single = pd.DataFrame([{"play_result": "Single", "game_date": "2026-04-01"}])
    assert C.caught_stealing_trend(only_single).empty
