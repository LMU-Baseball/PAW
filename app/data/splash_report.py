"""Splash Report storage layer: coach-editable per-pitcher development plan.

Migrated from the "PD PLANS - Pitching" Google Sheet (one tab per pitcher per
training cycle: Fall/Winter/Spring, three times a season). Everything here is
keyed by (player_id, season_label, cycle) -- season_label is the existing
academic-year label (`app.data.seasons`, e.g. "2025/2026"); cycle is one of
CYCLES below. Six small tables, one per section of the page; all follow
`app.data.velo_board`'s exact idiom: `CREATE TABLE IF NOT EXISTS` with an
explicit composite PRIMARY KEY, `INSERT ... ON DUPLICATE KEY UPDATE` upserts,
the pooled RDS engine, `ensure_tables()` called lazily (never at import time).

Two tables (`splash_gas_station`, `splash_pen_results`) hold a variable
number of rows per key (a coach can add/delete rows in the UI), so those are
persisted by full REPLACE (delete-then-insert) rather than upsert-by-row --
upserting by row_num would leave stale rows behind whenever a row is
deleted in the UI. The other four have a fixed row shape (a fixed metric/
script/pitch-slot count) and are upserted by that fixed key instead.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import text

from app.db import get_engine, query_df

CYCLES: tuple[str, ...] = ("Fall", "Winter", "Spring")

PLANS_TABLE = "splash_plans"
ENGINE_TABLE = "splash_engine_metrics"
GAS_TABLE = "splash_gas_station"
SCRIPTS_TABLE = "splash_scripts"
SCRIPT_ROWS_TABLE = "splash_script_rows"
PEN_TABLE = "splash_pen_results"

N_SCRIPTS = 6
N_SCRIPT_ROWS = 12

STRENGTH_METRICS: tuple[str, ...] = ("IR", "ER", "Scaption", "Grip")
ROM_METRICS: tuple[str, ...] = ("IROM", "EROM", "TotalArc")
ENGINE_METRIC_KEYS: tuple[str, ...] = STRENGTH_METRICS + ROM_METRICS
ENGINE_METRIC_LABELS = {
    "IR": "IR", "ER": "ER", "Scaption": "Scaption", "Grip": "Grip",
    "IROM": "IROM", "EROM": "EROM", "TotalArc": "Total Arc",
}

# The sheet's inline Excel data-validation list for "Strength Needs"
# (PD PLANS - Pitching.xlsx, e.g. cell U12:U14 on the `behrens` tab) --
# The Gas Station's NEED column dropdown.
STRENGTH_NEED_OPTIONS: tuple[str, ...] = (
    "Mass", "Upper Body Strength", "Lower Body Strength", "Explosiveness",
    "Forearm Strength", "Core Control", "Lean Out", "Foot Speed",
)

# The sheet's drill-name catalog (PD PLANS - Pitching.xlsx, sheet `MENU`,
# column AA, cells AA3:AA300 -- the Excel data-validation source for the
# Feet Set / Feet Moving / Work Day rows on every player tab). Fixed
# reference list, not queried live; de-duplicated + sorted.
FEET_DRILL_OPTIONS: tuple[str, ...] = (
    "10-Toes Figure 8 (Blue x6)", "10-Toes Figure 8's (Blue x6)",
    "2-Step Shuffle Throws (Yellow/Baseball x4)", "2-Step Shuffle Throws (x5)",
    "Anterior Step Double Plays (Yellow/Baseball x4)",
    "Back to Wall Banch Reach x3 breaths", "Back to Wall Bench Reach 3X breaths",
    "CVB (Fwd Pull) x5 (2X)", "CVB - Drift (x5)", "CVB - Drive Leg (x5)",
    "CVB - Feed the Flaw (x5)", "Depth Box Drops (Yellow/Baseball x4)",
    "Ferm Drill (Yellow/Baseball x4)", "Figure 8 Rocker x5", "Fly’s",
    "Front Foot Elevated Saucers (Blue x6)",
    "Front-Foot Elevated Figure 8's (Blue x6)",
    "Front-Foot Elevated Rockers (Blue x6)", "Heel Wedge Dry Reps x5 (2X)",
    "Heel-Elevated Pitches (Yellow/Baseball x4)",
    "Hook 'Em - On Mound (Yellow/Baseball x4)",
    "Hook’Em (Yellow/Baseball x4)", "Lasso Throws (Blue x6)",
    "Lateral Arm Drags 5X breaths|side", "Lateral Arm Drags x 5 breaths/side",
    "Lateral Reach", "Lateral Step-Back (Yellow/Baseball x4)",
    "Med Ball Hugs x5 (2 sets)", "MedBall Depth Drop Shotput (x5)",
    "MedBall Double Hop Shotput (x5)", "MedBall FFE Figure 8 Shotput (x5)",
    "MedBall Hugs w/ Heel Elevated (x5)", "MedBall Hugs w/CVB Drift (x5)",
    "MedBall Split Stance Shotput (x5)", "MedBall Stepbacks Shotput (x5)",
    "MedBall Turn & Burn Shotput (x5)", "MedBall w/CVB Drift (x5)",
    "MedBall w/CVB Drive Leg (x5)", "MedBall w/CVB Feed the Flaw (x5)",
    "Partner Decels (Green x8)", "Pivot Picks (Blue x6)",
    "Posterior Step Double Plays (Yellow/Baseball x4)",
    "QB Armside Rollouts (Red x4)", "QB Gloveside Rollouts (Red x4)",
    "QB Stepups (Red x4)", "Quarter Squat w/ Reach",
    "Reverse Flys x3 (Left foot back)", "Reverse Throws (Green x8)",
    "Reverse Walkbacks x 5/side", "Roll-Ins (Yellow/Baseball x4)",
    "Rotational Step Back x4", "Rotational StepBack (Yellow/Baseball x4)",
    "Saucers w/ Front Foot Elevated (Blue x6)",
    "Split Stance Figure 8's (Blue x6)", "Throwing Walkbacks (Red x4)",
    "Turn & Burn (Yellow/Baseball x4)", "Turn & Burn - On Mound (Yellow/Baseball x4)",
    "Turn and Burns x4", "Walkbacks", "Walking Wind Up - On Mound (Yellow/Baseball x4)",
    "Walking Wind Up x4", "Walking Windup (Yellow/Baseball x4)",
    "Water Bag Foot Elevated Figure 8 (x5)", "Water Bag Hand Held Throws (2x 30 seconds)",
    "Water Bag Hop Back (Hot Feet) (x5)", "Water Bag Kettle Bell Carry (2x60 ft)",
    "Water Bag Lateral Step Back (x5)",
)

# ============================ SCHEMA ========================================

_PLANS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {PLANS_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        vision_statement     TEXT,
        training_goals       TEXT,
        pre_throw_checklist  TEXT,
        post_throw_checklist TEXT,
        feet_set        TEXT,
        feet_moving      TEXT,
        work_day        TEXT,
        recovery_video_url VARCHAR(512),
        updated_by      INT,
        updated_at      DATETIME,
        PRIMARY KEY (player_id, season_label, cycle)
    )"""
_PLAN_COLS = ("vision_statement", "training_goals", "pre_throw_checklist",
              "post_throw_checklist", "feet_set", "feet_moving", "work_day",
              "recovery_video_url")

_ENGINE_DDL = f"""
    CREATE TABLE IF NOT EXISTS {ENGINE_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        metric_key     VARCHAR(32) NOT NULL,
        base_value     FLOAT,
        now_value      FLOAT,
        updated_by     INT,
        updated_at     DATETIME,
        PRIMARY KEY (player_id, season_label, cycle, metric_key)
    )"""

_GAS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {GAS_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        row_num     INT NOT NULL,
        need           VARCHAR(128),
        exercise       VARCHAR(255),
        sets_reps      VARCHAR(64),
        notes          VARCHAR(255),
        updated_by     INT,
        updated_at     DATETIME,
        PRIMARY KEY (player_id, season_label, cycle, row_num)
    )"""

_SCRIPTS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {SCRIPTS_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        script_number  TINYINT NOT NULL,
        goal           VARCHAR(255),
        measurable     VARCHAR(255),
        updated_by     INT,
        updated_at     DATETIME,
        PRIMARY KEY (player_id, season_label, cycle, script_number)
    )"""

_SCRIPT_ROWS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {SCRIPT_ROWS_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        script_number  TINYINT NOT NULL,
        row_num     TINYINT NOT NULL,
        pitch_type     VARCHAR(64),
        ball_info      VARCHAR(64),
        info           VARCHAR(255),
        updated_by     INT,
        updated_at     DATETIME,
        PRIMARY KEY (player_id, season_label, cycle, script_number, row_num)
    )"""

_PEN_DDL = f"""
    CREATE TABLE IF NOT EXISTS {PEN_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        script_number  TINYINT NOT NULL,
        pen_number     INT NOT NULL,
        pen_date       VARCHAR(10),
        value          FLOAT,
        updated_by     INT,
        updated_at     DATETIME,
        PRIMARY KEY (player_id, season_label, cycle, script_number, pen_number)
    )"""

_ALL_DDL = (_PLANS_DDL, _ENGINE_DDL, _GAS_DDL, _SCRIPTS_DDL, _SCRIPT_ROWS_DDL, _PEN_DDL)


_TABLES_ENSURED = False


def ensure_tables(engine=None) -> None:
    """Idempotently create all six Splash Report tables -- but only pay for
    it once per process. Every read/write function below calls this first
    (same idiom as `app.data.velo_board`), and a `CREATE TABLE IF NOT EXISTS`
    is a full RDS round trip even when the table already exists (measured
    ~0.6-0.85s each against this DB). Without this guard, a single Splash
    Report page load calls this ~12 times (read_plan, pitcher_profile's
    callers, engine metrics, gas station, pen results, scripts, plus once
    per script's 12-row table) -- adding up to most of the page's reported
    load time for pure "does this table exist" checks whose answer never
    changes within a process. Mirrors `app/dashboards/__init__.py`'s
    `_CAULDRON_SEEDED` guard for the same reason.
    `engine=` is still honored on the first call (tests can pass a fresh
    one); a caller that genuinely needs to force a re-check (there is none
    today -- these tables are never dropped at runtime) can reset
    `_TABLES_ENSURED` directly."""
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    engine = engine or get_engine()
    with engine.begin() as conn:
        for ddl in _ALL_DDL:
            conn.execute(text(ddl))
    _TABLES_ENSURED = True


def cycle_for_date(d=None) -> str:
    """Fall (Aug-Nov) / Winter (Dec-Feb) / Spring (Mar-Jul) for a date --
    ONLY used to pick a sensible default Cycle dropdown value, never for
    date-range math (KPIs stay Season-scoped, independent of Cycle)."""
    d = date.fromisoformat(str(d)[:10]) if d else date.today()
    if d.month in (8, 9, 10, 11):
        return "Fall"
    if d.month in (12, 1, 2):
        return "Winter"
    return "Spring"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _clean(value):
    """Scrub NaN/NaT/''-> None; leave everything else as-is (mirrors
    velo_board._clean)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() != "" else None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _key_where(alias_prefix=""):
    return (f"{alias_prefix}player_id = :player_id AND "
            f"{alias_prefix}season_label = :season_label AND {alias_prefix}cycle = :cycle")


# ============================ PLAN (text sections) ==========================

def read_plan(player_id, season_label, cycle) -> dict:
    """The eight text fields for (player, season, cycle); "" for any column
    with no saved row yet (never None -- so a Textarea always gets a str)."""
    ensure_tables()
    df = query_df(
        f"SELECT * FROM {PLANS_TABLE} WHERE {_key_where()}",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})
    if df.empty:
        return {c: "" for c in _PLAN_COLS}
    r = df.iloc[0]
    return {c: ("" if pd.isna(r[c]) else str(r[c])) for c in _PLAN_COLS}


def upsert_plan(player_id, season_label, cycle, fields: dict, updated_by=None) -> None:
    ensure_tables()
    set_clause = ", ".join(f"{c} = VALUES({c})" for c in _PLAN_COLS) + \
        ", updated_by = VALUES(updated_by), updated_at = VALUES(updated_at)"
    cols = ", ".join(_PLAN_COLS)
    placeholders = ", ".join(f":{c}" for c in _PLAN_COLS)
    sql = text(f"""
        INSERT INTO {PLANS_TABLE}
            (player_id, season_label, cycle, {cols}, updated_by, updated_at)
        VALUES
            (:player_id, :season_label, :cycle, {placeholders}, :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE {set_clause}
    """)
    params = {"player_id": int(player_id), "season_label": season_label, "cycle": cycle,
              "updated_by": _clean(updated_by), "updated_at": _now()}
    for c in _PLAN_COLS:
        params[c] = _clean(fields.get(c))
    with get_engine().begin() as conn:
        conn.execute(sql, params)


# ============================ BUILDING THE ENGINE ===========================

def read_engine_metrics(player_id, season_label, cycle) -> pd.DataFrame:
    """One row per ENGINE_METRIC_KEYS entry (fixed order), base/now/delta.
    A metric with no saved row yet still shows a blank editable line."""
    ensure_tables()
    df = query_df(
        f"SELECT metric_key, base_value, now_value FROM {ENGINE_TABLE} "
        f"WHERE {_key_where()}",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})
    by_key = {r["metric_key"]: r for _, r in df.iterrows()} if not df.empty else {}
    rows = []
    for key in ENGINE_METRIC_KEYS:
        r = by_key.get(key)
        base = None if r is None or pd.isna(r["base_value"]) else float(r["base_value"])
        now = None if r is None or pd.isna(r["now_value"]) else float(r["now_value"])
        delta = round(now - base, 1) if (base is not None and now is not None) else None
        rows.append({"metric_key": key, "label": ENGINE_METRIC_LABELS[key],
                     "base_value": base, "now_value": now, "delta": delta})
    return pd.DataFrame(rows)


def upsert_engine_metrics(player_id, season_label, cycle, rows: list[dict],
                          updated_by=None) -> None:
    """`rows`: [{"metric_key", "base_value", "now_value"}, ...]. Rows for a
    metric outside ENGINE_METRIC_KEYS are ignored."""
    ensure_tables()
    sql = text(f"""
        INSERT INTO {ENGINE_TABLE}
            (player_id, season_label, cycle, metric_key, base_value, now_value,
             updated_by, updated_at)
        VALUES
            (:player_id, :season_label, :cycle, :metric_key, :base_value, :now_value,
             :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE base_value = VALUES(base_value),
            now_value = VALUES(now_value), updated_by = VALUES(updated_by),
            updated_at = VALUES(updated_at)
    """)
    now = _now()
    with get_engine().begin() as conn:
        for row in rows:
            key = row.get("metric_key")
            if key not in ENGINE_METRIC_KEYS:
                continue
            conn.execute(sql, {
                "player_id": int(player_id), "season_label": season_label, "cycle": cycle,
                "metric_key": key, "base_value": _clean(row.get("base_value")),
                "now_value": _clean(row.get("now_value")),
                "updated_by": _clean(updated_by), "updated_at": now,
            })


# ============================ VARIABLE-ROW TABLES ===========================
# (Gas Station + Pen Results: a coach can add/delete rows, so these persist
# by full REPLACE -- delete every row for this key, then insert the rows the
# UI currently holds -- rather than upsert-by-row, which would leave a
# deleted row behind forever.)

def _replace_rows(table: str, extra_cols: tuple, player_id, season_label, cycle,
                  rows: list[dict], updated_by=None) -> None:
    ensure_tables()
    now = _now()
    cols = ", ".join(extra_cols)
    placeholders = ", ".join(f":{c}" for c in extra_cols)
    insert_sql = text(f"""
        INSERT INTO {table} (player_id, season_label, cycle, {cols}, updated_by, updated_at)
        VALUES (:player_id, :season_label, :cycle, {placeholders}, :updated_by, :updated_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(text(f"DELETE FROM {table} WHERE {_key_where()}"),
                     {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})
        for row in rows:
            params = {"player_id": int(player_id), "season_label": season_label,
                      "cycle": cycle, "updated_by": _clean(updated_by), "updated_at": now}
            for c in extra_cols:
                params[c] = _clean(row.get(c))
            conn.execute(insert_sql, params)


def read_gas_station(player_id, season_label, cycle) -> pd.DataFrame:
    ensure_tables()
    return query_df(
        f"SELECT row_num, need, exercise, sets_reps, notes FROM {GAS_TABLE} "
        f"WHERE {_key_where()} ORDER BY row_num",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})


def replace_gas_station(player_id, season_label, cycle, rows: list[dict],
                        updated_by=None) -> None:
    """`rows`: [{"need","exercise","sets_reps","notes"}, ...] in display
    order; row_num is assigned from list position. A row where all four
    fields are blank is dropped (not persisted)."""
    kept = [r for r in rows if any(_clean(r.get(c)) is not None
                                   for c in ("need", "exercise", "sets_reps", "notes"))]
    for i, r in enumerate(kept, start=1):
        r["row_num"] = i
    _replace_rows(GAS_TABLE, ("row_num", "need", "exercise", "sets_reps", "notes"),
                 player_id, season_label, cycle, kept, updated_by)


def read_pen_results(player_id, season_label, cycle) -> pd.DataFrame:
    ensure_tables()
    return query_df(
        f"SELECT script_number, pen_number, pen_date, value FROM {PEN_TABLE} "
        f"WHERE {_key_where()} ORDER BY script_number, pen_number",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})


def replace_pen_results(player_id, season_label, cycle, rows: list[dict],
                        updated_by=None) -> None:
    """`rows`: [{"script_number","pen_date","value"}, ...]; pen_number is
    assigned per-script from row order (1st row for a script = pen 1, etc).
    A row missing script_number or value is dropped."""
    counters: dict = {}
    kept = []
    for r in rows:
        script_number = r.get("script_number")
        value = _clean(r.get("value"))
        if script_number in (None, "") or value is None:
            continue
        script_number = int(script_number)
        counters[script_number] = counters.get(script_number, 0) + 1
        kept.append({"script_number": script_number, "pen_number": counters[script_number],
                    "pen_date": r.get("pen_date"), "value": value})
    _replace_rows(PEN_TABLE, ("script_number", "pen_number", "pen_date", "value"),
                 player_id, season_label, cycle, kept, updated_by)


# ============================ SCRIPTS (fixed 1-6 / 1-12) ====================

def read_scripts(player_id, season_label, cycle) -> pd.DataFrame:
    """One row per script_number 1..N_SCRIPTS (fixed order), goal/measurable
    blank ("") for any script with no saved row yet."""
    ensure_tables()
    df = query_df(
        f"SELECT script_number, goal, measurable FROM {SCRIPTS_TABLE} WHERE {_key_where()}",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})
    by_num = {int(r["script_number"]): r for _, r in df.iterrows()} if not df.empty else {}
    rows = []
    for n in range(1, N_SCRIPTS + 1):
        r = by_num.get(n)
        rows.append({
            "script_number": n,
            "goal": "" if r is None or pd.isna(r["goal"]) else str(r["goal"]),
            "measurable": "" if r is None or pd.isna(r["measurable"]) else str(r["measurable"]),
        })
    return pd.DataFrame(rows)


def upsert_scripts(player_id, season_label, cycle, rows: list[dict], updated_by=None) -> None:
    """`rows`: [{"script_number","goal","measurable"}, ...]."""
    ensure_tables()
    sql = text(f"""
        INSERT INTO {SCRIPTS_TABLE}
            (player_id, season_label, cycle, script_number, goal, measurable,
             updated_by, updated_at)
        VALUES
            (:player_id, :season_label, :cycle, :script_number, :goal, :measurable,
             :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE goal = VALUES(goal), measurable = VALUES(measurable),
            updated_by = VALUES(updated_by), updated_at = VALUES(updated_at)
    """)
    now = _now()
    with get_engine().begin() as conn:
        for row in rows:
            n = row.get("script_number")
            if n is None or not (1 <= int(n) <= N_SCRIPTS):
                continue
            conn.execute(sql, {
                "player_id": int(player_id), "season_label": season_label, "cycle": cycle,
                "script_number": int(n), "goal": _clean(row.get("goal")),
                "measurable": _clean(row.get("measurable")),
                "updated_by": _clean(updated_by), "updated_at": now,
            })


def _reindex_script_rows(df: pd.DataFrame) -> pd.DataFrame:
    """df -> exactly N_SCRIPT_ROWS rows (1..12, fixed order), blank ("") for
    any row_num with no saved row. Shared by `read_script_rows` (one script)
    and `read_all_script_rows` (all six, batched)."""
    by_num = {int(r["row_num"]): r for _, r in df.iterrows()} if not df.empty else {}
    rows = []
    for n in range(1, N_SCRIPT_ROWS + 1):
        r = by_num.get(n)
        rows.append({
            "row_num": n,
            "pitch_type": "" if r is None or pd.isna(r["pitch_type"]) else str(r["pitch_type"]),
            "ball_info": "" if r is None or pd.isna(r["ball_info"]) else str(r["ball_info"]),
            "info": "" if r is None or pd.isna(r["info"]) else str(r["info"]),
        })
    return pd.DataFrame(rows)


def read_script_rows(player_id, season_label, cycle, script_number) -> pd.DataFrame:
    """One row per row_num 1..N_SCRIPT_ROWS (fixed order) for one script.
    Rendering all six scripts should use `read_all_script_rows` instead --
    one query beats six for that case."""
    ensure_tables()
    df = query_df(
        f"SELECT row_num, pitch_type, ball_info, info FROM {SCRIPT_ROWS_TABLE} "
        f"WHERE {_key_where()} AND script_number = :script_number",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle,
         "script_number": int(script_number)})
    return _reindex_script_rows(df)


def read_all_script_rows(player_id, season_label, cycle) -> dict:
    """{script_number: 12-row DataFrame} for ALL N_SCRIPTS scripts in ONE
    query -- the page renders all six at once, so this replaces what used
    to be six separate `read_script_rows` round trips with one."""
    ensure_tables()
    df = query_df(
        f"SELECT script_number, row_num, pitch_type, ball_info, info "
        f"FROM {SCRIPT_ROWS_TABLE} WHERE {_key_where()}",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle})
    by_script = ({n: g for n, g in df.groupby("script_number")} if not df.empty else {})
    return {n: _reindex_script_rows(by_script.get(n, pd.DataFrame(
        columns=["row_num", "pitch_type", "ball_info", "info"])))
            for n in range(1, N_SCRIPTS + 1)}


def upsert_script_rows(player_id, season_label, cycle, script_number, rows: list[dict],
                       updated_by=None) -> None:
    """`rows`: [{"row_num","pitch_type","ball_info","info"}, ...]."""
    ensure_tables()
    sql = text(f"""
        INSERT INTO {SCRIPT_ROWS_TABLE}
            (player_id, season_label, cycle, script_number, row_num,
             pitch_type, ball_info, info, updated_by, updated_at)
        VALUES
            (:player_id, :season_label, :cycle, :script_number, :row_num,
             :pitch_type, :ball_info, :info, :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE pitch_type = VALUES(pitch_type),
            ball_info = VALUES(ball_info), info = VALUES(info),
            updated_by = VALUES(updated_by), updated_at = VALUES(updated_at)
    """)
    now = _now()
    with get_engine().begin() as conn:
        for row in rows:
            n = row.get("row_num")
            if n is None or not (1 <= int(n) <= N_SCRIPT_ROWS):
                continue
            conn.execute(sql, {
                "player_id": int(player_id), "season_label": season_label, "cycle": cycle,
                "script_number": int(script_number), "row_num": int(n),
                "pitch_type": _clean(row.get("pitch_type")),
                "ball_info": _clean(row.get("ball_info")), "info": _clean(row.get("info")),
                "updated_by": _clean(updated_by), "updated_at": now,
            })


# ============================ ONE-CLICK SAVE ================================

def save_all(player_id, season_label, cycle, *, plan_fields=None, engine_rows=None,
            gas_rows=None, script_fields=None, script_pitch_rows=None, pen_rows=None,
            updated_by=None) -> None:
    """Persist every edited section in one call -- the page's single Save
    button. Every argument is optional so a caller/test can persist just one
    section; the callback always passes all of them.

    `script_fields`: {script_number: {"goal", "measurable"}}.
    `script_pitch_rows`: {script_number: [12 row dicts]}.
    """
    if plan_fields is not None:
        upsert_plan(player_id, season_label, cycle, plan_fields, updated_by=updated_by)
    if engine_rows is not None:
        upsert_engine_metrics(player_id, season_label, cycle, engine_rows,
                              updated_by=updated_by)
    if gas_rows is not None:
        replace_gas_station(player_id, season_label, cycle, gas_rows, updated_by=updated_by)
    if script_fields is not None:
        rows = [{"script_number": n, **fields} for n, fields in script_fields.items()]
        upsert_scripts(player_id, season_label, cycle, rows, updated_by=updated_by)
    if script_pitch_rows is not None:
        for script_number, rows in script_pitch_rows.items():
            upsert_script_rows(player_id, season_label, cycle, script_number, rows,
                              updated_by=updated_by)
    if pen_rows is not None:
        replace_pen_results(player_id, season_label, cycle, pen_rows, updated_by=updated_by)
