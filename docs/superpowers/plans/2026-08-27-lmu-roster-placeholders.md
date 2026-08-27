# LMU Roster Placeholders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Fall 2026/2027 LMU roster (47 players, name/class/position, zero Trackman data
yet) show up as the default roster everywhere in the app — Cauldron, Velo Board, and the
Hitting/Pitching/Catching dropdowns — and flip the site's default season to 2026/2027.

**Architecture:** A new `lmu_roster` DB table (hand-seeded from a committed JSON file) gives each
rostered player with no Trackman data yet a stable negative placeholder id. Three existing
`lmu_pitchers`/`lmu_hitters`/`lmu_catchers` query functions union those placeholder rows in,
deduped by name against real Trackman-derived rows, so a real id always wins the moment one
exists. A CLI-triggered reconciliation step migrates any Cauldron/Velo Board data a coach saved
against a placeholder over to the real id once it appears. `current_season()` is changed to always
default to today's calendar season.

**Tech Stack:** Python 3.12, Flask, pandas, SQLAlchemy (`app.db.query_df`/`get_engine`), MySQL
(RDS analytics DB), pytest, Click (Flask CLI).

**Spec:** `docs/superpowers/specs/2026-08-27-lmu-roster-placeholders-design.md`

## Global Constraints

- Follow existing patterns exactly: `ensure_table`/DDL/upsert idiom mirrors
  `app/data/cauldron.py` and `app/data/velo_board.py` (`CREATE TABLE IF NOT EXISTS` +
  `INSERT ... ON DUPLICATE KEY UPDATE`, `get_engine().begin()` for writes, `query_df` for reads).
- TDD: write/adjust tests first. Use `python -m pytest`, not bare `pytest`. Windows; Git Bash
  available; set `PYTHONIOENCODING=utf-8` for any script printing non-ASCII output.
- This suite runs against the LIVE analytics DB (no test-DB isolation — see `conftest.py`, and
  every existing `test_cauldron.py`/`test_velo_board.py` write test). Use an unmistakably-fake
  season label (`"1899/1900"`) for any new test that must guarantee zero real Trackman rows, and
  monkeypatch `query_df`/`load_roster` rather than depending on live data shape wherever a test
  needs a deterministic result. This matches how existing tests in these files already operate —
  read 2-3 neighboring tests in each file before adding new ones.
- **Baseline, captured before this work started:** `python -m pytest -q --ignore=tests/test_precalc.py`
  → **931 passed, 15 failed**, all 15 pre-existing and unrelated to this feature (`test_player_filter_access.py`
  9 failures, `test_practice.py` 4 failures, `test_velo_cauldron_save_live.py` 1 failure — HitTrax
  practice-layer and player-role-filter tests, nothing to do with rosters/seasons). Do NOT attempt
  to fix these. The bar for this plan is: 931 passing stays 931+ (net new tests all pass), and this
  exact same set of 15 pre-existing failures is the only thing still failing at the end — no new
  failures anywhere.
- Do not modify `app/data/called_strike.py`, `app/dashboards/velo_board/visual.py`,
  `app/dashboards/cauldron/visual.py`, or any static brand assets — off-limits per prior sessions'
  notes, unrelated to this work.
- No jersey/photo work, no changes to the nationwide `roster_players` scrape table, no
  cron/scheduled reconciliation, no two-way-player modeling — see spec §6.

---

### Task 1: `lmu_roster` core module

**Files:**
- Create: `app/data/lmu_roster.py`
- Test: `tests/test_lmu_roster.py`

**Interfaces:**
- Consumes: `app.data.roster_media._norm_name`, `app.db.get_engine`/`query_df`. (NOT
  `pitching_caps` yet — that module-level import is added in Task 7, the first task that actually
  uses it (`reconcile_ids`). Adding it here in Task 1 would be an unused import from Task 1 through
  Task 6 and fail this repo's `ruff check .` CI step (F401 is enabled for `app/`, per `ruff.toml`).)
- Produces (used by Tasks 2, 3, 4, 5, 6):
  - `ensure_table(engine=None) -> None`
  - `_position_group(position: str) -> str` — `"pitcher"` / `"catcher"` / `"hitter"`
  - `load_roster(season_label: str) -> pd.DataFrame` — columns `roster_id, first_name, last_name,
    class_year, position`
  - `upsert_season_roster(season_label: str, players: list[dict], engine=None) -> int` — each dict
    has keys `first_name, last_name, class_year, position`
  - `placeholder_rows(season_label: str, groups: tuple[str, ...], id_col: str, name_col: str) -> pd.DataFrame`
  - `union_with_roster(df: pd.DataFrame, season_label: str, groups: tuple[str, ...], id_col: str, name_col: str) -> pd.DataFrame`
  - `reconcile_ids(season_label: str, engine=None) -> int`

- [ ] **Step 1: Write the failing tests for `ensure_table` / `_position_group` / `load_roster` / `upsert_season_roster`**

Create `tests/test_lmu_roster.py`:

```python
"""lmu_roster: the LMU-only active-roster table that backs placeholder rows
in the Trackman-derived lmu_pitchers/lmu_hitters/lmu_catchers rosters. Uses
season label "1899/1900" throughout -- guaranteed to never be a real season,
so these tests can freely write/read against the live analytics DB without
colliding with real data."""
import pandas as pd

from app.data import lmu_roster as LR

SEASON = "1899/1900"


def test_ensure_table_idempotent():
    LR.ensure_table()
    LR.ensure_table()  # second call is a no-op, not an error


def test_position_group_mapping():
    assert LR._position_group("RHP") == "pitcher"
    assert LR._position_group("LHP") == "pitcher"
    assert LR._position_group("C") == "catcher"
    assert LR._position_group("1B") == "hitter"
    assert LR._position_group("SS") == "hitter"
    assert LR._position_group("") == "hitter"
    assert LR._position_group(None) == "hitter"


def test_upsert_then_load_roster_roundtrip():
    LR.ensure_table()
    n = LR.upsert_season_roster(SEASON, [
        {"first_name": "Test", "last_name": "Playerone", "class_year": "FR", "position": "RHP"},
        {"first_name": "Test", "last_name": "Playertwo", "class_year": "SR", "position": "C"},
    ])
    assert n == 2
    df = LR.load_roster(SEASON)
    names = set(zip(df["first_name"], df["last_name"]))
    assert ("Test", "Playerone") in names
    assert ("Test", "Playertwo") in names


def test_upsert_is_idempotent_and_keeps_same_roster_id():
    LR.ensure_table()
    LR.upsert_season_roster(SEASON, [
        {"first_name": "Stable", "last_name": "Idcheck", "class_year": "FR", "position": "OF"},
    ])
    before = LR.load_roster(SEASON)
    rid_before = int(before.loc[before["last_name"] == "Idcheck", "roster_id"].iloc[0])

    # Re-run with an edited class_year/position -- must update in place, not
    # insert a second row or change roster_id (placeholder ids elsewhere in
    # the app are -roster_id and must never shift under a re-seed).
    LR.upsert_season_roster(SEASON, [
        {"first_name": "Stable", "last_name": "Idcheck", "class_year": "SO", "position": "SS"},
    ])
    after = LR.load_roster(SEASON)
    matches = after[after["last_name"] == "Idcheck"]
    assert len(matches) == 1
    assert int(matches.iloc[0]["roster_id"]) == rid_before
    assert matches.iloc[0]["class_year"] == "SO"
    assert matches.iloc[0]["position"] == "SS"


def test_load_roster_empty_season_returns_empty_frame():
    df = LR.load_roster("1800/1801")  # never seeded
    assert df.empty
    assert list(df.columns) == ["roster_id", "first_name", "last_name", "class_year", "position"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_lmu_roster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.lmu_roster'` (or ImportError).

- [ ] **Step 3: Implement `app/data/lmu_roster.py` (table + core CRUD, no union/reconcile yet)**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_lmu_roster.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/data/lmu_roster.py tests/test_lmu_roster.py
git commit -m "feat(lmu-roster): add lmu_roster table + core CRUD"
```

---

### Task 2: `placeholder_rows` / `union_with_roster` (the union logic itself)

**Files:**
- Modify: `app/data/lmu_roster.py`
- Test: `tests/test_lmu_roster.py` (append)

**Interfaces:**
- Consumes: Task 1's `load_roster`, `_position_group`, `app.data.roster_media._norm_name`.
- Produces: `placeholder_rows(...)`, `union_with_roster(...)` (consumed by Tasks 3/4/5).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lmu_roster.py`:

```python
def test_placeholder_rows_shape_and_negative_ids(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 501, "first_name": "Test", "last_name": "Rhp", "class_year": "FR", "position": "RHP"},
        {"roster_id": 502, "first_name": "Test", "last_name": "Inf", "class_year": "SO", "position": "SS"},
    ]))
    df = LR.placeholder_rows(SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert list(df.columns) == ["PitcherId", "Pitcher"]
    assert len(df) == 1
    assert df.iloc[0]["PitcherId"] == -501
    assert df.iloc[0]["Pitcher"] == "Rhp, Test"


def test_placeholder_rows_empty_when_no_roster(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame(
        columns=["roster_id", "first_name", "last_name", "class_year", "position"]))
    df = LR.placeholder_rows(SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert df.empty


def test_union_with_roster_adds_unmatched_and_dedupes_matched(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 1, "first_name": "adam", "last_name": "BEHRENS",  # same player as real row, different case
         "class_year": "SR", "position": "RHP"},
        {"roster_id": 2, "first_name": "New", "last_name": "Guy", "class_year": "FR", "position": "RHP"},
    ]))
    real = pd.DataFrame({"PitcherId": [123], "Pitcher": ["Behrens, Adam"]})
    out = LR.union_with_roster(real, SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert list(out["PitcherId"]).count(123) == 1        # real row not duplicated
    assert (out["PitcherId"] == -2).any()                 # non-matching roster row added
    assert not (out["PitcherId"] == -1).any()              # matching roster row suppressed
    assert len(out) == 2


def test_union_with_roster_returns_df_unchanged_when_no_placeholders(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame(
        columns=["roster_id", "first_name", "last_name", "class_year", "position"]))
    real = pd.DataFrame({"PitcherId": [123], "Pitcher": ["Behrens, Adam"]})
    out = LR.union_with_roster(real, SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert out is real
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_lmu_roster.py -v -k "placeholder_rows or union_with_roster"`
Expected: FAIL — `AttributeError: module 'app.data.lmu_roster' has no attribute 'placeholder_rows'`.

- [ ] **Step 3: Implement `placeholder_rows` and `union_with_roster`**

Append to `app/data/lmu_roster.py` (after `upsert_season_roster`, before the module ends):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_lmu_roster.py -v`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/data/lmu_roster.py tests/test_lmu_roster.py
git commit -m "feat(lmu-roster): add placeholder_rows/union_with_roster"
```

---

### Task 3: Union placeholders into `pitching_caps.lmu_pitchers`

**Files:**
- Modify: `app/data/pitching_caps.py:307-341`
- Test: `tests/test_pitching_caps.py`

**Interfaces:**
- Consumes: `app.data.lmu_roster.union_with_roster` (LOCAL import inside `lmu_pitchers`, to avoid
  a module-level import cycle with `lmu_roster.py`'s own module-level `pitching_caps` import from
  Task 1).
- Produces: `lmu_pitchers`'s return shape is unchanged (`PitcherId, Pitcher` columns) — no
  downstream caller needs any change.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pitching_caps.py` (near the other `lmu_pitchers` tests, e.g. after
`test_lmu_pitchers_season_scoped_and_past_seasons_surface`):

```python
def test_lmu_pitchers_unions_roster_placeholders(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9001, "first_name": "Test", "last_name": "Placeholder",
         "class_year": "FR", "position": "RHP"},
    ]))
    df = pitching_caps.lmu_pitchers("1899/1900")
    assert (df["PitcherId"] == -9001).any()
    assert (df.loc[df["PitcherId"] == -9001, "Pitcher"] == "Placeholder, Test").all()
    cache.clear_all()


def test_lmu_pitchers_ranged_call_excludes_roster_placeholders(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9002, "first_name": "Test", "last_name": "Placeholder2",
         "class_year": "FR", "position": "RHP"},
    ]))
    df = pitching_caps.lmu_pitchers("1899/1900", start="1899-08-01", end="1899-08-02")
    assert not (df["PitcherId"] == -9002).any() if not df.empty else True
    cache.clear_all()


def test_lmu_pitchers_dedupes_placeholder_matching_real_row_by_name(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(pitching_caps, "query_df", lambda sql, params=None: pd.DataFrame(
        {"PitcherId": [123], "Pitcher": ["Behrens, Adam"]}))
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 1, "first_name": "adam", "last_name": "BEHRENS",
         "class_year": "SR", "position": "RHP"},
        {"roster_id": 2, "first_name": "New", "last_name": "Guy",
         "class_year": "FR", "position": "RHP"},
    ]))
    df = pitching_caps.lmu_pitchers("1899/1900")
    assert list(df["PitcherId"]).count(123) == 1
    assert (df["PitcherId"] == -2).any()
    assert not (df["PitcherId"] == -1).any()
    cache.clear_all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pitching_caps.py -v -k "roster_placeholder or dedupes_placeholder"`
Expected: FAIL — the placeholder id `-9001` is absent from the real (empty-for-fake-season)
`lmu_pitchers("1899/1900")` result; the dedup test shows 2 real+placeholder rows instead of 1.

- [ ] **Step 3: Modify `lmu_pitchers`**

In `app/data/pitching_caps.py`, replace lines 307-341 (the whole `lmu_pitchers` function) with:

```python
@cached
def lmu_pitchers(season=None, start=None, end=None) -> pd.DataFrame:
    """One row per LMU pitcher (name deduped; canonical id = most-tracked id),
    scoped to the given academic-year season (default = current_season()).

    Mirrors pitching.wh_lmu_pitchers's dedup logic, but over GAMES/PitcherId
    instead of fact_tm_game_pitch/pitcher_id. Season date-bounds (not a
    numeric-GameID filter) do the scoping now, so legacy composite-GameID
    seasons are listable too. The COUNT(*) DESC dedup tiebreak is computed
    over the season's rows only. Mirrors hitting_caps.lmu_hitters(season).

    When both `start` and `end` are given, they replace the season's date
    bounds (the coach's date-range dropdown nests inside the season, so this
    narrows the roster to pitchers with data in that window).

    At the season level (no start/end override), also unions in
    `app.data.lmu_roster` placeholder rows (negative PitcherId) for any
    rostered pitcher with zero GAMES rows yet this season. A ranged call
    never gets placeholders -- it's explicitly asking "who has DATA in this
    window", which a data-less placeholder can never answer yes to.
    """
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    ranged = start is not None and end is not None
    if ranged:
        s, e = str(start), str(end)
    df = query_df(
        f"""
        SELECT PitcherId, Pitcher FROM (
          SELECT PitcherId, Pitcher,
                 ROW_NUMBER() OVER (PARTITION BY Pitcher
                                    ORDER BY COUNT(*) DESC, PitcherId) AS rn
            FROM GAMES
           WHERE PitcherTeam = :team AND PitcherId IS NOT NULL
             AND Date BETWEEN :s AND :e
           GROUP BY PitcherId, Pitcher
        ) t WHERE rn = 1 ORDER BY Pitcher
        """,
        {"team": LMU_PITCHER_TEAM, "s": s, "e": e},
    )
    if not df.empty:
        df["PitcherId"] = df["PitcherId"].astype(int)
    if not ranged:
        from app.data import lmu_roster
        df = lmu_roster.union_with_roster(df, season, ("pitcher",), "PitcherId", "Pitcher")
    return df
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching_caps.py -v`
Expected: PASS, including all pre-existing `lmu_pitchers` tests (the ranged-call and default-season
behavior for real data is unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching_caps.py tests/test_pitching_caps.py
git commit -m "feat(lmu-roster): union roster placeholders into lmu_pitchers"
```

---

### Task 4: Union placeholders into `hitting_caps.lmu_hitters`

**Files:**
- Modify: `app/data/hitting_caps.py:337-371`
- Test: `tests/test_hitting_caps.py`

**Interfaces:**
- Consumes: `app.data.lmu_roster.union_with_roster` (LOCAL import inside `lmu_hitters`).
- Produces: `lmu_hitters`'s return shape unchanged (`Batter, BatterId` columns). Uses groups
  `("hitter", "catcher")` — a real catcher already appears in `lmu_hitters` once they have live
  batting data (it's keyed on `BatterId`, independent of `lmu_catchers`'s `CatcherId`), so a
  catcher-position placeholder must be eligible here too, not just in `lmu_catchers`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_hitting_caps.py`:

```python
def test_lmu_hitters_unions_roster_placeholders_including_catchers(monkeypatch):
    from app.data import lmu_roster
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9101, "first_name": "Test", "last_name": "Infielder",
         "class_year": "FR", "position": "SS"},
        {"roster_id": 9102, "first_name": "Test", "last_name": "Catcher",
         "class_year": "SO", "position": "C"},
        {"roster_id": 9103, "first_name": "Test", "last_name": "Pitcheronly",
         "class_year": "JR", "position": "RHP"},
    ]))
    df = hitting_caps.lmu_hitters("1899/1900")
    assert (df["BatterId"] == -9101).any()
    assert (df["BatterId"] == -9102).any()          # catchers also appear here
    assert not (df["BatterId"] == -9103).any()       # pitcher-only does not
    cache.clear_all()


def test_lmu_hitters_ranged_call_excludes_roster_placeholders(monkeypatch):
    from app.data import lmu_roster
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9104, "first_name": "Test", "last_name": "Infielder2",
         "class_year": "FR", "position": "SS"},
    ]))
    df = hitting_caps.lmu_hitters("1899/1900", start="1899-08-01", end="1899-08-02")
    assert not (df["BatterId"] == -9104).any() if not df.empty else True
    cache.clear_all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_hitting_caps.py -v -k roster_placeholder`
Expected: FAIL — placeholder BatterIds absent.

- [ ] **Step 3: Modify `lmu_hitters`**

In `app/data/hitting_caps.py`, replace lines 337-371 (the whole `lmu_hitters` function) with:

```python
@cached
def lmu_hitters(season=None, start=None, end=None) -> pd.DataFrame:
    """One row per LMU hitter (name deduped; canonical id = most-tracked id),
    scoped to the given academic-year season (default = current_season()).

    Season date-bounds (not a numeric-GameID filter) do the scoping now, so
    legacy composite-GameID seasons are listable too. The COUNT(*) DESC dedup
    tiebreak is computed over the season's rows only.

    When both `start` and `end` are given, they replace the season's date
    bounds (the coach's date-range dropdown nests inside the season, so this
    narrows the roster to hitters with data in that window -- e.g. the
    Hitter dropdown refresh on `*-daterange` change).

    At the season level (no start/end override), also unions in
    `app.data.lmu_roster` placeholder rows (negative BatterId) for any
    rostered hitter OR catcher with zero GAMES rows yet this season --
    catchers hit too, so they're eligible here in addition to
    `lmu_catchers`. A ranged call never gets placeholders -- it's explicitly
    asking "who has DATA in this window", which a data-less placeholder can
    never answer yes to.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    ranged = start is not None and end is not None
    if ranged:
        s, e = str(start), str(end)
    df = query_df(
        f"""
        SELECT Batter, BatterId FROM (
          SELECT Batter, BatterId,
                 ROW_NUMBER() OVER (PARTITION BY Batter
                                    ORDER BY COUNT(*) DESC, BatterId) AS rn
            FROM GAMES
           WHERE BatterTeam = :team AND BatterId IS NOT NULL
             AND Date BETWEEN :s AND :e
           GROUP BY Batter, BatterId
        ) t WHERE rn = 1 ORDER BY Batter
        """,
        {"team": LMU_BATTER_TEAM, "s": s, "e": e},
    )
    if not df.empty:
        df["BatterId"] = df["BatterId"].astype(int)
    if not ranged:
        from app.data import lmu_roster
        df = lmu_roster.union_with_roster(df, season, ("hitter", "catcher"), "BatterId", "Batter")
    return df
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_hitting_caps.py -v`
Expected: PASS, including all pre-existing `lmu_hitters` tests.

- [ ] **Step 5: Commit**

```bash
git add app/data/hitting_caps.py tests/test_hitting_caps.py
git commit -m "feat(lmu-roster): union roster placeholders into lmu_hitters"
```

---

### Task 5: Union placeholders into `catching_caps.lmu_catchers`

**Files:**
- Modify: `app/data/catching_caps.py:120-156`
- Test: `tests/test_catching_caps.py`

**Interfaces:**
- Consumes: `app.data.lmu_roster.union_with_roster` (LOCAL import inside `lmu_catchers`).
- Produces: `lmu_catchers`'s return shape unchanged (`CatcherId, Catcher` columns). Uses group
  `("catcher",)` only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catching_caps.py`:

```python
def test_lmu_catchers_unions_roster_placeholders(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9201, "first_name": "Test", "last_name": "Backstop",
         "class_year": "FR", "position": "C"},
        {"roster_id": 9202, "first_name": "Test", "last_name": "Infielder3",
         "class_year": "SO", "position": "SS"},
    ]))
    df = catching_caps.lmu_catchers("1899/1900")
    assert (df["CatcherId"] == -9201).any()
    assert not (df["CatcherId"] == -9202).any()   # non-catcher position excluded
    cache.clear_all()


def test_lmu_catchers_ranged_call_excludes_roster_placeholders(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9203, "first_name": "Test", "last_name": "Backstop2",
         "class_year": "FR", "position": "C"},
    ]))
    df = catching_caps.lmu_catchers("1899/1900", start="1899-08-01", end="1899-08-02")
    assert not (df["CatcherId"] == -9203).any() if not df.empty else True
    cache.clear_all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_catching_caps.py -v -k roster_placeholder`
Expected: FAIL — placeholder CatcherIds absent.

- [ ] **Step 3: Modify `lmu_catchers`**

In `app/data/catching_caps.py`, replace lines 120-156 (the whole `lmu_catchers` function) with:

```python
@cached
def lmu_catchers(season=None, start=None, end=None) -> pd.DataFrame:
    """One row per LMU catcher (name deduped; canonical id = most-tracked id),
    scoped to the given academic-year season (default = current_season()).

    Season date-bounds (not a numeric-GameID filter, and no ~12-month recent
    window) do the scoping now, so legacy composite-GameID seasons are listable
    too -- picking a PAST season from the dropdown surfaces that season's
    catchers, whose games are ALL composite-GameID and were previously hidden.
    The COUNT(*) DESC dedup tiebreak is computed over the season's rows only.
    Mirrors hitting_caps.lmu_hitters(season) exactly.

    When both `start` and `end` are given, they replace the season's date
    bounds (the coach's date-range dropdown nests inside the season, so this
    narrows the roster to catchers with data in that window).

    At the season level (no start/end override), also unions in
    `app.data.lmu_roster` placeholder rows (negative CatcherId) for any
    rostered catcher with zero GAMES rows yet this season. A ranged call
    never gets placeholders -- it's explicitly asking "who has DATA in this
    window", which a data-less placeholder can never answer yes to.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    ranged = start is not None and end is not None
    if ranged:
        s, e = str(start), str(end)
    df = query_df(
        f"""
        SELECT CatcherId, Catcher FROM (
          SELECT CatcherId, Catcher,
                 ROW_NUMBER() OVER (PARTITION BY Catcher
                                    ORDER BY COUNT(*) DESC, CatcherId) AS rn
            FROM GAMES
           WHERE PitcherTeam = :team AND CatcherId IS NOT NULL
             AND Date BETWEEN :s AND :e
           GROUP BY CatcherId, Catcher
        ) t WHERE rn = 1 ORDER BY Catcher
        """,
        {"team": LMU_PITCHER_TEAM, "s": s, "e": e},
    )
    if not df.empty:
        df["CatcherId"] = df["CatcherId"].astype(int)
    if not ranged:
        from app.data import lmu_roster
        df = lmu_roster.union_with_roster(df, season, ("catcher",), "CatcherId", "Catcher")
    return df
```

Note the query uses `LMU_PITCHER_TEAM` (catchers are scoped by their pitching team, same rule as
`app.data.catching`'s oracle), NOT `LMU_BATTER_TEAM` — do not swap it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_catching_caps.py -v`
Expected: PASS, including all pre-existing `lmu_catchers` tests.

- [ ] **Step 5: Commit**

```bash
git add app/data/catching_caps.py tests/test_catching_caps.py
git commit -m "feat(lmu-roster): union roster placeholders into lmu_catchers"
```

---

### Task 6: Seed data + loader script, run against the live DB

**Files:**
- Create: `data/rosters/2026-2027.json`
- Create: `scripts/load_lmu_roster.py`
- Test: `tests/test_load_lmu_roster.py`

**Interfaces:**
- Consumes: Task 1's `lmu_roster.upsert_season_roster`, `lmu_roster.load_roster`.
- Produces: nothing new consumed by later tasks (this task's *effect* — a populated
  `lmu_roster` table for `"2026/2027"` — is what makes Task 8's live smoke check show real
  players).

- [ ] **Step 1: Create the roster data file**

Create `data/rosters/2026-2027.json` with this exact content (47 players; last-name-only
cross-matched against the `26-27 Breakdown` tab of `Roster Management.xlsx` for first names, with
5 gaps — Geren/Jacobsen/Kaczynski/Leitgeb/Marucci — and 2 non-roster names — Chavez/Webster
excluded — resolved directly by the user; see spec §1):

```json
[
  {"first_name": "Adam", "last_name": "Behrens", "class_year": "SR", "position": "RHP"},
  {"first_name": "Ryan", "last_name": "Bresaw", "class_year": "FR", "position": "RHP"},
  {"first_name": "Braden", "last_name": "Burness", "class_year": "JR", "position": "RHP"},
  {"first_name": "Cam", "last_name": "Casado", "class_year": "JR", "position": "1B"},
  {"first_name": "John", "last_name": "Casale", "class_year": "JR", "position": "LHP"},
  {"first_name": "Matthew", "last_name": "Champion", "class_year": "RS SO", "position": "RHP"},
  {"first_name": "JD", "last_name": "Dunn", "class_year": "RS JR", "position": "OF"},
  {"first_name": "Eric", "last_name": "Erdmann", "class_year": "SO", "position": "RHP"},
  {"first_name": "Andrew", "last_name": "Estrella", "class_year": "GR", "position": "SS"},
  {"first_name": "Brayden", "last_name": "Flores", "class_year": "JR", "position": "SS"},
  {"first_name": "Travis", "last_name": "Friend", "class_year": "SO", "position": "CF"},
  {"first_name": "Lucas", "last_name": "Gabay", "class_year": "SR", "position": "INF"},
  {"first_name": "Alex", "last_name": "Gamboa", "class_year": "SO", "position": "OF"},
  {"first_name": "Lucas", "last_name": "Geren", "class_year": "JR", "position": "RHP"},
  {"first_name": "Corbin", "last_name": "Giesen", "class_year": "JR", "position": "RHP"},
  {"first_name": "Win", "last_name": "Gurney", "class_year": "SO", "position": "OF"},
  {"first_name": "Gavin", "last_name": "Jacobsen", "class_year": "GR", "position": "LHP"},
  {"first_name": "Shaw", "last_name": "Jenkins", "class_year": "FR", "position": "SS"},
  {"first_name": "Alec", "last_name": "Johnson", "class_year": "SR", "position": "LHP"},
  {"first_name": "Will", "last_name": "Kaczynski", "class_year": "JR", "position": "RHP"},
  {"first_name": "Blake", "last_name": "Killinger", "class_year": "FR", "position": "RHP"},
  {"first_name": "Theo", "last_name": "Kim", "class_year": "JR", "position": "INF"},
  {"first_name": "Richie", "last_name": "Klosek", "class_year": "SO", "position": "OF"},
  {"first_name": "Colten", "last_name": "Landen", "class_year": "FR", "position": "RHP"},
  {"first_name": "Brock", "last_name": "Leitgeb", "class_year": "RS JR", "position": "C"},
  {"first_name": "Jake", "last_name": "Lyall", "class_year": "JR", "position": "C"},
  {"first_name": "Noah", "last_name": "Malone", "class_year": "JR", "position": "OF"},
  {"first_name": "Andrew", "last_name": "Mhoon", "class_year": "SO", "position": "INF"},
  {"first_name": "Matthew", "last_name": "Moreno", "class_year": "JR", "position": "INF"},
  {"first_name": "Donnie", "last_name": "Morgan", "class_year": "JR", "position": "CF"},
  {"first_name": "Sawyer", "last_name": "Nelson", "class_year": "FR", "position": "SS"},
  {"first_name": "Holden", "last_name": "Newhouse", "class_year": "FR", "position": "RHP"},
  {"first_name": "Jordan", "last_name": "Ortiz", "class_year": "SO", "position": "C"},
  {"first_name": "Braeden", "last_name": "Parker", "class_year": "FR", "position": "OF"},
  {"first_name": "Andrew", "last_name": "Phillips", "class_year": "RS SO", "position": "RHP"},
  {"first_name": "Niko", "last_name": "Riera", "class_year": "SR", "position": "RHP"},
  {"first_name": "Chad", "last_name": "Rolison", "class_year": "FR", "position": "OF"},
  {"first_name": "Max", "last_name": "Schneider", "class_year": "SO", "position": "RHP"},
  {"first_name": "Ari", "last_name": "Silva", "class_year": "FR", "position": "LHP"},
  {"first_name": "Nate", "last_name": "Stiveson", "class_year": "JR", "position": "INF"},
  {"first_name": "Cole", "last_name": "Stucky", "class_year": "RS JR", "position": "RHP"},
  {"first_name": "Caleb", "last_name": "Sweeney", "class_year": "SO", "position": "LHP"},
  {"first_name": "Charlie", "last_name": "Ushijima", "class_year": "FR", "position": "RHP"},
  {"first_name": "Zach", "last_name": "Wadas", "class_year": "SR", "position": "1B"},
  {"first_name": "Branson", "last_name": "Wade", "class_year": "FR", "position": "RHP"},
  {"first_name": "Jacob", "last_name": "Wicker", "class_year": "FR", "position": "OF"},
  {"first_name": "Luca", "last_name": "Marucci", "class_year": "FR", "position": "C"}
]
```

- [ ] **Step 2: Write the failing test for the loader script**

Create `tests/test_load_lmu_roster.py`:

```python
"""scripts/load_lmu_roster.py: seeds lmu_roster from a committed JSON file."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import lmu_roster as LR
from scripts.load_lmu_roster import main as load_main

SEASON = "1899/1900"


def _write_fixture(tmp_path, players):
    p = tmp_path / "roster.json"
    p.write_text(json.dumps(players), encoding="utf-8")
    return str(p)


def test_load_main_seeds_all_players(tmp_path):
    path = _write_fixture(tmp_path, [
        {"first_name": "Load", "last_name": "Testone", "class_year": "FR", "position": "RHP"},
        {"first_name": "Load", "last_name": "Testtwo", "class_year": "SR", "position": "C"},
    ])
    rc = load_main(path, SEASON)
    assert rc == 0
    df = LR.load_roster(SEASON)
    names = set(zip(df["first_name"], df["last_name"]))
    assert ("Load", "Testone") in names
    assert ("Load", "Testtwo") in names


def test_load_main_is_idempotent(tmp_path):
    path = _write_fixture(tmp_path, [
        {"first_name": "Idem", "last_name": "Potent", "class_year": "FR", "position": "OF"},
    ])
    load_main(path, SEASON)
    before = LR.load_roster(SEASON)
    rid = int(before.loc[before["last_name"] == "Potent", "roster_id"].iloc[0])
    load_main(path, SEASON)  # re-run unchanged -- must not duplicate or renumber
    after = LR.load_roster(SEASON)
    matches = after[after["last_name"] == "Potent"]
    assert len(matches) == 1
    assert int(matches.iloc[0]["roster_id"]) == rid


def test_real_2026_2027_fixture_loads_47_players():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "data", "rosters", "2026-2027.json")
    with open(path, encoding="utf-8") as fh:
        players = json.load(fh)
    assert len(players) == 47
    for p in players:
        assert p["first_name"] and p["last_name"] and p["position"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_load_lmu_roster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.load_lmu_roster'`.

- [ ] **Step 4: Implement `scripts/load_lmu_roster.py`**

```python
"""Seed/update the `lmu_roster` table from a committed season roster JSON file.

Run: python scripts/load_lmu_roster.py data/rosters/2026-2027.json "2026/2027"

Idempotent: re-running with edited class_year/position updates those fields
in place (same roster_id, matched on season_label+last_name+first_name)
rather than reinserting -- required so placeholder ids (-roster_id) already
possibly saved elsewhere (Cauldron/Velo Board) never shift under a coach's
data. Never deletes a player who's missing from a re-run's file -- prints
anyone in the DB for that season who ISN'T in the new file instead, so a real
drop (transfer, etc.) stays a deliberate manual decision.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.lmu_roster import load_roster, upsert_season_roster  # noqa: E402


def main(path: str, season_label: str) -> int:
    with open(path, encoding="utf-8") as fh:
        players = json.load(fh)
    before = set(zip(load_roster(season_label)["last_name"],
                      load_roster(season_label)["first_name"]))
    n = upsert_season_roster(season_label, players)
    print(f"upserted {n} players for {season_label} from {path}")
    after_names = {(p["last_name"], p["first_name"]) for p in players}
    dropped = before - after_names
    if dropped:
        print(f"NOTE: in DB for {season_label} but not in this file (NOT removed): "
              f"{sorted(dropped)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/load_lmu_roster.py <path.json> <season_label>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_load_lmu_roster.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the loader for real against the live DB**

Run: `PYTHONIOENCODING=utf-8 python scripts/load_lmu_roster.py data/rosters/2026-2027.json "2026/2027"`
Expected output: `upserted 47 players for 2026/2027 from data/rosters/2026-2027.json` and no
`NOTE: ... NOT removed` line (nothing was seeded for this season before). Verify with:
`python -c "from app.data import lmu_roster as LR; print(len(LR.load_roster('2026/2027')))"` →
prints `47`.

- [ ] **Step 7: Commit**

```bash
git add data/rosters/2026-2027.json scripts/load_lmu_roster.py tests/test_load_lmu_roster.py
git commit -m "feat(lmu-roster): seed the 2026/2027 roster"
```

---

### Task 7: Reconciliation (`reconcile_ids`) + `flask roster-reconcile` CLI

**Files:**
- Modify: `app/data/lmu_roster.py`
- Modify: `app/cli.py`
- Test: `tests/test_lmu_roster.py` (append), `tests/test_cli_roster_reconcile.py`

**Interfaces:**
- Consumes: `pitching_caps.lmu_pitchers` (module-level import in `lmu_roster.py`, per Task 1's
  docstring note), Task 1's `load_roster`/`_position_group`, `roster_media._norm_name`.
- Produces: `reconcile_ids(season_label, engine=None) -> int`; `flask roster-reconcile [--season]`
  CLI command.

- [ ] **Step 1: Write the failing test for `reconcile_ids`**

Append to `tests/test_lmu_roster.py`:

```python
def test_reconcile_ids_migrates_matched_pitcher_and_is_idempotent(monkeypatch):
    from app.data import cauldron, velo_board
    cauldron.ensure_tables()
    velo_board.ensure_tables()

    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9301, "first_name": "Recon", "last_name": "Cilable",
         "class_year": "FR", "position": "RHP"},
        {"roster_id": 9302, "first_name": "Still", "last_name": "Unmatched",
         "class_year": "SO", "position": "RHP"},
    ]))
    monkeypatch.setattr(LR.pitching_caps, "lmu_pitchers", lambda season: pd.DataFrame(
        {"PitcherId": [777001], "Pitcher": ["Cilable, Recon"]}))

    placeholder_id = -9301
    cauldron.set_team(placeholder_id, "TEST-RECON-c1", "Team 1")
    velo_board.set_override(placeholder_id, SEASON, season_max=95.0)

    migrated = LR.reconcile_ids(SEASON)
    assert migrated == 2  # one cauldron_teams row + one velo_board_overrides row

    teams = cauldron.read_teams("TEST-RECON-c1")
    ids = set(teams["player_id"].astype(int))
    assert 777001 in ids
    assert placeholder_id not in ids

    overrides = velo_board.read_overrides(SEASON)
    ov_ids = set(overrides["pitcher_id"].astype(int))
    assert 777001 in ov_ids
    assert placeholder_id not in ov_ids

    again = LR.reconcile_ids(SEASON)
    assert again == 0  # idempotent -- nothing left under the placeholder id
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_lmu_roster.py -v -k reconcile_ids`
Expected: FAIL — `AttributeError: module 'app.data.lmu_roster' has no attribute 'reconcile_ids'`.

- [ ] **Step 3: Implement `reconcile_ids`**

Add the module-level import and the function to `app/data/lmu_roster.py`. Add
`from app.data import pitching_caps` to the top imports (alongside the existing
`from app.data.roster_media import _norm_name`). Append at the end of the file:

```python
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
    real = pitching_caps.lmu_pitchers(season_label)
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
                result = conn.execute(
                    text(f"UPDATE {table} SET {col} = :real WHERE {col} = :placeholder"),
                    {"real": real_id, "placeholder": placeholder_id})
                migrated += result.rowcount
    return migrated
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_lmu_roster.py -v`
Expected: PASS (all tests in the file, including the new `reconcile_ids` one).

- [ ] **Step 5: Write the failing test for the CLI command**

Create `tests/test_cli_roster_reconcile.py`:

```python
"""`flask roster-reconcile` CLI command."""
import os
import tempfile

from click.testing import CliRunner

from app import create_app
from config import Config


def _test_app():
    """Mirrors tests/test_auth.py's `app` fixture: a real create_app() with the
    AUTH db pointed at a throwaway sqlite file (ANALYTICS_DB_URL is untouched,
    so lmu_roster.reconcile_ids -- monkeypatched below anyway -- would still
    resolve against the real analytics DB if it weren't mocked)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    return create_app(TestConfig)


def test_roster_reconcile_command_runs_and_reports_count(monkeypatch):
    from app.data import lmu_roster
    monkeypatch.setattr(lmu_roster, "reconcile_ids", lambda season, engine=None: 3)
    app = _test_app()
    runner = CliRunner()
    result = runner.invoke(app.cli, ["roster-reconcile", "--season", "1899/1900"])
    assert result.exit_code == 0
    assert "1899/1900" in result.output
    assert "3" in result.output
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `python -m pytest tests/test_cli_roster_reconcile.py -v`
Expected: FAIL — `Error: No such command 'roster-reconcile'.`

- [ ] **Step 7: Add the CLI command**

In `app/cli.py`, inside `register_cli(server)`, add (after the existing `rebuild_precalc` command,
before `pipeline_load`, following that command's exact structural pattern):

```python
    @server.cli.command("roster-reconcile")
    @click.option("--season", default=None,
                  help="Season label, e.g. 2026/2027 (default: today's calendar season).")
    def roster_reconcile(season):
        """Migrate Cauldron/Velo Board rows from placeholder roster ids to real
        Trackman ids, for pitchers who now have real data."""
        from datetime import date
        from app.data import lmu_roster, seasons
        season = season or seasons.season_label_for(date.today().isoformat())
        n = lmu_roster.reconcile_ids(season)
        click.echo(f"roster-reconcile ({season}): migrated {n} row(s)")
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `python -m pytest tests/test_cli_roster_reconcile.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/data/lmu_roster.py app/cli.py tests/test_lmu_roster.py tests/test_cli_roster_reconcile.py
git commit -m "feat(lmu-roster): add reconcile_ids + flask roster-reconcile CLI"
```

---

### Task 8: Season default — `current_season()` always today's calendar season

**Files:**
- Modify: `app/data/seasons.py:62-76`
- Modify: `app/warmup.py` (comment only, lines ~108-113)
- Modify: `tests/test_seasons.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `current_season()`'s behavior changes (no signature change) — every caller listed in
  the spec §0/§5 (`catching/hitting/pitching` layouts, `*_caps.py`, `precalc.py`, `cauldron.py`,
  `pitcher_development.py`, `reports/routes.py`) now gets today's calendar season by default,
  automatically, with no per-caller code change needed.

- [ ] **Step 1: Update the failing/contradicting test first**

`tests/test_seasons.py::test_current_season_stays_games_driven_not_todays_calendar_season`
currently asserts the OLD behavior (`current_season()` must stay GAMES-driven, never today's
calendar season). That assertion becomes false by design. Replace that whole test function with:

```python
def test_current_season_now_always_todays_calendar_season(monkeypatch):
    """current_season() now ALWAYS returns today's calendar academic-year
    label, regardless of what GAMES contains -- the roster-placeholder union
    (app.data.lmu_roster) means the season view is no longer blank just
    because GAMES has zero rows for it yet, so the old "only fall back if
    GAMES is entirely empty" guard is no longer needed."""
    cache.clear_all()
    monkeypatch.setattr(S, "query_df", lambda sql, params=None:
                         pd.DataFrame({"Date": ["2024-11-01"]}))  # GAMES has OLDER data only
    try:
        assert S.current_season() == S.season_label_for(date.today().isoformat())
        assert S.current_season() != "2024/2025"
    finally:
        cache.clear_all()
```

Also update the comment in `test_available_and_current_live` (lines 22-26) — replace:

```python
    # current_season() stays GAMES-data-driven (deliberately NOT today's calendar
    # season unless GAMES actually has rows for it) while available_seasons() now
    # always additionally includes today's calendar season label -- so current_season()
    # is always ONE of the available options, but not necessarily the newest-sorted
    # one anymore (today's label can be newer than the latest season with real data).
```

with:

```python
    # current_season() now always returns today's calendar academic-year label
    # (see test_current_season_now_always_todays_calendar_season), which
    # available_seasons() also always includes -- so current_season() is
    # always the newest entry in available_seasons().
```

The two assertions below that comment (`current_season() in seasons`, `current_season() <= seasons[0]`)
still hold as-is; leave them unchanged.

- [ ] **Step 2: Run the test to verify it fails against current code**

Run: `python -m pytest tests/test_seasons.py -v`
Expected: FAIL on `test_current_season_now_always_todays_calendar_season` — old `current_season()`
returns `"2024/2025"` (GAMES-driven), not today's label.

- [ ] **Step 3: Change `current_season()`**

In `app/data/seasons.py`, replace lines 62-76:

```python
def current_season() -> str:
    """The latest season that has real GAMES data (the dropdown's default for
    catching/hitting/pitching). Falls back to today's academic year only if GAMES
    is entirely empty.

    Deliberately reads _games_seasons() directly rather than available_seasons():
    the latter always includes today's calendar season label (see above), which --
    since today's label can never be "older" than any GAMES-derived label -- would
    otherwise always win the max() and silently make this function track today's
    calendar date instead of real data. That would regress catching/hitting/pitching
    dashboards to an empty default view every day until real Fall-2026 GAMES rows
    land. This function's behavior is intentionally unchanged from before
    available_seasons() started including today's label."""
    labels = _games_seasons()
    return max(labels) if labels else season_label_for(date.today().isoformat())
```

with:

```python
def current_season() -> str:
    """Today's real calendar academic-year label -- the dropdown default for
    catching/hitting/pitching (and everything else that defaults off this).

    Used to prefer the latest season WITH real GAMES data instead, falling
    back to today's calendar season only if GAMES was entirely empty -- a
    guard against defaulting onto a blank page before any data existed for
    the new season. That guard is no longer needed: `app.data.lmu_roster`
    unions each season's rostered players in as placeholder rows wherever
    `lmu_pitchers`/`lmu_hitters`/`lmu_catchers` are read, so the current
    season's view is never actually empty, even on day one before any
    Trackman data exists for it."""
    return season_label_for(date.today().isoformat())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_seasons.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Update the now-stale comment in `app/warmup.py`**

Read `app/warmup.py` lines 100-118 first to confirm current line numbers, then replace the
paragraph:

```python
    # Velo Board/Cauldron's OWN default season (serve_layout in both
    # dashboards' layout.py) is today's real calendar season, not
    # current_season() -- their data source is BULLPEN, which gets Fall-2026
    # rows well before GAMES does. Use that same value here so the warmed
    # cache keys actually match what serve_layout requests; `season` (above)
    # stays current_season() for the hitting/pitching/catching warming only.
```

with:

```python
    # Velo Board/Cauldron's OWN default season (serve_layout in both
    # dashboards' layout.py) is today's real calendar season -- as of this
    # session, current_season() (used for the hitting/pitching/catching
    # warming above) ALSO always returns today's calendar season, so
    # `board_season` and `season` are now the same value. Kept as two
    # separately-computed locals (rather than collapsed to one) so this file
    # doesn't silently break if the two functions' behavior ever diverges
    # again later.
```

This is a comment-only change (no behavior/test implications) — no test step for it.

- [ ] **Step 6: Run the full `test_seasons.py` and `test_warmup.py` files together**

Run: `python -m pytest tests/test_seasons.py tests/test_warmup.py -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add app/data/seasons.py app/warmup.py tests/test_seasons.py
git commit -m "feat(lmu-roster): current_season() always defaults to today's calendar season"
```

---

### Task 9: Full-suite verification + live smoke check

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q --ignore=tests/test_precalc.py`

Expected: pass count is **931 + (net new tests from Tasks 1-8)**, and the ONLY failing tests are
the exact same pre-existing 15 named in Global Constraints (`test_player_filter_access.py` ×9,
`test_practice.py` ×4, `test_velo_cauldron_save_live.py` ×1). If any test outside that named set
fails, stop and fix it before proceeding — do not proceed with a new, unexplained failure.

- [ ] **Step 2: Run `flask roster-reconcile` against the live DB for the real season**

Run: `PYTHONIOENCODING=utf-8 python -m flask --app run roster-reconcile --season "2026/2027"`
Expected output: `roster-reconcile (2026/2027): migrated 0 row(s)` (expected — no Cauldron/Velo
Board data exists yet for any of the 47 real placeholder ids; this just confirms the command runs
clean against real data, not a monkeypatched fixture).

- [ ] **Step 3: Live check — start the dev server and open Cauldron + a Pitching dashboard**

Start the app (however this repo's dev server is normally started — check `README.md` /
`CONTRIBUTING.md` if unfamiliar) and, logged in as a coach:

`data/rosters/2026-2027.json` breaks down as 22 RHP/LHP (pitcher group), 4 C (catcher group), 21
everyone else (hitter group) — 47 total. Hitter-group dropdowns additionally get the 4 catchers
(union groups `("hitter", "catcher")`), so 25 total there.

- Open **Competitive Cauldron**: confirm the Season selector defaults to `2026/2027`, the coach
  grid lists all 22 RHP/LHP roster players, no numeric IDs visible anywhere in the `Player` column.
- Open **Pitching** dashboard: confirm the Season selector defaults to `2026/2027` and the pitcher
  dropdown lists those same 22 names.
- Open **Hitting** dashboard: confirm the Hitter dropdown lists all 25 non-pitcher roster names
  (21 position players + the 4 catchers).
- Open **Catching** dashboard: confirm the Catcher dropdown lists exactly the 4 catchers: Leitgeb,
  Lyall, Ortiz, Marucci.

If any of these shows a raw numeric id instead of a name, or is missing a roster player, stop and
diagnose before considering this plan complete — do not report success without having actually
looked.
