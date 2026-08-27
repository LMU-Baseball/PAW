"""LMU-specific active-roster placeholders (name + class + position, no
Trackman id required) -- lets Cauldron, Velo Board, and the Hitting/Pitching/
Catching dropdowns list a season's whole roster before anyone on it has a
single tracked pitch or swing.

Distinct from the `roster_players` table (a nationwide recruiting scrape
across 71 D1 schools, refreshed by an unrelated pipeline, used only for
best-effort class-year/position bio lookups via
`app.data.hitting._roster_lookup`) -- `lmu_roster` is LMU-only, hand-seeded
from a committed per-season JSON file (see `scripts/load_lmu_roster.py`), and
is what actually drives the placeholder rows below.

Each `lmu_roster` row gets a NEGATIVE placeholder id (`-roster_id`) wherever a
player_id/pitcher_id column is needed -- Trackman ids are always positive
BIGINTs, so this can never collide, and it flows through every existing such
column untouched. Once a player's real Trackman id appears (they throw or hit
something tracked), `union_with_roster`'s name-based dedup makes the
placeholder disappear from every *read*, and `reconcile_ids` migrates any
*persisted* Cauldron/Velo Board rows saved against the placeholder over to
the real id.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from app.db import get_engine, query_df

TABLE = "lmu_roster"

_DDL = f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        roster_id     INT AUTO_INCREMENT PRIMARY KEY,
        season_label  VARCHAR(16)  NOT NULL,
        first_name    VARCHAR(64)  NOT NULL,
        last_name     VARCHAR(64)  NOT NULL,
        class_year    VARCHAR(16),
        position      VARCHAR(8),
        UNIQUE KEY uq_season_name (season_label, last_name, first_name)
    )"""

_PITCHER_POSITIONS = {"RHP", "LHP"}
_CATCHER_POSITIONS = {"C"}

# Tables that persist a value keyed by player_id/pitcher_id -- the only place
# a negative placeholder id can outlive a single request and need migrating
# once a real Trackman id appears. Both are pitcher-only systems (Cauldron: a
# pitching competition; Velo Board: fastball/sinker velo), so only PITCHER
# placeholders ever need reconcile_ids -- hitter/catcher placeholders are
# read fresh (and re-deduped by name) on every call, nothing to migrate.
_RECONCILE_TABLES = (
    ("cauldron_teams", "player_id"),
    ("cauldron_daily", "player_id"),
    ("velo_board_entries", "pitcher_id"),
    ("velo_board_overrides", "pitcher_id"),
)


def ensure_table(engine=None) -> None:
    """Idempotently create lmu_roster."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(_DDL))


def _position_group(position) -> str:
    """'pitcher' for RHP/LHP, 'catcher' for C, 'hitter' otherwise (including
    blank/unknown positions -- never silently drops a rostered player)."""
    p = (position or "").strip().upper()
    if p in _PITCHER_POSITIONS:
        return "pitcher"
    if p in _CATCHER_POSITIONS:
        return "catcher"
    return "hitter"


def load_roster(season_label: str) -> pd.DataFrame:
    """roster_id, first_name, last_name, class_year, position for a season,
    empty DataFrame (same columns) if none seeded yet."""
    ensure_table()
    return query_df(
        f"SELECT roster_id, first_name, last_name, class_year, position "
        f"FROM {TABLE} WHERE season_label = :s ORDER BY last_name, first_name",
        {"s": season_label},
    )


def upsert_season_roster(season_label: str, players: list[dict], engine=None) -> int:
    """Upsert each {first_name,last_name,class_year,position} dict for
    `season_label`, keyed on (season_label,last_name,first_name). A repeat
    run with an edited class_year/position updates that row IN PLACE -- same
    roster_id, so any -roster_id placeholder already saved against
    Cauldron/Velo Board data never shifts underneath it. Never deletes a
    player missing from `players` -- see scripts/load_lmu_roster.py, which
    reports (but does not act on) any such drop. Returns len(players)."""
    ensure_table(engine)
    engine = engine or get_engine()
    sql = text(f"""
        INSERT INTO {TABLE} (season_label, first_name, last_name, class_year, position)
        VALUES (:season_label, :first_name, :last_name, :class_year, :position)
        ON DUPLICATE KEY UPDATE class_year = VALUES(class_year), position = VALUES(position)
    """)
    with engine.begin() as conn:
        for p in players:
            conn.execute(sql, {
                "season_label": season_label,
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "class_year": p.get("class_year"),
                "position": p.get("position"),
            })
    return len(players)
