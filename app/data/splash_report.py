"""Built on the Bluff storage layer: coach-editable per-pitcher development plan.

Migrated from the "PD PLANS - Pitching" Google Sheet (one tab per pitcher per
training cycle: Fall/Winter/Spring, three times a season). Everything here is
keyed by (player_id, season_label, cycle) -- season_label is the existing
academic-year label (`app.data.seasons`, e.g. "2025/2026"); cycle is one of
CYCLES below. Six small tables, one per section of the page; all follow
`app.data.velo_board`'s exact idiom: `CREATE TABLE IF NOT EXISTS` with an
explicit composite PRIMARY KEY, `INSERT ... ON DUPLICATE KEY UPDATE` upserts,
the pooled RDS engine, `ensure_tables()` called lazily (never at import time).

`splash_gas_station` holds a variable number of rows per key (a coach can
add/delete rows in the UI), persisted by full REPLACE (delete-then-insert)
rather than upsert-by-row -- upserting by row_num would leave stale rows
behind whenever a row is deleted in the UI. There's no history concept for
Gas Station (just "what's the current exercise list"), so losing a removed
row is fine.

`splash_pen_results` is also variable-row, but a coach removing an old pen
result IS a real, permanent-feeling loss (it's the raw data behind the
Script Pen Results trend graph) -- so unlike Gas Station, it's never hard-
deleted. Each reading has a stable surrogate `id` and an `active` flag;
`save_pen_results` soft-deletes (active=0) whatever the coach removed from
the table instead of dropping it, and `restore_pen_result` flips one back.
`pen_number` (the trend chart's x-axis) is derived at read time from each
script's active rows ordered by date, not stored -- storing it as an
identity column made a row's "identity" shift every time a sibling row was
deleted, which is what made safe soft-delete/restore impossible before this.

The other four tables (splash_plans, splash_engine_readings, splash_scripts,
splash_script_rows) have a fixed row shape (a fixed metric/script/pitch-slot
count, or a single row per key) and are upserted by that fixed key instead.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import text

from app.db import get_engine, query_df

CYCLES: tuple[str, ...] = ("Fall", "Winter", "Spring")

PLANS_TABLE = "splash_plans"
# Superseded by READINGS_TABLE (2026-09-10 planning session -- one Base/Now
# pair per metric couldn't represent the every-2-week reassessment cadence
# coaches actually use). Left in _ALL_DDL/ensure_tables so a pre-existing
# deployment doesn't error, but no code reads or writes it anymore -- same
# "known dead table" status as GAMES_v1/v2 (see docs/DATABASE.md). Its rows
# were migrated into READINGS_TABLE by scripts/migrate_splash_engine_history.py.
ENGINE_TABLE = "splash_engine_metrics"
READINGS_TABLE = "splash_engine_readings"
GAS_TABLE = "splash_gas_station"
SCRIPTS_TABLE = "splash_scripts"
SCRIPT_ROWS_TABLE = "splash_script_rows"
PEN_TABLE = "splash_pen_results"
DRILL_CATALOG_TABLE = "splash_drill_catalog"
VIDEOS_TABLE = "splash_videos"

# Video categories for the titled-link library (2026-09-10 planning
# session): Recovery Protocols and Gas Station each get their own shared
# list, coach-managed, shown to every player rather than curated per plan
# (matches "Brad to add to database as named links" -- an admin action, not
# a per-player one).
VIDEO_CATEGORIES: tuple[str, ...] = ("Recovery", "Gas Station")

# Video bytes are stored as a DB BLOB for now (splash_videos.data) rather
# than on local disk -- this app is still on Render's free tier, whose disk
# is ephemeral and wiped on every redeploy (this repo auto-deploys on every
# push to main), and has no S3 write access today. Revisit once the AWS
# Lightsail migration lands a real persistent disk (see memory). Capped
# per-file to keep a handful of drill/recovery clips from bloating the RDS
# instance.
MAX_VIDEO_BYTES = 150 * 1024 * 1024  # 150 MB

N_SCRIPTS = 6
N_SCRIPT_ROWS = 12

STRENGTH_METRICS: tuple[str, ...] = ("IR", "ER", "Scaption", "Grip")
# "ScaptionROM" added 2026-09-14 (Brad: "we will be measuring Scaption ROM
# as well, not just strength") -- placed after EROM, matching where Brad
# wants it read in both the Building the Engine table and the body-visual
# readout list.
ROM_METRICS: tuple[str, ...] = ("IROM", "EROM", "ScaptionROM", "TotalArc")
ENGINE_METRIC_KEYS: tuple[str, ...] = STRENGTH_METRICS + ROM_METRICS
ENGINE_METRIC_LABELS = {
    "IR": "IR", "ER": "ER", "Scaption": "Scaption", "Grip": "Grip",
    "IROM": "IROM", "EROM": "EROM", "ScaptionROM": "Scaption ROM",
    "TotalArc": "Total Arc",
}

# D1-average baseline per metric, the fixed reference line a player's Now
# value is color-flagged against (2026-09-10 planning session). Strength
# metrics (IR/ER/Scaption/Grip) are in lb, ROM metrics (IROM/EROM/TotalArc)
# in degrees -- Brad's rough thresholds ("~1-2 off = fine, ~5 = yellow, 10+
# = red") were given in lb terms, so the same absolute deltas are applied to
# ROM here too as a starting point; revisit once real ROM baselines are in
# hand.
#
# PLACEHOLDER VALUES (Brad said "go with those numbers" on 2026-09-10,
# after being told these are NOT LMU-specific): ballpark figures commonly
# cited in throwing-shoulder sports-medicine literature for competitive
# (college-level) overhead throwing athletes -- handheld-dynamometer
# strength and ROM measured at 90 deg abduction (the standard clinical
# position for this testing, e.g. Wilk et al.'s "total motion concept" --
# IROM + EROM totaling ~180 deg is the classic bilateral-symmetry target).
# These were NOT pulled from LMU's own testing protocol/device and are not
# validated against this program's actual normative data -- replace with
# real numbers from LMU's strength/athletic-training staff whenever
# available; nothing else about the color-flag wiring needs to change when
# that happens, just these seven values.
D1_BASELINES: dict[str, float | None] = {
    "IR": 30.0, "ER": 22.0, "Scaption": 22.0, "Grip": 115.0,
    "IROM": 50.0, "EROM": 130.0,
    # No placeholder baseline for Scaption ROM yet (2026-09-14, new metric --
    # unlike the other seven, Brad hasn't OK'd a starting number for this
    # one) -- `engine_flag`/the table/body-visual dot all already handle a
    # None baseline (no color flag, "-" shown) exactly like an unlogged
    # reading, so this is safe to leave blank until real guidance comes in.
    "ScaptionROM": None,
    "TotalArc": 180.0,
}
D1_YELLOW_DELTA = 5.0
D1_RED_DELTA = 10.0


def engine_flag(metric_key: str, now_value) -> str | None:
    """"red" / "yellow" / "ok" against D1_BASELINES[metric_key], or None if
    either the baseline or the player's Now value isn't known yet."""
    baseline = D1_BASELINES.get(metric_key)
    if baseline is None or now_value is None:
        return None
    try:
        if pd.isna(now_value):
            return None
    except (TypeError, ValueError):
        pass
    off = float(baseline) - float(now_value)
    if off >= D1_RED_DELTA:
        return "red"
    if off >= D1_YELLOW_DELTA:
        return "yellow"
    return "ok"

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

_READINGS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {READINGS_TABLE} (
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        metric_key     VARCHAR(32) NOT NULL,
        reading_date   VARCHAR(10) NOT NULL,
        value          FLOAT,
        updated_by     INT,
        updated_at     DATETIME,
        PRIMARY KEY (player_id, season_label, cycle, metric_key, reading_date)
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
        id             INT AUTO_INCREMENT PRIMARY KEY,
        player_id      BIGINT NOT NULL,
        season_label   VARCHAR(16) NOT NULL,
        cycle          VARCHAR(16) NOT NULL,
        script_number  TINYINT NOT NULL,
        pen_date       VARCHAR(10),
        value          FLOAT,
        active         TINYINT(1) NOT NULL DEFAULT 1,
        updated_by     INT,
        updated_at     DATETIME,
        KEY idx_pen_key (player_id, season_label, cycle, script_number, active)
    )"""

# Coach-managed catalog backing the Feet Set/Feet Moving/Work Day dropdowns
# (used to be the hardcoded FEET_DRILL_OPTIONS tuple -- see that constant's
# docstring). A coach can add new entries and deactivate old ones from the
# UI; deactivating never deletes the row, so a plan that already picked a
# now-inactive drill still displays its name (see read_plan/_bullet_view --
# drill names are stored as plain text on the plan, not a foreign key).
_DRILL_CATALOG_DDL = f"""
    CREATE TABLE IF NOT EXISTS {DRILL_CATALOG_TABLE} (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        name         VARCHAR(255) NOT NULL,
        active       TINYINT(1) NOT NULL DEFAULT 1,
        created_by   INT,
        created_at   DATETIME,
        UNIQUE KEY uq_splash_drill_name (name)
    )"""

# Shared, coach-managed video library (Recovery Protocols / Gas Station
# titled links -- see VIDEO_CATEGORIES). `data` holds the raw file bytes
# (see MAX_VIDEO_BYTES for why: no persistent disk on this deployment yet).
_VIDEOS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {VIDEOS_TABLE} (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        title        VARCHAR(255) NOT NULL,
        category     VARCHAR(32) NOT NULL,
        mimetype     VARCHAR(64),
        size_bytes   INT,
        data         LONGBLOB,
        active       TINYINT(1) NOT NULL DEFAULT 1,
        created_by   INT,
        created_at   DATETIME
    )"""

_ALL_DDL = (_PLANS_DDL, _ENGINE_DDL, _READINGS_DDL, _GAS_DDL, _SCRIPTS_DDL, _SCRIPT_ROWS_DDL,
           _PEN_DDL, _DRILL_CATALOG_DDL, _VIDEOS_DDL)


_TABLES_ENSURED = False


def ensure_tables(engine=None) -> None:
    """Idempotently create all six Built on the Bluff tables -- but only pay for
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


def _multi_row_upsert(table: str, key_cols: tuple, value_cols: tuple, rows: list[dict],
                      updated_by=None) -> None:
    """One `INSERT ... VALUES (row1), (row2), ... ON DUPLICATE KEY UPDATE`
    for N rows in a SINGLE round trip, instead of N separate `execute()`
    calls each paying the same RDS round-trip latency.

    Each dict in `rows` must carry every column in `key_cols` (e.g.
    player_id/season_label/cycle/script_number, already fully resolved by
    the caller -- passed through as-is, never scrubbed, since a key is
    never optional) and may carry columns in `value_cols` (the actual
    editable fields, `_clean()`-scrubbed the usual way). No-op on an empty
    `rows` (a valid, common case: nothing to save for this section).

    Measured against this DB: 72 individual per-row upserts (6 scripts x 12
    pitch rows) cost ~6.3s; the equivalent single multi-row statement costs
    a small fraction of that -- this was the dominant cost of the page's
    Save button."""
    if not rows:
        return
    ensure_tables()
    now = _now()
    cols = key_cols + value_cols
    value_groups, params = [], {}
    for i, row in enumerate(rows):
        placeholders = []
        for c in key_cols:
            key = f"{c}_{i}"
            params[key] = row[c]
            placeholders.append(f":{key}")
        for c in value_cols:
            key = f"{c}_{i}"
            params[key] = _clean(row.get(c))
            placeholders.append(f":{key}")
        params[f"updated_by_{i}"] = _clean(updated_by)
        params[f"updated_at_{i}"] = now
        placeholders.append(f":updated_by_{i}")
        placeholders.append(f":updated_at_{i}")
        value_groups.append("(" + ", ".join(placeholders) + ")")
    set_clause = ", ".join(f"{c} = VALUES({c})" for c in value_cols) + \
        ", updated_by = VALUES(updated_by), updated_at = VALUES(updated_at)"
    sql = text(f"""
        INSERT INTO {table} ({', '.join(cols)}, updated_by, updated_at)
        VALUES {', '.join(value_groups)}
        ON DUPLICATE KEY UPDATE {set_clause}
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, params)


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
# One reading per (metric, date) -- see READINGS_TABLE docstring at the top
# of this module. "Base" and "Now" are never stored directly; they're always
# derived from the reading history (earliest/latest in the cycle), so
# there's no way for a coach's correction to a past date to silently
# overwrite the trend the way a single mutable Base/Now pair could.

def read_engine_history(player_id, season_label, cycle) -> pd.DataFrame:
    """Every reading for (player, season, cycle), one row per (metric_key,
    reading_date) -- columns metric_key/reading_date/value, sorted for a
    trend chart (metric, then chronological). `cycle` is normally one of
    CYCLES, but also accepts a list of cycles -- the "View Cycles" multi-
    select on Building the Engine (2026-09-10 planning session: "fall,
    winter, spring, or full year") reads across more than one cycle at
    once this way; selecting all of CYCLES is what gives the "full year"
    view, so there's no separate literal "Full Year" option to maintain."""
    ensure_tables()
    cycles = [cycle] if isinstance(cycle, str) else list(cycle)
    if not cycles:
        return pd.DataFrame(columns=["metric_key", "reading_date", "value"])
    cph = ", ".join(f":c{i}" for i in range(len(cycles)))
    params = {"player_id": int(player_id), "season_label": season_label}
    params.update({f"c{i}": c for i, c in enumerate(cycles)})
    df = query_df(
        f"SELECT metric_key, reading_date, value FROM {READINGS_TABLE} "
        f"WHERE player_id = :player_id AND season_label = :season_label "
        f"AND cycle IN ({cph}) ORDER BY metric_key, reading_date",
        params)
    return df


def read_engine_metrics(player_id, season_label, cycle) -> pd.DataFrame:
    """One row per ENGINE_METRIC_KEYS entry (fixed order): base_value/
    base_date = earliest reading in `cycle` (or across all of `cycle` when
    it's a list -- see read_engine_history), now_value/now_date = latest,
    delta = now - base, flag = color flag on now_value vs D1_BASELINES (see
    `engine_flag`). A metric with no reading yet still shows a blank line."""
    hist = read_engine_history(player_id, season_label, cycle)
    by_key = ({k: g.sort_values("reading_date") for k, g in hist.groupby("metric_key")}
             if not hist.empty else {})
    rows = []
    for key in ENGINE_METRIC_KEYS:
        g = by_key.get(key)
        if g is None or g.empty:
            base_v = base_d = now_v = now_d = None
        else:
            first, last = g.iloc[0], g.iloc[-1]
            base_v = None if pd.isna(first["value"]) else float(first["value"])
            base_d = first["reading_date"]
            now_v = None if pd.isna(last["value"]) else float(last["value"])
            now_d = last["reading_date"]
        delta = round(now_v - base_v, 1) if (base_v is not None and now_v is not None) else None
        rows.append({"metric_key": key, "label": ENGINE_METRIC_LABELS[key],
                     "base_value": base_v, "base_date": base_d,
                     "now_value": now_v, "now_date": now_d, "delta": delta,
                     "d1_baseline": D1_BASELINES.get(key),
                     "flag": engine_flag(key, now_v)})
    return pd.DataFrame(rows)


def latest_engine_reading_date(player_id, season_label, cycle) -> str | None:
    """Most recent reading_date across ALL metrics for (player, season,
    cycle), or None if nothing's been logged yet -- drives the "last
    updated N days ago" hint next to the Update Readings control."""
    hist = read_engine_history(player_id, season_label, cycle)
    return None if hist.empty else str(hist["reading_date"].max())


def upsert_engine_readings(player_id, season_label, cycle, reading_date, rows: list[dict],
                           updated_by=None) -> None:
    """`rows`: [{"metric_key", "value"}, ...] for ONE `reading_date` (the
    Update Readings form submits all metrics for a single day at once).
    Rows for a metric outside ENGINE_METRIC_KEYS, or with a blank/None
    value, are dropped -- a coach leaving a field empty shouldn't create a
    reading for it. Re-submitting the same reading_date upserts that day's
    row in place (a same-day typo fix); a different reading_date always
    lands as a new row, so past readings are never touched."""
    pid, sl = int(player_id), season_label
    resolved = []
    for row in rows:
        key = row.get("metric_key")
        value = _clean(row.get("value"))
        if key not in ENGINE_METRIC_KEYS or value is None:
            continue
        resolved.append({"player_id": pid, "season_label": sl, "cycle": cycle,
                         "metric_key": key, "reading_date": str(reading_date),
                         "value": value})
    _multi_row_upsert(READINGS_TABLE,
                      ("player_id", "season_label", "cycle", "metric_key", "reading_date"),
                      ("value",), resolved, updated_by)


# ============================ VARIABLE-ROW TABLES ===========================
# (Gas Station + Pen Results: a coach can add/delete rows, so these persist
# by full REPLACE -- delete every row for this key, then insert the rows the
# UI currently holds -- rather than upsert-by-row, which would leave a
# deleted row behind forever.)

def _replace_rows(table: str, extra_cols: tuple, player_id, season_label, cycle,
                  rows: list[dict], updated_by=None) -> None:
    """DELETE then INSERT every row in ONE multi-row statement (one round
    trip for the insert, regardless of row count), both in the same
    transaction as the delete."""
    ensure_tables()
    now = _now()
    pid = int(player_id)
    with get_engine().begin() as conn:
        conn.execute(text(f"DELETE FROM {table} WHERE {_key_where()}"),
                     {"player_id": pid, "season_label": season_label, "cycle": cycle})
        if not rows:
            return
        cols = ("player_id", "season_label", "cycle") + extra_cols
        value_groups, params = [], {}
        for i, row in enumerate(rows):
            placeholders = [f":player_id_{i}", f":season_label_{i}", f":cycle_{i}"]
            params[f"player_id_{i}"] = pid
            params[f"season_label_{i}"] = season_label
            params[f"cycle_{i}"] = cycle
            for c in extra_cols:
                key = f"{c}_{i}"
                params[key] = _clean(row.get(c))
                placeholders.append(f":{key}")
            params[f"updated_by_{i}"] = _clean(updated_by)
            params[f"updated_at_{i}"] = now
            placeholders.append(f":updated_by_{i}")
            placeholders.append(f":updated_at_{i}")
            value_groups.append("(" + ", ".join(placeholders) + ")")
        insert_sql = text(f"""
            INSERT INTO {table} ({', '.join(cols)}, updated_by, updated_at)
            VALUES {', '.join(value_groups)}
        """)
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


def _read_pen_rows(player_id, season_label, cycle, *, active: bool) -> pd.DataFrame:
    ensure_tables()
    df = query_df(
        f"SELECT id, script_number, pen_date, value FROM {PEN_TABLE} "
        f"WHERE {_key_where()} AND active = :active "
        f"ORDER BY script_number, pen_date, id",
        {"player_id": int(player_id), "season_label": season_label, "cycle": cycle,
         "active": 1 if active else 0})
    if df.empty:
        return pd.DataFrame(columns=["id", "script_number", "pen_number", "pen_date", "value"])
    # pen_number is derived, not stored -- the chart's x-axis position within
    # each script, ranked by date (id breaks ties) among ACTIVE rows only.
    # Storing it made a row's identity shift whenever a sibling row was
    # deleted, which is exactly what made safe soft-delete/restore
    # impossible before this (see this module's docstring).
    df["pen_number"] = df.groupby("script_number").cumcount() + 1
    return df[["id", "script_number", "pen_number", "pen_date", "value"]]


def read_pen_results(player_id, season_label, cycle, *, active_only: bool = True) -> pd.DataFrame:
    """Columns: id/script_number/pen_number (derived)/pen_date/value.
    `active_only=True` (the default, used by the trend chart and the main
    editable table) excludes soft-deleted rows -- see
    `read_deleted_pen_results` for those."""
    return _read_pen_rows(player_id, season_label, cycle, active=bool(active_only))


def read_deleted_pen_results(player_id, season_label, cycle) -> pd.DataFrame:
    """The soft-deleted set for this key (same shape as `read_pen_results`)
    -- what the "Recently Removed" list / Restore action reads from."""
    return _read_pen_rows(player_id, season_label, cycle, active=False)


def save_pen_results(player_id, season_label, cycle, rows: list[dict],
                     updated_by=None) -> None:
    """`rows`: [{"id" (optional -- present for a pre-existing row the coach
    didn't remove, absent/None for a freshly-typed one), "script_number",
    "pen_date", "value"}, ...] -- the pen-results table's current `data`,
    exactly as the coach left it before hitting Save.

    Never hard-deletes. A previously-active row whose id is NOT present in
    `rows` was removed from the table by the coach -- it gets soft-deleted
    (active=0), not dropped, so `restore_pen_result` can bring it back. A
    row with an id IS present gets its fields updated. A row with no id (a
    blank row the coach filled in) gets inserted new. A row missing
    script_number or value is dropped from the submission entirely (same as
    before) -- for an EXISTING row that just means it also gets soft-deleted
    (its id won't appear as still-present either); a blank never-filled-in
    padding row simply isn't inserted."""
    ensure_tables()
    pid = int(player_id)
    submitted = []
    for r in rows:
        script_number = r.get("script_number")
        value = _clean(r.get("value"))
        if script_number in (None, "") or value is None:
            continue
        submitted.append({
            "id": r.get("id"), "script_number": int(script_number),
            "pen_date": _clean(r.get("pen_date")), "value": value,
        })

    existing = query_df(
        f"SELECT id FROM {PEN_TABLE} WHERE {_key_where()} AND active = 1",
        {"player_id": pid, "season_label": season_label, "cycle": cycle})
    existing_ids = set(existing["id"]) if not existing.empty else set()
    kept_ids = {int(r["id"]) for r in submitted if r.get("id") not in (None, "")}
    removed_ids = existing_ids - kept_ids

    now = _now()
    with get_engine().begin() as conn:
        for r in submitted:
            if r["id"] in (None, ""):
                conn.execute(text(f"""
                    INSERT INTO {PEN_TABLE}
                        (player_id, season_label, cycle, script_number, pen_date, value,
                         active, updated_by, updated_at)
                    VALUES (:player_id, :season_label, :cycle, :script_number, :pen_date,
                            :value, 1, :updated_by, :updated_at)
                """), {"player_id": pid, "season_label": season_label, "cycle": cycle,
                      "script_number": r["script_number"], "pen_date": r["pen_date"],
                      "value": r["value"], "updated_by": _clean(updated_by),
                      "updated_at": now})
            else:
                conn.execute(text(f"""
                    UPDATE {PEN_TABLE}
                       SET script_number = :script_number, pen_date = :pen_date,
                           value = :value, active = 1,
                           updated_by = :updated_by, updated_at = :updated_at
                     WHERE id = :id AND {_key_where()}
                """), {"id": int(r["id"]), "script_number": r["script_number"],
                      "pen_date": r["pen_date"], "value": r["value"],
                      "updated_by": _clean(updated_by), "updated_at": now,
                      "player_id": pid, "season_label": season_label, "cycle": cycle})
        if removed_ids:
            ph = ", ".join(f":rid{i}" for i in range(len(removed_ids)))
            params = {f"rid{i}": rid for i, rid in enumerate(removed_ids)}
            params.update({"player_id": pid, "season_label": season_label, "cycle": cycle})
            conn.execute(text(f"""
                UPDATE {PEN_TABLE} SET active = 0, updated_by = :updated_by,
                       updated_at = :updated_at
                 WHERE id IN ({ph}) AND {_key_where()}
            """), {**params, "updated_by": _clean(updated_by), "updated_at": now})


def restore_pen_result(row_id, updated_by=None) -> None:
    """Flips one soft-deleted row back to active=1 -- the "Restore" button
    next to an entry in the "Recently Removed" list."""
    ensure_tables()
    with get_engine().begin() as conn:
        conn.execute(text(f"""
            UPDATE {PEN_TABLE} SET active = 1, updated_by = :updated_by, updated_at = :updated_at
             WHERE id = :id
        """), {"id": int(row_id), "updated_by": _clean(updated_by), "updated_at": _now()})


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
    pid, sl = int(player_id), season_label
    resolved = [{"player_id": pid, "season_label": sl, "cycle": cycle,
                "script_number": int(row["script_number"]), "goal": row.get("goal"),
                "measurable": row.get("measurable")}
               for row in rows
               if row.get("script_number") is not None and 1 <= int(row["script_number"]) <= N_SCRIPTS]
    _multi_row_upsert(SCRIPTS_TABLE, ("player_id", "season_label", "cycle", "script_number"),
                      ("goal", "measurable"), resolved, updated_by)


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


def _resolve_script_rows(player_id, season_label, cycle, script_number, rows: list[dict]) -> list:
    pid = int(player_id)
    return [{"player_id": pid, "season_label": season_label, "cycle": cycle,
             "script_number": int(script_number), "row_num": int(row["row_num"]),
             "pitch_type": row.get("pitch_type"), "ball_info": row.get("ball_info"),
             "info": row.get("info")}
            for row in rows
            if row.get("row_num") is not None and 1 <= int(row["row_num"]) <= N_SCRIPT_ROWS]


def upsert_script_rows(player_id, season_label, cycle, script_number, rows: list[dict],
                       updated_by=None) -> None:
    """`rows`: [{"row_num","pitch_type","ball_info","info"}, ...] for ONE
    script. Saving all six scripts at once should use
    `upsert_all_script_rows` instead -- one round trip beats six."""
    resolved = _resolve_script_rows(player_id, season_label, cycle, script_number, rows)
    _multi_row_upsert(SCRIPT_ROWS_TABLE,
                      ("player_id", "season_label", "cycle", "script_number", "row_num"),
                      ("pitch_type", "ball_info", "info"), resolved, updated_by)


def upsert_all_script_rows(player_id, season_label, cycle, script_pitch_rows: dict,
                           updated_by=None) -> None:
    """`script_pitch_rows`: {script_number: [12 row dicts]} for ALL scripts
    being saved at once -- one multi-row statement covering every script's
    rows together (up to N_SCRIPTS * N_SCRIPT_ROWS = 72 rows), instead of
    one upsert per script (which was itself already one round trip per row
    before `_multi_row_upsert` -- see that function's docstring for the
    measured cost this replaces)."""
    resolved = []
    for script_number, rows in script_pitch_rows.items():
        resolved.extend(_resolve_script_rows(player_id, season_label, cycle, script_number, rows))
    _multi_row_upsert(SCRIPT_ROWS_TABLE,
                      ("player_id", "season_label", "cycle", "script_number", "row_num"),
                      ("pitch_type", "ball_info", "info"), resolved, updated_by)


# ============================ DRILL CATALOG ==================================

_DRILL_SEEDED = False


def _seed_drill_catalog() -> None:
    """One-time (per process) INSERT IGNORE of the old hardcoded
    FEET_DRILL_OPTIONS into the coach-managed catalog table, so switching
    the dropdown over to a DB-backed list doesn't blank out everyone's
    existing options on first deploy. Safe to call repeatedly -- IGNORE
    skips names already present (the UNIQUE KEY on `name`)."""
    global _DRILL_SEEDED
    if _DRILL_SEEDED:
        return
    ensure_tables()
    now = _now()
    value_groups, params = [], {}
    for i, name in enumerate(FEET_DRILL_OPTIONS):
        params[f"name_{i}"] = name
        params[f"created_at_{i}"] = now
        value_groups.append(f"(:name_{i}, 1, NULL, :created_at_{i})")
    sql = text(f"""
        INSERT IGNORE INTO {DRILL_CATALOG_TABLE} (name, active, created_by, created_at)
        VALUES {', '.join(value_groups)}
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, params)
    _DRILL_SEEDED = True


def read_drill_options(*, active_only: bool = True) -> list[str]:
    """Names for the Feet Set/Feet Moving/Work Day dropdowns, seeded from
    the original FEET_DRILL_OPTIONS list on first call, coach-editable
    (add_drill_option/deactivate_drill_option) after that."""
    _seed_drill_catalog()
    where = "WHERE active = 1" if active_only else ""
    df = query_df(f"SELECT name FROM {DRILL_CATALOG_TABLE} {where} ORDER BY name")
    return [] if df.empty else list(df["name"])


def add_drill_option(name: str, created_by=None) -> None:
    """Adds a new drill to the shared catalog (or reactivates it, if a
    coach previously deactivated a drill of the same name). Blank names are
    ignored."""
    name = (name or "").strip()
    if not name:
        return
    _seed_drill_catalog()
    sql = text(f"""
        INSERT INTO {DRILL_CATALOG_TABLE} (name, active, created_by, created_at)
        VALUES (:name, 1, :created_by, :created_at)
        ON DUPLICATE KEY UPDATE active = 1, created_by = VALUES(created_by),
                                created_at = VALUES(created_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {"name": name, "created_by": _clean(created_by), "created_at": _now()})


def deactivate_drill_option(name: str) -> None:
    """Soft-delete: hides `name` from future dropdown choices without
    touching any plan that already saved it as text."""
    _seed_drill_catalog()
    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE {DRILL_CATALOG_TABLE} SET active = 0 WHERE name = :name"),
                    {"name": name})


# ============================ VIDEO LIBRARY ==================================
# Shared, coach-managed titled-link library for Recovery Protocols / Gas
# Station (see VIDEO_CATEGORIES + MAX_VIDEO_BYTES above for why bytes live
# in the DB for now).

def list_videos(category: str | None = None, *, active_only: bool = True) -> pd.DataFrame:
    """id/title/category/size_bytes/created_at for the video library --
    never selects `data` (the blob) so listing stays cheap even with a lot
    of clips; fetch one clip's bytes with `get_video`."""
    ensure_tables()
    where = ["active = 1"] if active_only else []
    params = {}
    if category is not None:
        where.append("category = :category")
        params["category"] = category
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return query_df(
        f"SELECT id, title, category, size_bytes, created_at FROM {VIDEOS_TABLE} "
        f"{clause} ORDER BY created_at DESC", params)


def get_video(video_id) -> dict | None:
    """{"title","mimetype","data"} (raw bytes) for one video, or None if
    the id doesn't exist / was deactivated. Used only by the streaming
    route -- never loaded onto the page itself."""
    ensure_tables()
    df = query_df(
        f"SELECT title, mimetype, data FROM {VIDEOS_TABLE} WHERE id = :id AND active = 1",
        {"id": int(video_id)})
    if df.empty:
        return None
    r = df.iloc[0]
    return {"title": r["title"], "mimetype": r["mimetype"] or "video/mp4", "data": r["data"]}


def add_video(title: str, category: str, mimetype: str, data: bytes, created_by=None) -> int:
    """Stores one video's bytes; returns the new row's id. Raises
    ValueError for an oversized file or an unrecognized category --
    callers (the upload callback) should catch that and show it as a
    status message, not a stack trace."""
    if category not in VIDEO_CATEGORIES:
        raise ValueError(f"unknown video category: {category!r}")
    if not data:
        raise ValueError("no file data")
    if len(data) > MAX_VIDEO_BYTES:
        raise ValueError(f"file is {len(data) / 1e6:.0f} MB, over the "
                         f"{MAX_VIDEO_BYTES / 1e6:.0f} MB limit")
    ensure_tables()
    sql = text(f"""
        INSERT INTO {VIDEOS_TABLE} (title, category, mimetype, size_bytes, data, active,
                                    created_by, created_at)
        VALUES (:title, :category, :mimetype, :size_bytes, :data, 1, :created_by, :created_at)
    """)
    with get_engine().begin() as conn:
        result = conn.execute(sql, {
            "title": (title or "Untitled").strip() or "Untitled", "category": category,
            "mimetype": mimetype, "size_bytes": len(data), "data": data,
            "created_by": _clean(created_by), "created_at": _now(),
        })
        return int(result.lastrowid)


def deactivate_video(video_id) -> None:
    """Soft-delete: hides the video from the library without dropping the
    row (mirrors deactivate_drill_option)."""
    ensure_tables()
    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE {VIDEOS_TABLE} SET active = 0 WHERE id = :id"),
                    {"id": int(video_id)})


# ============================ ONE-CLICK SAVE ================================

def save_all(player_id, season_label, cycle, *, plan_fields=None,
            gas_rows=None, script_fields=None, script_pitch_rows=None, pen_rows=None,
            updated_by=None) -> None:
    """Persist every edited section in one call -- the page's single Save
    button. Every argument is optional so a caller/test can persist just one
    section; the callback always passes all of them.

    Building the Engine is deliberately NOT a `save_all` argument -- it has
    its own "Update Readings" action (`upsert_engine_readings`), separate
    from this Edit/Save flow, because a reading is a dated historical fact
    rather than a revisable field (see READINGS_TABLE docstring).

    `script_fields`: {script_number: {"goal", "measurable"}}.
    `script_pitch_rows`: {script_number: [12 row dicts]}.
    """
    if plan_fields is not None:
        upsert_plan(player_id, season_label, cycle, plan_fields, updated_by=updated_by)
    if gas_rows is not None:
        replace_gas_station(player_id, season_label, cycle, gas_rows, updated_by=updated_by)
    if script_fields is not None:
        rows = [{"script_number": n, **fields} for n, fields in script_fields.items()]
        upsert_scripts(player_id, season_label, cycle, rows, updated_by=updated_by)
    if script_pitch_rows is not None:
        upsert_all_script_rows(player_id, season_label, cycle, script_pitch_rows,
                               updated_by=updated_by)
    if pen_rows is not None:
        save_pen_results(player_id, season_label, cycle, pen_rows, updated_by=updated_by)
