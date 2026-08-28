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

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.data import pitching_caps
from app.data.roster_media import _norm_name
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


def placeholder_name(player_id) -> str | None:
    """"Last, First" for a negative placeholder id (-roster_id), or None if
    `player_id` is a real (non-negative) Trackman id, or the roster row no
    longer exists. Callers that resolve a display name from GAMES/BULLPEN
    (which has zero rows for a placeholder) should check this FIRST."""
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid >= 0:
        return None
    ensure_table()
    df = query_df(
        f"SELECT first_name, last_name FROM {TABLE} WHERE roster_id = :rid",
        {"rid": -pid})
    if df.empty:
        return None
    r = df.iloc[0]
    return f"{r['last_name']}, {r['first_name']}"


def placeholder_profile(player_id) -> dict | None:
    """{first_name, last_name, class_year, position} for a negative
    placeholder id, or None if not a placeholder / not found. For
    hitting_caps.player_profile's use -- unlike placeholder_name, callers
    here want the structured fields, not a formatted name string."""
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid >= 0:
        return None
    ensure_table()
    df = query_df(
        f"SELECT first_name, last_name, class_year, position FROM {TABLE} "
        f"WHERE roster_id = :rid", {"rid": -pid})
    if df.empty:
        return None
    return df.iloc[0].to_dict()


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


def placeholder_rows(season_label: str, groups: tuple[str, ...],
                     id_col: str, name_col: str) -> pd.DataFrame:
    """lmu_roster rows for `season_label` whose _position_group is in `groups`,
    shaped as a 2-column DataFrame [id_col, name_col] -- id = -roster_id,
    name = "Last, First" (matches GAMES.Pitcher/Batter/Catcher's own format)."""
    roster = load_roster(season_label)
    if roster.empty:
        return pd.DataFrame(columns=[id_col, name_col])
    sub = roster[roster["position"].map(_position_group).isin(groups)]
    if sub.empty:
        return pd.DataFrame(columns=[id_col, name_col])
    return pd.DataFrame({
        id_col: (-sub["roster_id"].astype(int)).values,
        name_col: (sub["last_name"] + ", " + sub["first_name"]).values,
    })


def union_with_roster(df: pd.DataFrame, season_label: str, groups: tuple[str, ...],
                      id_col: str, name_col: str) -> pd.DataFrame:
    """Append placeholder_rows() entries for any roster name not already
    present in df[name_col] (order/case/punctuation-insensitive match via
    roster_media._norm_name), then re-sort by name_col. Returns `df` itself,
    unchanged, when there's no placeholder to add. Real Trackman-derived rows
    always win: a placeholder is only ever added for a name with zero real
    rows this season."""
    ph = placeholder_rows(season_label, groups, id_col, name_col)
    if ph.empty:
        return df
    existing = {_norm_name(n) for n in df[name_col]} if not df.empty else set()
    ph = ph[~ph[name_col].map(_norm_name).isin(existing)]
    if ph.empty:
        return df
    out = pd.concat([df, ph], ignore_index=True, sort=False)
    return out.sort_values(name_col, kind="mergesort").reset_index(drop=True)


def reconcile_ids(season_label: str, engine=None) -> int:
    """Migrate any cauldron_teams/cauldron_daily/velo_board_entries/
    velo_board_overrides row saved against a pitcher placeholder id
    (-roster_id) over to that pitcher's real Trackman PitcherId, once one
    exists (matched by name). Idempotent: once migrated, a placeholder id no
    longer has any row referencing it, so re-running is a safe no-op. Only
    PITCHER placeholders are ever reconciled -- Cauldron and Velo Board are
    both pitcher-only systems (see _RECONCILE_TABLES); hitter/catcher
    placeholders never persist anywhere, so there's nothing to migrate for
    them. Returns the total number of rows migrated across all four tables.
    """
    engine = engine or get_engine()
    roster = load_roster(season_label)
    if roster.empty:
        return 0
    pitchers = roster[roster["position"].map(_position_group) == "pitcher"]
    if pitchers.empty:
        return 0
    # UNSCOPED (no start/end) -- per lmu_pitchers's own union logic, that
    # means placeholder rows (this function's own negative ids) are unioned
    # in too. Filter down to genuinely real (positive) Trackman ids only, or
    # every placeholder pitcher would match ITSELF by name in real_by_name
    # below and produce a self-referential no-op UPDATE ... SET col = -13
    # WHERE col = -13.
    real = pitching_caps.lmu_pitchers(season_label)
    if not real.empty:
        real = real[real["PitcherId"] > 0]
    real_by_name = {_norm_name(n): int(pid) for pid, n in
                    zip(real["PitcherId"], real["Pitcher"])} if not real.empty else {}

    migrated = 0
    with engine.begin() as conn:
        for _, r in pitchers.iterrows():
            key = _norm_name(f"{r['last_name']}, {r['first_name']}")
            real_id = real_by_name.get(key)
            if real_id is None:
                continue
            placeholder_id = -int(r["roster_id"])
            for table, col in _RECONCILE_TABLES:
                try:
                    with conn.begin_nested():
                        result = conn.execute(
                            text(f"UPDATE {table} SET {col} = :real WHERE {col} = :placeholder"),
                            {"real": real_id, "placeholder": placeholder_id})
                        migrated += result.rowcount
                except IntegrityError:
                    # A row already exists under the real id for this table's
                    # other key dimensions (e.g. a coach touched the real-id
                    # row before this ran) -- that row reflects more current
                    # state, so it wins: drop the now-stale placeholder row
                    # instead of leaving a collision that would recur forever.
                    logging.warning(
                        f"reconcile_ids: {table} collision for placeholder "
                        f"{placeholder_id} -> real {real_id}, dropping stale "
                        f"placeholder row")
                    with conn.begin_nested():
                        conn.execute(
                            text(f"DELETE FROM {table} WHERE {col} = :placeholder"),
                            {"placeholder": placeholder_id})
    return migrated
