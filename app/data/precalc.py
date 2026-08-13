"""Phase 4 precalc layer: derived rollups the site reads instead of raw CAPS.

Principle: the site READS off precalc; only the rebuild job READS raw CAPS. The
rollups are rebuilt from the existing CAPS compute path (no metric is redefined
here), so precalc is always reproducible from CAPS -- not a second source of
truth. Refresh with `flask rebuild-precalc`; a daily cron will call it after each
pipeline load later.

Three season rollups (one row per player), one per module:
  hitting  -> precalc_hitting_player_season   (kills the profiled full-season
              sidebar load; the big win)
  pitching -> precalc_pitching_player_season  (same full-season hotspot in
              range_summary)
  catching -> precalc_catching_player_season  (light: framing_season_tiles was
              already a cheap aggregate -- rollup kept for a uniform read path
              + the daily-cron story)
See docs/superpowers/specs/2026-08-07-phase4-precalc-hitting-design.md.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import query_df, get_engine
from app.ingest.common import chunked_insert
from app.data import cache

HITTING_SEASON_TABLE = "precalc_hitting_player_season"
PITCHING_SEASON_TABLE = "precalc_pitching_player_season"
CATCHING_SEASON_TABLE = "precalc_catching_player_season"
PRECALC_META_TABLE = "precalc_meta"

# Each season rollup is keyed by (player_id, season_label) so one row exists per
# player PER academic-year season -- picking a past season from the Season
# dropdown is a ~0.2s single-row read, not an on-the-fly compute. season_label
# is part of the PRIMARY KEY, so it must be NOT NULL.
_DDL = {
    HITTING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {HITTING_SEASON_TABLE} (
            batter_id    BIGINT NOT NULL,
            batter_name  VARCHAR(128),
            qab_pct      DECIMAL(4,3) NULL,
            ba VARCHAR(8), obp VARCHAR(8), slg VARCHAR(8),
            pa INT, ab INT, h INT, doubles INT, triples INT, hr INT, bb INT, so INT,
            season_label VARCHAR(32) NOT NULL,
            built_at     DATETIME,
            PRIMARY KEY (batter_id, season_label)
        )""",
    PITCHING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {PITCHING_SEASON_TABLE} (
            pitcher_id   BIGINT NOT NULL,
            pitcher_name VARCHAR(128),
            appearances VARCHAR(8), ip VARCHAR(8), k_pct VARCHAR(8),
            bb_pct VARCHAR(8), barrel_pct VARCHAR(8),
            min_date VARCHAR(16), max_date VARCHAR(16),
            season_label VARCHAR(32) NOT NULL,
            built_at     DATETIME,
            PRIMARY KEY (pitcher_id, season_label)
        )""",
    CATCHING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {CATCHING_SEASON_TABLE} (
            catcher_id   BIGINT NOT NULL,
            catcher_name VARCHAR(128),
            games VARCHAR(8), pitches VARCHAR(8),
            net_strikes VARCHAR(8), steal_pct VARCHAR(8),
            season_label VARCHAR(32) NOT NULL,
            built_at     DATETIME,
            PRIMARY KEY (catcher_id, season_label)
        )""",
    PRECALC_META_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {PRECALC_META_TABLE} (
            id INT PRIMARY KEY,
            version BIGINT,
            updated_at DATETIME
        )""",
}

# Expected PRIMARY-KEY columns per rollup table (for the drop-and-recreate
# migration off the old single-column-PK schema in ensure_tables).
_ROLLUP_PK = {
    HITTING_SEASON_TABLE: {"batter_id", "season_label"},
    PITCHING_SEASON_TABLE: {"pitcher_id", "season_label"},
    CATCHING_SEASON_TABLE: {"catcher_id", "season_label"},
}


def _bump_version(engine=None) -> None:
    """Increment the single-row data-version stamp (id=1). Called on every
    rebuild so a separate-process cron run signals web workers to invalidate."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO {PRECALC_META_TABLE} (id, version, updated_at) "
            f"VALUES (1, 1, :now) "
            f"ON DUPLICATE KEY UPDATE version = version + 1, updated_at = :now"),
            {"now": _now()})


def read_data_version(engine=None) -> int:
    """Current data-version (0 if the stamp/table doesn't exist yet)."""
    try:
        df = query_df(f"SELECT version FROM {PRECALC_META_TABLE} WHERE id = 1")
    except Exception:
        return 0
    return 0 if df.empty else int(df.iloc[0]["version"])


def _pk_columns(conn, table: str) -> set[str]:
    """Current PRIMARY-KEY column names of `table` (empty set if it has no PK /
    does not exist)."""
    rows = conn.execute(text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t "
        "AND CONSTRAINT_NAME = 'PRIMARY'"), {"t": table}).fetchall()
    return {r[0] for r in rows}


def ensure_tables(engine=None) -> None:
    """Idempotently create all precalc tables. Also migrates the rollup tables
    off the pre-per-season single-column PK: if a rollup table exists with a PK
    that isn't the (player_id, season_label) composite, DROP it so the CREATE
    below rebuilds it with the new schema. Safe -- these are derived caches, and
    the very next rebuild_* repopulates them."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        for table, expected_pk in _ROLLUP_PK.items():
            pk = _pk_columns(conn, table)
            if pk and pk != expected_pk:
                conn.execute(text(f"DROP TABLE {table}"))
        for ddl in _DDL.values():
            conn.execute(text(ddl))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _replace_rows(engine, table: str, rows: list[dict]) -> int:
    """Full replace: DELETE then chunked_insert. The brief empty window is
    covered by the readers' compute fallback. Returns rows written."""
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table}"))
    if rows:
        chunked_insert(engine, table, rows)
    cache.clear_all()  # readers re-query fresh CAPS after a rebuild (same process)
    _bump_version(engine)  # signal other processes (web workers) to invalidate
    return len(rows)


def _build_rows(engine, ids, compute, season) -> list[dict]:
    """Compute one rollup dict per id for one `season`, tagged with built_at. RDS
    can drop a connection mid-run over a long rebuild (~minutes); on
    OperationalError, dispose the stale pool and retry that id on a fresh
    connection (up to 3x) so a transient drop doesn't abort the whole rebuild /
    the daily cron. The caller clears the cache once before the season loop."""
    built = _now()
    rows = []
    for i in ids:
        for attempt in range(3):
            try:
                rows.append({**compute(int(i), season), "built_at": built})
                break
            except OperationalError:
                if attempt == 2:
                    raise
                engine.dispose()  # drop stale pooled connections; retry fresh
    return rows


def _build_all_seasons(engine, roster_fn, id_col, compute) -> list[dict]:
    """One rollup row per (player, season) across every season with data: for
    each `available_seasons()` label, take the season-scoped roster
    (`roster_fn(season)[id_col]`) and roll each player up for that season.

    The roster is deduped by NAME (one row per name spelling), so a player who
    appears under two name variants in a season would yield the same id twice --
    which would violate the (player_id, season_label) PK. drop_duplicates keeps
    exactly one rollup per (id, season)."""
    from app.data import seasons
    cache.clear_all()  # compute from fresh CAPS, never a stale in-process cache
    rows = []
    for season in seasons.available_seasons():
        ids = roster_fn(season)[id_col].drop_duplicates()
        rows += _build_rows(engine, ids, compute, season)
    return rows


def _read_one(table: str, key_col: str, key, season) -> dict | None:
    """One precalc row for (key, season) as a dict, or None if absent / table
    not built yet. `season` defaults to the current season."""
    from app.data import seasons
    season = season or seasons.current_season()
    try:
        df = query_df(
            f"SELECT * FROM {table} WHERE {key_col} = :k AND season_label = :s",
            {"k": int(key), "s": season})
    except Exception:
        return None
    return None if df.empty else df.iloc[0].to_dict()


# ---- hitting ---------------------------------------------------------------

def rebuild_hitting(engine=None) -> int:
    from app.data import hitting_caps  # lazy: hitting_caps imports precalc (reader)
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_all_seasons(engine, hitting_caps.lmu_hitters, "BatterId",
                              hitting_caps._compute_season_rollup)
    return _replace_rows(engine, HITTING_SEASON_TABLE, rows)


@cache.cached
def read_hitting_season(batter_id, season=None) -> dict | None:
    row = _read_one(HITTING_SEASON_TABLE, "batter_id", batter_id, season)
    if row is not None:
        q = row.get("qab_pct")
        row["qab_pct"] = None if q is None or pd.isna(q) else float(q)
    return row


# ---- pitching --------------------------------------------------------------

def rebuild_pitching(engine=None) -> int:
    from app.data import pitching_caps
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_all_seasons(engine, pitching_caps.lmu_pitchers, "PitcherId",
                              pitching_caps._compute_season_rollup)
    return _replace_rows(engine, PITCHING_SEASON_TABLE, rows)


@cache.cached
def read_pitching_season(pitcher_id, season=None) -> dict | None:
    return _read_one(PITCHING_SEASON_TABLE, "pitcher_id", pitcher_id, season)


# ---- catching --------------------------------------------------------------

def rebuild_catching(engine=None) -> int:
    from app.data import catching_caps
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_all_seasons(engine, catching_caps.lmu_catchers, "CatcherId",
                              catching_caps._compute_season_rollup)
    return _replace_rows(engine, CATCHING_SEASON_TABLE, rows)


def read_catching_season(catcher_id, season=None) -> dict | None:
    return _read_one(CATCHING_SEASON_TABLE, "catcher_id", catcher_id, season)


def rebuild_all(engine=None) -> dict:
    engine = engine or get_engine()
    return {"hitting": rebuild_hitting(engine),
            "pitching": rebuild_pitching(engine),
            "catching": rebuild_catching(engine)}
