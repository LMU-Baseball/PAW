"""Phase 4 precalc layer: derived rollups the site reads instead of raw CAPS.

Principle: the site READS off precalc; only the rebuild job READS raw CAPS. The
rollups are rebuilt from the existing CAPS compute path (no metric is redefined
here), so precalc is always reproducible from CAPS -- not a second source of
truth. Refresh with `flask rebuild-precalc`; a daily cron will call it after each
pipeline load later.

This slice ships the hitting season rollup only (see
docs/superpowers/specs/2026-08-07-phase4-precalc-hitting-design.md).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from app.db import query_df, get_engine
from app.ingest.common import chunked_insert

HITTING_SEASON_TABLE = "precalc_hitting_player_season"

_HITTING_SEASON_DDL = f"""
CREATE TABLE IF NOT EXISTS {HITTING_SEASON_TABLE} (
    batter_id    BIGINT PRIMARY KEY,
    batter_name  VARCHAR(128),
    qab_pct      DECIMAL(4,3) NULL,
    ba           VARCHAR(8),
    obp          VARCHAR(8),
    slg          VARCHAR(8),
    pa           INT,
    ab           INT,
    h            INT,
    doubles      INT,
    triples      INT,
    hr           INT,
    bb           INT,
    so           INT,
    season_label VARCHAR(32),
    built_at     DATETIME
)
"""


def ensure_tables(engine=None) -> None:
    """Idempotently create the precalc tables (no-op if they exist)."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(_HITTING_SEASON_DDL))


def rebuild_hitting(engine=None) -> int:
    """Full rebuild of the hitting season rollup from CAPS. Returns rows written.

    Recomputes every LMU hitter via hitting_caps._compute_season_rollup (the
    single source of truth), then replaces the table (DELETE + chunked_insert).
    Idempotent. The brief empty window between DELETE and insert is covered by
    the readers' compute fallback, so a concurrent read is never wrong.
    """
    from app.data import hitting_caps  # lazy: hitting_caps imports precalc (reader)

    engine = engine or get_engine()
    ensure_tables(engine)
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    hitters = hitting_caps.lmu_hitters()
    rows = []
    for bid in hitters["BatterId"]:
        row = hitting_caps._compute_season_rollup(int(bid))
        row["built_at"] = built_at
        rows.append(row)
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {HITTING_SEASON_TABLE}"))
    if rows:
        chunked_insert(engine, HITTING_SEASON_TABLE, rows)
    return len(rows)


def read_hitting_season(batter_id) -> dict | None:
    """One precalc row for a batter as a dict, or None if absent/table missing."""
    try:
        df = query_df(
            f"SELECT * FROM {HITTING_SEASON_TABLE} WHERE batter_id = :b",
            {"b": int(batter_id)})
    except Exception:
        return None  # table not built yet -> caller falls back to compute
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    q = row.get("qab_pct")
    row["qab_pct"] = None if q is None or pd.isna(q) else float(q)
    return row
