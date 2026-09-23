"""Built on the Bluff storage layer (live DB): schema idempotency, fixed-shape
reindexing, and REPLACE semantics for the variable-row tables."""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text

from app.data import splash_report as SR
from app.dashboards.splash_report import charts as SC
from app.db import get_engine

TEST_PID = -999101  # sandboxed fake player id; never collides with real GAMES data
SEASON = "2099/2100"  # sandboxed fake season label
CYCLE = "Fall"

# Isolation-test-only sandboxed ids/labels (Task 4) -- kept distinct from
# TEST_PID/SEASON above so those tests' cleanup can't accidentally mask a
# cross-key leak in these ones.
ISO_PID_A = -999201
ISO_PID_B = -999202
ISO_SEASON_A = "2099/2100"  # matches SEASON on purpose (see brief's four keys)
ISO_SEASON_B = "2098/2099"  # a distinct fake season, never a real one


@pytest.fixture(autouse=True)
def _clean_sandbox():
    yield
    with get_engine().begin() as conn:
        for t in (SR.PLANS_TABLE, SR.ENGINE_TABLE, SR.READINGS_TABLE, SR.GAS_TABLE,
                 SR.SCRIPTS_TABLE, SR.SCRIPT_ROWS_TABLE, SR.PEN_TABLE, SR.MOVEMENT_TABLE):
            conn.execute(text(f"DELETE FROM {t} WHERE player_id = :p"), {"p": TEST_PID})
            for pid in (ISO_PID_A, ISO_PID_B):
                conn.execute(text(f"DELETE FROM {t} WHERE player_id = :p"), {"p": pid})


def test_ensure_tables_idempotent():
    SR.ensure_tables()
    SR.ensure_tables()  # second call is a no-op, not an error


def test_cycle_for_date():
    assert SR.cycle_for_date("2026-09-15") == "Fall"
    assert SR.cycle_for_date("2026-01-10") == "Winter"
    assert SR.cycle_for_date("2026-04-01") == "Spring"


def test_cycle_bounds():
    assert SR.cycle_bounds("2025/2026", "Fall") == ("2025-08-01", "2025-11-30")
    assert SR.cycle_bounds("2025/2026", "Winter") == ("2025-12-01", "2026-02-28")
    assert SR.cycle_bounds("2025/2026", "Spring") == ("2026-03-01", "2026-07-31")
    # leap year: 2028's Feb has 29 days
    assert SR.cycle_bounds("2027/2028", "Winter") == ("2027-12-01", "2028-02-29")
    with pytest.raises(ValueError):
        SR.cycle_bounds("2025/2026", "Summer")


def test_cycle_bounds_matches_cycle_for_date():
    """Every date `cycle_for_date` maps to a cycle should fall inside that
    cycle's own `cycle_bounds` window for the same season."""
    season = "2025/2026"
    for d in ("2025-08-01", "2025-11-30", "2025-12-01", "2026-02-28",
             "2026-03-01", "2026-07-31"):
        cycle = SR.cycle_for_date(d)
        start, end = SR.cycle_bounds(season, cycle)
        assert start <= d <= end


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


def test_engine_metrics_shows_every_key_with_computed_delta():
    grid = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)
    assert list(grid["metric_key"]) == list(SR.ENGINE_METRIC_KEYS)
    assert grid["base_value"].isna().all() and grid["delta"].isna().all()

    # Base/Now are plain manual cells now (2026-09-16 revert) -- one upsert
    # sets both directly, no dated-reading history involved.
    SR.upsert_engine_metrics(TEST_PID, SEASON, CYCLE, [
        {"metric_key": "IR", "base_value": 40, "now_value": 45},
        {"metric_key": "TotalArc", "base_value": 180, "now_value": 175},
        {"metric_key": "NotAMetric", "base_value": 1, "now_value": 1},  # ignored
    ], updated_by=1)
    grid2 = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)
    assert len(grid2) == len(SR.ENGINE_METRIC_KEYS)
    ir = grid2[grid2.metric_key == "IR"].iloc[0]
    assert ir["base_value"] == 40.0 and ir["now_value"] == 45.0 and ir["delta"] == 5.0
    arc = grid2[grid2.metric_key == "TotalArc"].iloc[0]
    assert arc["delta"] == -5.0  # regression: now < base
    assert "NotAMetric" not in set(grid2["metric_key"])

    # re-submitting the same metric corrects it in place, not a new row.
    SR.upsert_engine_metrics(TEST_PID, SEASON, CYCLE,
                             [{"metric_key": "IR", "base_value": 40, "now_value": 46}],
                             updated_by=1)
    assert SR.read_engine_metrics(TEST_PID, SEASON, CYCLE) \
        .set_index("metric_key").loc["IR", "now_value"] == 46.0


def test_upsert_engine_metrics_blank_cell_clears_stored_value():
    SR.upsert_engine_metrics(TEST_PID, SEASON, CYCLE,
                             [{"metric_key": "ER", "base_value": 20, "now_value": 22}],
                             updated_by=1)
    SR.upsert_engine_metrics(TEST_PID, SEASON, CYCLE,
                             [{"metric_key": "ER", "base_value": 20, "now_value": None}],
                             updated_by=1)
    er = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE).set_index("metric_key").loc["ER"]
    assert er["base_value"] == 20.0 and pd.isna(er["now_value"])


def test_engine_flag_thresholds():
    """IR's confirmed thresholds (Brad, 2026-09-16): red <= 40.5, yellow
    40.5-45, ok >= 45, deficit-only (no upper cap)."""
    assert SR.engine_flag("IR", None) is None  # no reading yet -> never flags
    assert SR.engine_flag("IR", 45.0) == "ok"        # at the green threshold
    assert SR.engine_flag("IR", 60.0) == "ok"        # well above -- still ok, deficit-only
    assert SR.engine_flag("IR", 42.0) == "yellow"     # inside the yellow range
    assert SR.engine_flag("IR", 40.5) == "red"        # at the red threshold
    assert SR.engine_flag("IR", 35.0) == "red"
    assert SR.engine_flag("IR", None) is None


def test_engine_flag_none_when_thresholds_unset():
    # Grip and Scaption ROM are still TBD (None) as of 2026-09-16.
    assert SR.engine_flag("Grip", 100.0) is None
    assert SR.engine_flag("ScaptionROM", 90.0) is None


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
    assert (scripts["script_type"] == "").all()

    SR.upsert_scripts(TEST_PID, SEASON, CYCLE,
                      [{"script_number": 1, "goal": "FB command", "measurable": "Zone%",
                        "script_type": "Pitch Design"},
                       {"script_number": 99, "goal": "ignored", "measurable": "x"}],
                      updated_by=1)
    scripts2 = SR.read_scripts(TEST_PID, SEASON, CYCLE)
    row1 = scripts2[scripts2.script_number == 1].iloc[0]
    assert row1["goal"] == "FB command" and row1["measurable"] == "Zone%"
    assert row1["script_type"] == "Pitch Design"
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


def test_save_pen_results_inserts_new_rows_and_derives_sequential_pen_number():
    SR.save_pen_results(TEST_PID, SEASON, CYCLE, [
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
    assert s1["id"].notna().all()  # every row has a stable surrogate id


def test_save_pen_results_soft_deletes_omitted_rows_and_they_are_restorable():
    """The whole point of this rework: a pen result a coach removes from the
    table (by not including its id in the next save) must NOT be gone for
    good -- it should move to the deleted set and come back via
    restore_pen_result, never a hard DELETE."""
    SR.save_pen_results(TEST_PID, SEASON, CYCLE, [
        {"script_number": 1, "pen_date": "2026-09-01", "value": 60.0},
        {"script_number": 1, "pen_date": "2026-09-08", "value": 65.0},
    ], updated_by=1)
    active = SR.read_pen_results(TEST_PID, SEASON, CYCLE)
    assert len(active) == 2
    kept, removed = active.iloc[0], active.iloc[1]

    # resubmit with only the first row's id present (as if the coach deleted
    # the second row in the UI and hit Save) plus a brand-new third entry
    SR.save_pen_results(TEST_PID, SEASON, CYCLE, [
        {"id": int(kept["id"]), "script_number": 1, "pen_date": kept["pen_date"],
         "value": kept["value"]},
        {"script_number": 1, "pen_date": "2026-09-15", "value": 70.0},
    ], updated_by=1)

    still_active = SR.read_pen_results(TEST_PID, SEASON, CYCLE)
    assert len(still_active) == 2
    assert int(removed["id"]) not in set(still_active["id"])  # gone from the live view

    deleted = SR.read_deleted_pen_results(TEST_PID, SEASON, CYCLE)
    assert len(deleted) == 1
    assert int(deleted.iloc[0]["id"]) == int(removed["id"])
    assert deleted.iloc[0]["value"] == 65.0  # the actual value is preserved, not wiped

    with get_engine().begin() as conn:
        row = conn.execute(text(f"SELECT active FROM {SR.PEN_TABLE} WHERE id = :id"),
                           {"id": int(removed["id"])}).fetchone()
        assert row is not None and row[0] == 0  # soft-deleted, the DB row still physically exists

    SR.restore_pen_result(int(removed["id"]), updated_by=1)
    restored = SR.read_pen_results(TEST_PID, SEASON, CYCLE)
    assert len(restored) == 3
    assert int(removed["id"]) in set(restored["id"])
    assert SR.read_deleted_pen_results(TEST_PID, SEASON, CYCLE).empty


def test_save_pen_results_updates_an_existing_row_in_place_by_id():
    SR.save_pen_results(TEST_PID, SEASON, CYCLE,
                        [{"script_number": 1, "pen_date": "2026-09-01", "value": 60.0}],
                        updated_by=1)
    row_id = int(SR.read_pen_results(TEST_PID, SEASON, CYCLE).iloc[0]["id"])

    SR.save_pen_results(TEST_PID, SEASON, CYCLE,
                        [{"id": row_id, "script_number": 1, "pen_date": "2026-09-01",
                          "value": 61.0}],
                        updated_by=1)
    pen = SR.read_pen_results(TEST_PID, SEASON, CYCLE)
    assert len(pen) == 1  # updated in place, not a second row
    assert int(pen.iloc[0]["id"]) == row_id
    assert pen.iloc[0]["value"] == 61.0


def test_save_movement_inserts_multiple_pitch_types_for_one_script():
    SR.save_movement(TEST_PID, SEASON, CYCLE, 1, [
        {"pitch_type": "Fastball", "pen_date": "2026-09-01", "hb": 8.0, "ivb": 15.0},
        {"pitch_type": "Slider", "pen_date": "2026-09-01", "hb": 3.0, "ivb": -2.0},
        {"pitch_type": "", "pen_date": "2026-09-01", "hb": 1.0, "ivb": 1.0},  # dropped
        {"pitch_type": "Curveball", "pen_date": "2026-09-01", "hb": None, "ivb": None},  # dropped
    ], updated_by=1)
    mv = SR.read_movement(TEST_PID, SEASON, CYCLE, 1).sort_values("pitch_type")
    assert len(mv) == 2
    assert set(mv["pitch_type"]) == {"Fastball", "Slider"}
    assert mv["id"].notna().all()

    # a different script_number is a completely separate set
    assert SR.read_movement(TEST_PID, SEASON, CYCLE, 2).empty


def test_save_movement_soft_deletes_omitted_rows_and_they_are_restorable():
    SR.save_movement(TEST_PID, SEASON, CYCLE, 1, [
        {"pitch_type": "Fastball", "pen_date": "2026-09-01", "hb": 8.0, "ivb": 15.0},
        {"pitch_type": "Slider", "pen_date": "2026-09-01", "hb": 3.0, "ivb": -2.0},
    ], updated_by=1)
    active = SR.read_movement(TEST_PID, SEASON, CYCLE, 1)
    kept, removed = active.iloc[0], active.iloc[1]

    SR.save_movement(TEST_PID, SEASON, CYCLE, 1, [
        {"id": int(kept["id"]), "pitch_type": kept["pitch_type"], "pen_date": kept["pen_date"],
         "hb": kept["hb"], "ivb": kept["ivb"]},
    ], updated_by=1)
    still_active = SR.read_movement(TEST_PID, SEASON, CYCLE, 1)
    assert len(still_active) == 1 and still_active.iloc[0]["id"] == kept["id"]
    deleted = SR.read_deleted_movement(TEST_PID, SEASON, CYCLE, 1)
    assert len(deleted) == 1 and deleted.iloc[0]["id"] == removed["id"]

    SR.restore_movement_row(int(removed["id"]), updated_by=1)
    assert len(SR.read_movement(TEST_PID, SEASON, CYCLE, 1)) == 2
    assert SR.read_deleted_movement(TEST_PID, SEASON, CYCLE, 1).empty


def test_read_all_movement_batches_all_six_scripts():
    SR.save_movement(TEST_PID, SEASON, CYCLE, 1,
                     [{"pitch_type": "Fastball", "pen_date": "2026-09-01", "hb": 8.0, "ivb": 15.0}],
                     updated_by=1)
    by_script = SR.read_all_movement(TEST_PID, SEASON, CYCLE)
    assert set(by_script) == set(range(1, SR.N_SCRIPTS + 1))
    assert len(by_script[1]) == 1
    assert by_script[2].empty


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
        movement_rows={1: [{"pitch_type": "Fastball", "pen_date": "2026-09-01",
                            "hb": 8.0, "ivb": 15.0}]},
        updated_by=1,
    )
    assert SR.read_plan(TEST_PID, SEASON, CYCLE)["vision_statement"] == "Focus"
    eng = SR.read_engine_metrics(TEST_PID, SEASON, CYCLE)
    assert eng[eng.metric_key == "ER"].iloc[0]["now_value"] == 35.0
    assert len(SR.read_gas_station(TEST_PID, SEASON, CYCLE)) == 1
    assert SR.read_scripts(TEST_PID, SEASON, CYCLE).iloc[0]["goal"] == "G1"
    assert SR.read_script_rows(TEST_PID, SEASON, CYCLE, 1).iloc[0]["pitch_type"] == "FB"
    assert len(SR.read_pen_results(TEST_PID, SEASON, CYCLE)) == 1
    assert len(SR.read_movement(TEST_PID, SEASON, CYCLE, 1)) == 1


def test_feet_drill_and_strength_need_options_are_nonempty_and_deduped():
    assert len(SR.FEET_DRILL_OPTIONS) == len(set(SR.FEET_DRILL_OPTIONS)) > 50
    assert len(SR.STRENGTH_NEED_OPTIONS) == 8


_TEST_DRILL_NAME = "__test_sandbox_drill__"


@pytest.fixture
def _clean_drill_catalog():
    yield
    with get_engine().begin() as conn:
        conn.execute(text(f"DELETE FROM {SR.DRILL_CATALOG_TABLE} WHERE name = :n"),
                    {"n": _TEST_DRILL_NAME})


def test_drill_catalog_seeded_add_deactivate_roundtrip(_clean_drill_catalog):
    # Seeded from the original FEET_DRILL_OPTIONS on first read.
    seeded = SR.read_drill_options()
    assert set(SR.FEET_DRILL_OPTIONS).issubset(set(seeded))
    assert _TEST_DRILL_NAME not in seeded

    SR.add_drill_option(_TEST_DRILL_NAME, created_by=1)
    assert _TEST_DRILL_NAME in SR.read_drill_options()

    SR.deactivate_drill_option(_TEST_DRILL_NAME)
    active = SR.read_drill_options()
    inactive = SR.read_drill_options(active_only=False)
    assert _TEST_DRILL_NAME not in active
    assert _TEST_DRILL_NAME in inactive  # soft-delete, row still exists

    # re-adding reactivates the same row rather than erroring on the
    # UNIQUE(name) constraint
    SR.add_drill_option(_TEST_DRILL_NAME, created_by=1)
    assert _TEST_DRILL_NAME in SR.read_drill_options()


def test_add_drill_option_ignores_blank_name(_clean_drill_catalog):
    before = len(SR.read_drill_options(active_only=False))
    SR.add_drill_option("   ")
    assert len(SR.read_drill_options(active_only=False)) == before


@pytest.fixture
def _clean_videos():
    yield
    with get_engine().begin() as conn:
        conn.execute(text(f"DELETE FROM {SR.VIDEOS_TABLE} WHERE title LIKE '__test_sandbox%'"))


def test_video_library_add_get_list_deactivate_roundtrip(_clean_videos):
    vid_id = SR.add_video("__test_sandbox_clip__", "Recovery", "video/mp4", b"fake-bytes",
                          created_by=1)
    fetched = SR.get_video(vid_id)
    assert fetched["title"] == "__test_sandbox_clip__" and fetched["data"] == b"fake-bytes"

    listed = SR.list_videos(category="Recovery")
    assert vid_id in set(listed["id"])
    assert "data" not in listed.columns  # listing never pulls the blob

    SR.deactivate_video(vid_id)
    assert SR.get_video(vid_id) is None  # get_video only returns active rows
    assert vid_id not in set(SR.list_videos(category="Recovery")["id"])


def test_add_video_rejects_bad_category_and_oversized_file(_clean_videos):
    with pytest.raises(ValueError):
        SR.add_video("__test_sandbox_bad_cat__", "NotACategory", "video/mp4", b"x")
    with pytest.raises(ValueError):
        SR.add_video("__test_sandbox_too_big__", "Recovery", "video/mp4",
                     b"x" * (SR.MAX_VIDEO_BYTES + 1))


def test_gas_station_video_drill_category_roundtrip_and_filter(_clean_videos):
    SR.add_video("__test_sandbox_elbow_clip__", "Gas Station", "video/mp4", b"x",
                created_by=1, drill_category="Elbow Strength")
    SR.add_video("__test_sandbox_rehab_clip__", "Gas Station", "video/mp4", b"x",
                created_by=1, drill_category="Rehab")
    SR.add_video("__test_sandbox_uncategorized_clip__", "Gas Station", "video/mp4", b"x",
                created_by=1)  # no drill_category -- still a valid Gas Station upload

    gas = SR.list_videos(category="Gas Station")
    by_title = gas.set_index("title")
    assert by_title.loc["__test_sandbox_elbow_clip__", "drill_category"] == "Elbow Strength"
    assert by_title.loc["__test_sandbox_rehab_clip__", "drill_category"] == "Rehab"
    assert by_title.loc["__test_sandbox_uncategorized_clip__", "drill_category"] == ""

    # a Recovery upload is unaffected -- drill_category is Gas-Station-only
    SR.add_video("__test_sandbox_recovery_clip__", "Recovery", "video/mp4", b"x", created_by=1)
    recovery = SR.list_videos(category="Recovery")
    assert recovery.set_index("title").loc["__test_sandbox_recovery_clip__",
                                           "drill_category"] == ""


def test_add_video_rejects_unknown_drill_category(_clean_videos):
    with pytest.raises(ValueError):
        SR.add_video("__test_sandbox_bad_drill_cat__", "Gas Station", "video/mp4", b"x",
                    drill_category="Not A Real Category")


def test_pen_results_fig_plots_by_date_not_pen_number():
    """2026-09-16: chart x-axis switched from the sequential pen_number to
    the real pen_date -- confirm the trace actually carries dates, and that
    a row with no pen_date is excluded rather than crashing the chart."""
    df = pd.DataFrame([
        {"script_number": 1, "pen_number": 1, "pen_date": "2026-09-01", "value": 60.0},
        {"script_number": 1, "pen_number": 2, "pen_date": "2026-09-15", "value": 70.0},
        {"script_number": 2, "pen_number": 1, "pen_date": None, "value": 40.0},  # dropped
    ])
    fig = SC.pen_results_fig(df)
    assert len(fig.data) == 1  # only script 1 has a usable (dated) point
    trace = fig.data[0]
    assert list(trace.x) == [pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-15")]
    assert list(trace.y) == [60.0, 70.0]
    assert fig.layout.xaxis.title.text == "Date"


def test_pen_results_fig_parses_free_typed_us_date_format():
    """Real bug, reported live 2026-09-16: pen_date is a free-typed text
    cell, not a date picker -- a coach typing "9/16/26" (M/D/YY) instead of
    ISO left the chart's x-axis autoscaled to Jan 2000-2001 with the real
    2026 points invisible off to the right, looking like "no data" even
    though the table below clearly had rows. Confirms both formats land on
    the exact same parsed date."""
    df = pd.DataFrame([
        {"script_number": 1, "pen_number": 1, "pen_date": "9/16/26", "value": 50.0},
        {"script_number": 2, "pen_number": 1, "pen_date": "2026-09-16", "value": 55.0},
    ])
    fig = SC.pen_results_fig(df)
    assert len(fig.data) == 2
    for trace in fig.data:
        assert list(trace.x) == [pd.Timestamp("2026-09-16")]


def test_pen_results_fig_empty_when_no_dated_rows():
    df = pd.DataFrame([{"script_number": 1, "pen_number": 1, "pen_date": None, "value": 60.0}])
    fig = SC.pen_results_fig(df)
    assert fig.layout.annotations[0].text == "No pen results for this cycle yet."


def test_scripts_movement_fig_averages_per_script_and_pitch_type():
    """2026-09-16 round 2: the movement chart moved from a per-script detail
    view (one dot per pen session) to one shared chart averaging across ALL
    scripts -- one dot per (script, pitch_type), not per session."""
    movement_by_script = {
        "1": [
            {"pitch_type": "Fastball", "pen_date": "2026-09-01", "hb": 8.0, "ivb": 15.0},
            {"pitch_type": "Fastball", "pen_date": "2026-09-08", "hb": 10.0, "ivb": 17.0},
        ],
        "2": [
            {"pitch_type": "Slider", "pen_date": "2026-09-01", "hb": 3.0, "ivb": -2.0},
        ],
        "3": [],  # no movement logged -- contributes nothing, doesn't crash
    }
    fig = SC.scripts_movement_fig(movement_by_script)
    assert len(fig.data) == 2  # one trace per pitch type (Fastball, Slider)
    fb = next(t for t in fig.data if t.name == "Fastball")
    assert list(fb.x) == [9.0] and list(fb.y) == [16.0]  # averaged across 2 sessions
    assert list(fb.text) == ["S1"]  # labeled with its script number
    sl = next(t for t in fig.data if t.name == "Slider")
    assert list(sl.x) == [3.0] and list(sl.text) == ["S2"]
    assert fig.layout.xaxis.title.text == "HB (in)"
    assert fig.layout.yaxis.title.text == "IVB (in)"


def test_scripts_movement_fig_selected_filters_to_those_scripts():
    movement_by_script = {
        "1": [{"pitch_type": "Fastball", "pen_date": "2026-09-01", "hb": 8.0, "ivb": 15.0}],
        "2": [{"pitch_type": "Slider", "pen_date": "2026-09-01", "hb": 3.0, "ivb": -2.0}],
    }
    fig = SC.scripts_movement_fig(movement_by_script, selected=[1])
    assert len(fig.data) == 1
    assert fig.data[0].name == "Fastball"


def test_scripts_movement_fig_empty_when_no_rows():
    fig = SC.scripts_movement_fig({})
    assert fig.layout.annotations[0].text == "No movement logged for this script yet."


def test_add_video_link_roundtrip(_clean_videos):
    vid_id = SR.add_video_link("__test_sandbox_link_clip__", "Gas Station",
                               "https://drive.google.com/file/d/abc123/view",
                               created_by=1, drill_category="Rehab")
    listed = SR.list_videos(category="Gas Station")
    row = listed.set_index("id").loc[vid_id]
    assert row["link_url"] == "https://drive.google.com/file/d/abc123/view"
    assert row["drill_category"] == "Rehab"

    # get_video is upload-only -- a link video has no bytes to stream
    assert SR.get_video(vid_id) is None

    SR.deactivate_video(vid_id)
    assert vid_id not in set(SR.list_videos(category="Gas Station")["id"])


def test_add_video_link_rejects_blank_url_and_bad_category(_clean_videos):
    with pytest.raises(ValueError):
        SR.add_video_link("__test_sandbox_blank_link__", "Gas Station", "")
    with pytest.raises(ValueError):
        SR.add_video_link("__test_sandbox_bad_cat_link__", "NotACategory",
                          "https://drive.google.com/x")


def test_plan_and_script_rows_isolation_by_player_season_cycle():
    """Task 4: coaches reported every pitcher showing the exact same
    Pre-Throw/Post-Throw checklist text on Built on the Bluff and asked
    whether that's a save-isolation bug (stale caching / a save that isn't
    actually player-specific) or intentional shared content. Proves the
    persistence layer's composite key (player_id, season_label, cycle)
    actually isolates saves: four keys that each differ in exactly one
    part of the key get distinct plan text AND a distinct script-row value,
    then each key's read must come back with ONLY its own values -- never
    another key's, even the one that shares two of its three parts."""
    keys = [
        (ISO_PID_A, ISO_SEASON_A, "Fall"),
        (ISO_PID_B, ISO_SEASON_A, "Fall"),   # different player, same season/cycle
        (ISO_PID_A, ISO_SEASON_A, "Winter"), # same player, different cycle
        (ISO_PID_A, ISO_SEASON_B, "Fall"),   # same player, different season
    ]

    def plan_fields_for(i):
        return {
            "vision_statement": "", "training_goals": "",
            "pre_throw_checklist": f"pre-throw-{i}",
            "post_throw_checklist": f"post-throw-{i}",
            "feet_set": "", "feet_moving": "", "work_day": "",
            "recovery_video_url": "",
        }

    for i, (pid, season, cycle) in enumerate(keys):
        SR.upsert_plan(pid, season, cycle, plan_fields_for(i), updated_by=1)
        SR.upsert_all_script_rows(pid, season, cycle, {
            1: [{"row_num": 1, "pitch_type": f"pitch-{i}", "ball_info": "", "info": ""}],
        }, updated_by=1)

    for i, (pid, season, cycle) in enumerate(keys):
        plan = SR.read_plan(pid, season, cycle)
        assert plan["pre_throw_checklist"] == f"pre-throw-{i}"
        assert plan["post_throw_checklist"] == f"post-throw-{i}"
        rows = SR.read_all_script_rows(pid, season, cycle)[1]
        assert rows.iloc[0]["pitch_type"] == f"pitch-{i}"
        # not any OTHER key's values -- the actual isolation assertion
        for j, _ in enumerate(keys):
            if j != i:
                assert plan["pre_throw_checklist"] != f"pre-throw-{j}"
                assert plan["post_throw_checklist"] != f"post-throw-{j}"
