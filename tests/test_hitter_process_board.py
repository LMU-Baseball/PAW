"""Hitter All Things Process board: metric definitions, leaders, team-average
baseline coloring, and the table's summary-row sorting. Inline pitch frames
only -- no database."""
import pandas as pd

from app.data import hitter_process_board as HB
from app.dashboards.hitter_process_board import tables as T


def _p(name, call, side=0.0, height=2.5, ev=None, hit=None, bats="Right", la=None):
    return {"batter_name": name, "batter_side": bats, "plate_side": side,
            "plate_height": height, "pitch_call": call, "exit_speed": ev, "launch_angle": la,
            "hit_type": hit, "game_type": "Scrimmage"}


def _frame():
    return pd.DataFrame([
        # A: in-zone take, in-zone whiff, in-zone foul, chase whiff, ball taken,
        # hard-hit liner, soft popup
        _p("A, One", "StrikeCalled"),
        _p("A, One", "StrikeSwinging"),
        _p("A, One", "FoulBallNotFieldable"),
        _p("A, One", "StrikeSwinging", side=1.5),
        _p("A, One", "BallCalled", side=1.5),
        _p("A, One", "InPlay", ev=100.0, hit="LineDrive", la=15.0),
        _p("A, One", "InPlay", ev=60.0, hit="Popup"),
        # B (switch): one grounder
        _p("B, Two", "InPlay", ev=80.0, hit="GroundBall"),
        _p("B, Two", "InPlay", ev=90.0, hit="GroundBall", bats="Left"),
    ])


def test_metric_line_definitions():
    a = HB.metric_line(_frame()[lambda d: d["batter_name"] == "A, One"])
    assert a["pitches"] == 7
    assert a["swing_pct"] == 71.4          # 5 swings / 7 pitches
    assert a["contact_pct"] == 60.0        # foul + 2 in play = 3 of 5 swings
    assert a["whiff_pct"] == 40.0          # 2 of 5 swings
    assert a["iz_whiff_pct"] == 25.0       # 1 whiff / 4 in-zone swings
    assert a["chase_pct"] == 50.0          # 1 swing / 2 out-of-zone pitches
    assert a["barrel_pct"] == 50.0         # 1 of 2 balls in play at 95+ and 9-35 deg
    assert a["max_ev"] == 100.0 and a["avg_ev"] == 80.0
    assert a["gb_pct"] == 0.0 and a["ld_pct"] == 50.0
    assert a["fb_pct"] == 50.0             # popup counts as a fly ball


def test_metric_line_blank_not_zero_without_denominator():
    taken = pd.DataFrame([_p("C, Three", "BallCalled")])
    line = HB.metric_line(taken)
    assert line["swing_pct"] == 0.0
    assert line["contact_pct"] is None and line["whiff_pct"] is None
    assert line["barrel_pct"] is None and line["max_ev"] is None
    assert HB.metric_line(taken.iloc[0:0])["pitches"] == 0


def test_hitter_rows_alphabetical_with_side():
    rows = HB.hitter_rows(_frame())
    assert [r["hitter"] for r in rows] == ["A, One (R)", "B, Two (S)"]


def test_clean_names_merges_trailing_space_variants(monkeypatch):
    # Real case (Oct 2026): same BatterId loaded as 'Marucci, Luca' and 'Marucci, Luca '
    raw = pd.DataFrame([
        _p("Marucci, Luca", "StrikeCalled"),
        _p("Marucci, Luca ", "BallCalled"),
        _p("  Marucci,  Luca", "InPlay", ev=90.0, hit="LineDrive"),
        _p("Other, Guy", "BallCalled"),
    ])
    monkeypatch.setattr(HB, "_query_pitches", lambda s, e: raw.copy())
    df = HB._pitches("1900-01-01", "1900-01-02")
    rows = HB.hitter_rows(df)
    assert [r["hitter"] for r in rows] == ["Marucci, Luca (R)", "Other, Guy (R)"]
    assert rows[0]["pitches"] == 3


def test_clean_names_keeps_missing_names_missing():
    out = HB.clean_names(pd.Series(["A, One ", "   ", None]))
    assert out[0] == "A, One" and pd.isna(out[1]) and pd.isna(out[2])


def test_leader_needs_minimum_pitches_and_respects_direction():
    rows = [{"pitches": 100, "gb_pct": 40.0, "max_ev": 99.0},
            {"pitches": 100, "gb_pct": 30.0, "max_ev": 101.0},
            {"pitches": 5, "gb_pct": 0.0, "max_ev": 110.0}]
    best = HB.best_values(rows)
    assert best["gb_pct"] == 30.0       # lower is better, small sample excluded
    assert best["max_ev"] == 101.0


def test_styles_color_against_team_average():
    board = {"summary": [], "hitters": [], "best": {"max_ev": 101.0},
             "baseline": {"max_ev": 90.0, "chase_pct": 25.0, "swing_pct": None}}
    styles = T.cell_styles(board)
    blue = [s for s in styles if s.get("backgroundColor") == T.MEETS]
    red = [s for s in styles if s.get("backgroundColor") == T.MISSES]
    q = {s["if"]["column_id"]: s["if"]["filter_query"] for s in blue}
    assert q["max_ev"].endswith(">= 90.0")      # higher is better
    assert q["chase_pct"].endswith("<= 25.0")   # lower is better
    assert "swing_pct" not in q                 # no baseline -> unshaded
    assert len(red) == 2
    assert styles[-1]["backgroundColor"] == T.LEADER


def test_records_pin_summary_rows_and_sort_missing_last():
    board = {"summary": [{"hitter": "Team", "kind": "team"}],
             "hitters": [{"hitter": "A", "avg_ev": 80.0}, {"hitter": "B", "avg_ev": None},
                         {"hitter": "C", "avg_ev": 85.0}]}
    rows = T.records(board, [{"column_id": "avg_ev", "direction": "desc"}])
    assert [r["hitter"] for r in rows] == ["Team", "C", "A", "B"]


def test_chase_is_chase_or_waste_zone_not_shadow():
    # 1.0 ft off center is outside the rulebook plate but still Shadow: a swing
    # there is NOT a chase; 1.5 ft (Chase) and 2.0 ft (Waste) are.
    df = pd.DataFrame([
        _p("D, Four", "StrikeSwinging", side=1.0),
        _p("D, Four", "StrikeSwinging", side=1.5),
        _p("D, Four", "BallCalled", side=2.0),
        _p("D, Four", "FoulBallNotFieldable", side=2.0),
    ])
    assert HB.metric_line(df)["chase_pct"] == round(100 * 2 / 3, 1)
