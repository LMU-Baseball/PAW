"""All Things Process board: metric lines, leaders, baseline checks, cycle
math, and the table's pinned-summary sorting/styling. Inline pitch frames
only -- no database."""
import pandas as pd

from app.data import process_board as PB
from app.dashboards.process_board import layout as L
from app.dashboards.process_board import tables as T


def _pitch(name, game, inning, pa, pitch, call, balls=0, strikes=0, korbb="Undefined",
           result="Undefined", outs=0, ev=None, speed=90.0, ptype="Fastball", throws="Right"):
    return {"pitcher_name": name, "game_id": game, "inning": inning, "pa_of_inning": pa,
            "pitch_of_pa": pitch, "pitch_call": call, "balls": balls, "strikes": strikes,
            "korbb": korbb, "play_result": result, "outs_on_play": outs, "exit_speed": ev,
            "rel_speed": speed, "tagged_pitch_type": ptype, "auto_pitch_type": ptype,
            "pitcher_throws": throws, "batter_side": "Right"}


def _frame():
    return pd.DataFrame([
        # A: strikeout on 3 pitches, then a 4-pitch walk
        _pitch("A, One", "g1", 1, 1, 1, "StrikeCalled"),
        _pitch("A, One", "g1", 1, 1, 2, "StrikeSwinging", strikes=1),
        _pitch("A, One", "g1", 1, 1, 3, "StrikeSwinging", strikes=2, korbb="Strikeout", speed=94.0),
        _pitch("A, One", "g1", 1, 2, 1, "BallCalled"),
        _pitch("A, One", "g1", 1, 2, 2, "BallCalled", balls=1),
        _pitch("A, One", "g1", 1, 2, 3, "BallCalled", balls=2),
        _pitch("A, One", "g1", 1, 2, 4, "BallCalled", balls=3, korbb="Walk"),
        # B (lefty): first-pitch ground out at 96 EV
        _pitch("B, Two", "g1", 2, 1, 1, "InPlay", result="Out", outs=1, ev=96.0,
               speed=88.0, throws="Left"),
    ])


def test_metric_line_matches_pitching_transforms():
    a = PB.metric_line(_frame()[lambda d: d["pitcher_name"] == "A, One"])
    assert a["pitches"] == 7
    assert a["strike_pct"] == 42.9
    assert a["fps_pct"] == 50.0
    assert a["k_pct"] == 50.0 and a["bb_pct"] == 50.0
    assert a["twok_kill_pct"] == 100.0
    # no balls in play -> Barrel% has no denominator -> blank, not 0
    assert a["barrel_pct"] is None
    assert a["velo_avg"] == 90.6 and a["velo_max"] == 94.0


def test_metric_line_empty_frame_is_all_blank():
    line = PB.metric_line(_frame().iloc[0:0])
    assert line["pitches"] == 0
    assert all(line[k] is None for k, _l, _f, _h in PB.METRICS)
    assert line["velo_avg"] is None


def test_pitcher_rows_alphabetical_with_hand():
    rows = PB.pitcher_rows(_frame())
    assert [r["pitcher"] for r in rows] == ["A, One (R)", "B, Two (L)"]
    assert rows[1]["barrel_pct"] == 100.0


def test_best_values_respects_lower_is_better():
    rows = [{"strike_pct": 60.0, "bb_pct": 12.0, "velo_max": 91.0},
            {"strike_pct": 70.0, "bb_pct": 4.0, "velo_max": None}]
    best = PB.best_values(rows)
    assert best["strike_pct"] == 70.0
    assert best["bb_pct"] == 4.0
    assert best["velo_max"] == 91.0
    assert "fps_pct" not in best


def test_meets_baseline_direction():
    assert PB.meets_baseline("strike_pct", 55.0) is True
    assert PB.meets_baseline("strike_pct", 54.9) is False
    assert PB.meets_baseline("bb_pct", 9.0) is True
    assert PB.meets_baseline("bb_pct", 11.0) is False
    assert PB.meets_baseline("velo_avg", 90.0) is None
    assert PB.meets_baseline("k_pct", None) is None


def test_previous_cycle_and_display():
    assert PB.previous_cycle("2025/2026", "Spring") == ("2025/2026", "Fall")
    assert PB.previous_cycle("2026/2027", "Fall") == ("2025/2026", "Spring")
    assert PB.cycle_display("2025/2026", "Fall") == "Fall 2025"
    assert PB.cycle_display("2025/2026", "Spring") == "Spring 2026"


def test_board_rows_and_reference_labels(monkeypatch):
    frame = _frame()
    monkeypatch.setattr(PB, "window_pitches", lambda s, e, t=None: frame)
    board = PB.board("2026/2027", "Fall")
    labels = [r["pitcher"] for r in board["summary"]]
    assert labels == ["LMU Baseline", "LMU Spring 2026 Average", "LMU Team Average"]
    assert board["summary"][0]["strike_pct"] == 55.0
    assert board["summary"][2]["pitches"] == 8
    assert len(board["pitchers"]) == 2


def _board():
    return {"summary": [{"pitcher": "LMU Baseline", "kind": "baseline", "strike_pct": 55.0}],
            "pitchers": [{"pitcher": "A", "strike_pct": 50.0},
                         {"pitcher": "B", "strike_pct": None},
                         {"pitcher": "C", "strike_pct": 70.0}],
            "best": {"strike_pct": 70.0}}


def test_records_keep_summary_on_top_and_blanks_last():
    recs = T.records(_board(), [{"column_id": "strike_pct", "direction": "desc"}])
    assert [r["pitcher"] for r in recs] == ["LMU Baseline", "C", "A", "B"]
    recs = T.records(_board(), [{"column_id": "strike_pct", "direction": "asc"}])
    assert [r["pitcher"] for r in recs] == ["LMU Baseline", "A", "C", "B"]
    assert [r["pitcher"] for r in T.records(_board())] == ["LMU Baseline", "A", "B", "C"]


def test_cell_styles_leader_and_baseline_tints():
    styles = T.cell_styles(_board())
    leader = [s for s in styles if s.get("backgroundColor") == T.LEADER]
    assert leader and leader[0]["if"]["filter_query"].endswith("{strike_pct} = 70.0")
    meets = [s for s in styles if s.get("backgroundColor") == T.MEETS
             and s["if"].get("column_id") == "bb_pct"]
    assert "<= 10.0" in meets[0]["if"]["filter_query"]
    # leader styles come after tints so the gold wins
    assert styles.index(leader[0]) > styles.index(meets[0])


def test_table_and_header_render():
    dt = T.process_table(_board())
    assert dt.id == T.TABLE_ID and dt.sort_action == "custom"
    ids = [c["id"] for c in dt.columns]
    assert ids[0] == "pitcher" and "twok_kill_pct" in ids and "velo_max" in ids
    assert "kind" not in ids
    assert "ALL THINGS PROCESS" in str(L.process_header())


def test_team_line_keeps_intrasquad_halves_apart():
    top = _frame()[lambda d: d["pitcher_name"] == "A, One"].assign(top_bottom="Top")
    bottom = top.assign(top_bottom="Bottom", pitcher_name="C, Three")
    line = PB.metric_line(pd.concat([top, bottom]))
    assert line["bb_pct"] == 50.0 and line["k_pct"] == 50.0
