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

_DDL = {
    HITTING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {HITTING_SEASON_TABLE} (
            batter_id    BIGINT PRIMARY KEY,
            batter_name  VARCHAR(128),
            qab_pct      DECIMAL(4,3) NULL,
            ba VARCHAR(8), obp VARCHAR(8), slg VARCHAR(8),
            pa INT, ab INT, h INT, doubles INT, triples INT, hr INT, bb INT, so INT,
            season_label VARCHAR(32),
            built_at     DATETIME
        )""",
    PITCHING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {PITCHING_SEASON_TABLE} (
            pitcher_id   BIGINT PRIMARY KEY,
            pitcher_name VARCHAR(128),
            appearances VARCHAR(8), ip VARCHAR(8), k_pct VARCHAR(8),
            bb_pct VARCHAR(8), barrel_pct VARCHAR(8),
            min_date VARCHAR(16), max_date VARCHAR(16),
            built_at     DATETIME
        )""",
    CATCHING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {CATCHING_SEASON_TABLE} (
            catcher_id   BIGINT PRIMARY KEY,
            catcher_name VARCHAR(128),
            games VARCHAR(8), pitches VARCHAR(8),
            net_strikes VARCHAR(8), steal_pct VARCHAR(8),
            built_at     DATETIME
        )""",
}


def ensure_tables(engine=None) -> None:
    """Idempotently create all precalc tables (no-op if they exist)."""
    engine = engine or get_engine()
    with engine.begin() as conn:
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
    cache.clear_all()  # readers re-query fresh CAPS after a rebuild
    return len(rows)


def _build_rows(engine, ids, compute) -> list[dict]:
    """Compute one rollup dict per id, tagged with built_at. RDS can drop a
    connection mid-run over a long rebuild (~minutes); on OperationalError,
    dispose the stale pool and retry that id on a fresh connection (up to 3x) so
    a transient drop doesn't abort the whole rebuild / the daily cron."""
    cache.clear_all()  # compute from fresh CAPS, never a stale in-process cache
    built = _now()
    rows = []
    for i in ids:
        for attempt in range(3):
            try:
                rows.append({**compute(int(i)), "built_at": built})
                break
            except OperationalError:
                if attempt == 2:
                    raise
                engine.dispose()  # drop stale pooled connections; retry fresh
    return rows


def _read_one(table: str, key_col: str, key) -> dict | None:
    """One precalc row as a dict, or None if absent / table not built yet."""
    try:
        df = query_df(f"SELECT * FROM {table} WHERE {key_col} = :k", {"k": int(key)})
    except Exception:
        return None
    return None if df.empty else df.iloc[0].to_dict()


# ---- hitting ---------------------------------------------------------------

def rebuild_hitting(engine=None) -> int:
    from app.data import hitting_caps  # lazy: hitting_caps imports precalc (reader)
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_rows(engine, hitting_caps.lmu_hitters()["BatterId"],
                       hitting_caps._compute_season_rollup)
    return _replace_rows(engine, HITTING_SEASON_TABLE, rows)


def read_hitting_season(batter_id) -> dict | None:
    row = _read_one(HITTING_SEASON_TABLE, "batter_id", batter_id)
    if row is not None:
        q = row.get("qab_pct")
        row["qab_pct"] = None if q is None or pd.isna(q) else float(q)
    return row


# ---- pitching --------------------------------------------------------------

def rebuild_pitching(engine=None) -> int:
    from app.data import pitching_caps
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_rows(engine, pitching_caps.lmu_pitchers()["PitcherId"],
                       pitching_caps._compute_season_rollup)
    return _replace_rows(engine, PITCHING_SEASON_TABLE, rows)


def read_pitching_season(pitcher_id) -> dict | None:
    return _read_one(PITCHING_SEASON_TABLE, "pitcher_id", pitcher_id)


# ---- catching --------------------------------------------------------------

def rebuild_catching(engine=None) -> int:
    from app.data import catching_caps
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_rows(engine, catching_caps.lmu_catchers()["CatcherId"],
                       catching_caps._compute_season_rollup)
    return _replace_rows(engine, CATCHING_SEASON_TABLE, rows)


def read_catching_season(catcher_id) -> dict | None:
    return _read_one(CATCHING_SEASON_TABLE, "catcher_id", catcher_id)


def rebuild_all(engine=None) -> dict:
    engine = engine or get_engine()
    return {"hitting": rebuild_hitting(engine),
            "pitching": rebuild_pitching(engine),
            "catching": rebuild_catching(engine)}
