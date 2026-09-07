"""Splash Report storage layer (live DB): schema idempotency, fixed-shape
reindexing, and REPLACE semantics for the variable-row tables."""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text

from app.data import splash_report as SR
from app.db import get_engine

TEST_PID = -999101  # sandboxed fake player id; never collides with real GAMES data
SEASON = "2099/2100"  # sandboxed fake season label
CYCLE = "Fall"


@pytest.fixture(autouse=True)
def _clean_sandbox():
    yield
    with get_engine().begin() as conn:
        for t in (SR.PLANS_TABLE, SR.ENGINE_TABLE, SR.GAS_TABLE, SR.SCRIPTS_TABLE,
                 SR.SCRIPT_ROWS_TABLE, SR.PEN_TABLE):
            conn.execute(text(f"DELETE FROM {t} WHERE player_id = :p"), {"p": TEST_PID})


def test_ensure_tables_idempotent():
    SR.ensure_tables()
    SR.ensure_tables()  # second call is a no-op, not an error


def test_cycle_for_date():
    assert SR.cycle_for_date("2026-09-15") == "Fall"
    assert SR.cycle_for_date("2026-01-10") == "Winter"
    assert SR.cycle_for_date("2026-04-01") == "Spring"


def test_plan_roundtrip_and_defaults():
    empty = SR.read_plan(TEST_PID, SEASON, CYCLE)
    assert empty == {c: "" for c in (
        "vision_statement", "training_goals", "pre_throw_checklist",
        "post_throw_checklist", "feet_set", "feet_moving", "work_day",
        "recovery_video_url")}

    SR.upsert_plan(TEST_PID, SEASON, CYCLE, {
        "vision_statement": "Get after it", "training_goals": "Goal one\nGoal two",
        "pre_throw_checklist": "Breathe", "post_throw_checklist": "Reset",
        "feet_set": "Partner Decels (Green x8)", "feet_moving": "", "work_day": "",
        "recovery_video_url": "",
    }, updated_by=1)
    saved = SR.read_plan(TEST_PID, SEASON, CYCLE)
    assert saved["vision_statement"] == "Get after it"
    assert saved["training_goals"] == "Goal one\nGoal two"
    assert saved["feet_set"] == "Partner Decels (Green x8)"

    # a second upsert overwrites in place, not a second row
    SR.upsert_plan(TEST_PID, SEASON, CYCLE, {**saved, "vision_statement": "Revised"},
                   updated_by=1)
    assert SR.read_plan(TEST_PID, SEASON, CYCLE)["vision_statement"] == "Revised"


def test_plan_recovery_url_untouched_when_omitted_by_a_partial_update():
    """save_all's callback path always re-reads the current recovery_video_url
    and passes it straight through (no edit UI exists yet) -- this proves an
    upsert that includes it keeps a previously-saved value stable."""
    SR.upsert_plan(TEST_PID, SEASON, CYCLE, {"recovery_video_url": "https://x/video.mp4"},
                  updated_by=1)
    plan = SR.read_plan(TEST_PID, SEASON, CYCLE)
    assert plan["recovery_video_url"] == "https://x/video.mp4"
    SR.upsert_plan(TEST_PID, SEASON, CYCLE,
                   {**plan, "vision_statement": "New focus"}, updated_by=1)
    assert SR.read_plan(TEST_PID, SEASON, CYCLE)["recovery_video_url"] == "https://x/video.mp4"


def test_engine_metrics_reindexed_to_fixed_seven_with_computed_delta():
    grid = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)
    assert list(grid["metric_key"]) == list(SR.ENGINE_METRIC_KEYS)
    assert grid["base_value"].isna().all() and grid["delta"].isna().all()

    SR.upsert_engine_metrics(TEST_PID, SEASON, CYCLE, [
        {"metric_key": "IR", "base_value": 40, "now_value": 45},
        {"metric_key": "TotalArc", "base_value": 180, "now_value": 175},
        {"metric_key": "NotAMetric", "base_value": 1, "now_value": 2},  # ignored
    ], updated_by=1)
    grid2 = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)
    assert len(grid2) == 7
    ir = grid2[grid2.metric_key == "IR"].iloc[0]
    assert ir["base_value"] == 40.0 and ir["now_value"] == 45.0 and ir["delta"] == 5.0
    arc = grid2[grid2.metric_key == "TotalArc"].iloc[0]
    assert arc["delta"] == -5.0  # regression: now < base
    assert "NotAMetric" not in set(grid2["metric_key"])


def test_gas_station_replace_drops_blank_rows_and_removes_stale_ones():
    SR.replace_gas_station(TEST_PID, SEASON, CYCLE, [
        {"need": "Forearm Strength", "exercise": "Cuban press", "sets_reps": "3x10", "notes": ""},
        {"need": "", "exercise": "", "sets_reps": "", "notes": ""},  # all-blank -> dropped
    ], updated_by=1)
    gas = SR.read_gas_station(TEST_PID, SEASON, CYCLE)
    assert len(gas) == 1 and gas.iloc[0]["need"] == "Forearm Strength"

    # a second replace with FEWER rows must not leave the first row behind
    SR.replace_gas_station(TEST_PID, SEASON, CYCLE, [
        {"need": "Core Control", "exercise": "Sleeper stretch", "sets_reps": "2x30s", "notes": ""},
    ], updated_by=1)
    gas2 = SR.read_gas_station(TEST_PID, SEASON, CYCLE)
    assert len(gas2) == 1 and gas2.iloc[0]["need"] == "Core Control"


def test_scripts_reindexed_to_fixed_six():
    scripts = SR.read_scripts(TEST_PID, SEASON, CYCLE)
    assert list(scripts["script_number"]) == list(range(1, 7))
    assert (scripts["goal"] == "").all()

    SR.upsert_scripts(TEST_PID, SEASON, CYCLE,
                      [{"script_number": 1, "goal": "FB command", "measurable": "Zone%"},
                       {"script_number": 99, "goal": "ignored", "measurable": "x"}],
                      updated_by=1)
    scripts2 = SR.read_scripts(TEST_PID, SEASON, CYCLE)
    row1 = scripts2[scripts2.script_number == 1].iloc[0]
    assert row1["goal"] == "FB command" and row1["measurable"] == "Zone%"
    assert len(scripts2) == 6  # the out-of-range script_number=99 was ignored


def test_script_rows_reindexed_to_fixed_twelve():
    rows = SR.read_script_rows(TEST_PID, SEASON, CYCLE, 1)
    assert list(rows["row_num"]) == list(range(1, 13))
    assert (rows["pitch_type"] == "").all()

    SR.upsert_script_rows(TEST_PID, SEASON, CYCLE, 1,
                          [{"row_num": 1, "pitch_type": "FB", "ball_info": "5+", "info": "vRHH"}],
                          updated_by=1)
    rows2 = SR.read_script_rows(TEST_PID, SEASON, CYCLE, 1)
    assert len(rows2) == 12
    assert rows2.iloc[0]["pitch_type"] == "FB"
    assert rows2.iloc[1]["pitch_type"] == ""  # untouched row still blank, not missing

    # a different script_number's rows are independent
    empty_script2 = SR.read_script_rows(TEST_PID, SEASON, CYCLE, 2)
    assert (empty_script2["pitch_type"] == "").all()


def test_read_all_script_rows_matches_per_script_reads_in_one_query():
    """read_all_script_rows (one query for all six) must return exactly what
    six read_script_rows calls would, since it replaces those six round
    trips on the page's render path."""
    SR.upsert_script_rows(TEST_PID, SEASON, CYCLE, 1,
                          [{"row_num": 1, "pitch_type": "FB", "ball_info": "5+", "info": "vRHH"}],
                          updated_by=1)
    SR.upsert_script_rows(TEST_PID, SEASON, CYCLE, 3,
                          [{"row_num": 5, "pitch_type": "CH", "ball_info": "Reg", "info": ""}],
                          updated_by=1)
    all_rows = SR.read_all_script_rows(TEST_PID, SEASON, CYCLE)
    assert set(all_rows) == set(range(1, SR.N_SCRIPTS + 1))
    for n in range(1, SR.N_SCRIPTS + 1):
        expected = SR.read_script_rows(TEST_PID, SEASON, CYCLE, n)
        assert all_rows[n].equals(expected)
    assert all_rows[1].iloc[0]["pitch_type"] == "FB"
    assert all_rows[3].iloc[4]["pitch_type"] == "CH"
    assert (all_rows[2]["pitch_type"] == "").all()  # untouched script -> all blank


def test_upsert_all_script_rows_writes_every_script_in_one_call():
    """upsert_all_script_rows (one multi-row statement for up to 72 rows --
    6 scripts x 12 -- instead of 72 separate upserts) must match what
    upsert_script_rows called once per script would persist."""
    SR.upsert_all_script_rows(TEST_PID, SEASON, CYCLE, {
        1: [{"row_num": 1, "pitch_type": "FB", "ball_info": "5+", "info": "vRHH"}],
        2: [{"row_num": 12, "pitch_type": "CB", "ball_info": "Reg", "info": ""}],
    }, updated_by=1)
    all_rows = SR.read_all_script_rows(TEST_PID, SEASON, CYCLE)
    assert all_rows[1].iloc[0]["pitch_type"] == "FB"
    assert all_rows[2].iloc[11]["pitch_type"] == "CB"
    assert (all_rows[3]["pitch_type"] == "").all()

    # a re-save overwrites in place (upsert), not a duplicate/extra row
    SR.upsert_all_script_rows(TEST_PID, SEASON, CYCLE,
                              {1: [{"row_num": 1, "pitch_type": "SL", "ball_info": "", "info": ""}]},
                              updated_by=1)
    assert SR.read_all_script_rows(TEST_PID, SEASON, CYCLE)[1].iloc[0]["pitch_type"] == "SL"


def test_multi_row_upsert_helpers_are_empty_safe():
    """An empty rows list (nothing to save for that section) must be a
    no-op, not a malformed empty-VALUES SQL statement."""
    SR.upsert_engine_metrics(TEST_PID, SEASON, CYCLE, [], updated_by=1)
    SR.upsert_scripts(TEST_PID, SEASON, CYCLE, [], updated_by=1)
    SR.upsert_script_rows(TEST_PID, SEASON, CYCLE, 1, [], updated_by=1)
    SR.upsert_all_script_rows(TEST_PID, SEASON, CYCLE, {}, updated_by=1)
    # still safe to read back (all blank, nothing crashed)
    assert SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)["base_value"].isna().all()


def test_pen_results_replace_assigns_sequential_pen_number_per_script():
    SR.replace_pen_results(TEST_PID, SEASON, CYCLE, [
        {"script_number": 1, "pen_date": "2026-09-01", "value": 60.0},
        {"script_number": 1, "pen_date": "2026-09-15", "value": 65.0},
        {"script_number": 2, "pen_date": "2026-09-01", "value": 50.0},
        {"script_number": None, "pen_date": "2026-09-01", "value": 40.0},  # dropped
        {"script_number": 3, "pen_date": "2026-09-01", "value": None},  # dropped (no value)
    ], updated_by=1)
    pen = SR.read_pen_results(TEST_PID, SEASON, CYCLE).sort_values(
        ["script_number", "pen_number"]).reset_index(drop=True)
    assert len(pen) == 3
    s1 = pen[pen.script_number == 1].sort_values("pen_number")
    assert list(s1["pen_number"]) == [1, 2]
    assert list(s1["value"]) == [60.0, 65.0]

    # replace again with fewer rows -> old ones gone (no stale leftovers)
    SR.replace_pen_results(TEST_PID, SEASON, CYCLE,
                           [{"script_number": 1, "pen_date": "2026-10-01", "value": 70.0}],
                           updated_by=1)
    pen2 = SR.read_pen_results(TEST_PID, SEASON, CYCLE)
    assert len(pen2) == 1 and pen2.iloc[0]["value"] == 70.0


def test_save_all_persists_every_section_in_one_call():
    SR.save_all(
        TEST_PID, SEASON, CYCLE,
        plan_fields={"vision_statement": "Focus", "training_goals": "", "pre_throw_checklist": "",
                    "post_throw_checklist": "", "feet_set": "", "feet_moving": "",
                    "work_day": "", "recovery_video_url": ""},
        engine_rows=[{"metric_key": "ER", "base_value": 30, "now_value": 35}],
        gas_rows=[{"need": "Mass", "exercise": "Squat", "sets_reps": "3x5", "notes": ""}],
        script_fields={1: {"goal": "G1", "measurable": "M1"}},
        script_pitch_rows={1: [{"row_num": 1, "pitch_type": "FB", "ball_info": "", "info": ""}]},
        pen_rows=[{"script_number": 1, "pen_date": "2026-09-01", "value": 55.0}],
        updated_by=1,
    )
    assert SR.read_plan(TEST_PID, SEASON, CYCLE)["vision_statement"] == "Focus"
    eng = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)
    assert eng[eng.metric_key == "ER"].iloc[0]["now_value"] == 35.0
    assert len(SR.read_gas_station(TEST_PID, SEASON, CYCLE)) == 1
    assert SR.read_scripts(TEST_PID, SEASON, CYCLE).iloc[0]["goal"] == "G1"
    assert SR.read_script_rows(TEST_PID, SEASON, CYCLE, 1).iloc[0]["pitch_type"] == "FB"
    assert len(SR.read_pen_results(TEST_PID, SEASON, CYCLE)) == 1


def test_feet_drill_and_strength_need_options_are_nonempty_and_deduped():
    assert len(SR.FEET_DRILL_OPTIONS) == len(set(SR.FEET_DRILL_OPTIONS)) > 50
    assert len(SR.STRENGTH_NEED_OPTIONS) == 8
