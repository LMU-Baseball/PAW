# Phase 2 (Hitting Slice) — Data Layer onto CAPS GAMES — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the **hitting** data layer off the `tm_*` warehouse to read the CAPS `GAMES` table, proven identical by parity tests against the warehouse before any cutover — plus the two shared prep steps (Date normalization, GameType column) the whole of Phase 2 needs.

**Architecture:** Build GAMES-based implementations in a NEW module `app/data/hitting_caps.py` alongside the untouched warehouse module `app/data/hitting_wh.py`. Both run against the live DB simultaneously, so parity tests assert the new output equals the old at the **semantic level the UI consumes** (batting line, QAB%, slash, swing decisions, BIP, game list) — tolerant of GAMES being a strict *improvement* (e.g. launch `Angle` is populated where the warehouse NaN'd it). Once parity holds, flip the hitting dashboard's imports to `hitting_caps`; `hitting_wh` stays only as the parity oracle until Phase 3 deletes it. GAMES already stores columns under the exact legacy names the shared transforms (`app/data/hitting.py`) expect, so no column aliasing is needed — the GAMES queries are simpler than the warehouse ones and consolidate redundant round-trips (the 3.2 s sidebar → one season load).

**Tech Stack:** Python, pandas, SQLAlchemy (`app.db.query_df`), MySQL (AWS RDS), pytest. Reuses `app/data/hitting.py` transforms (`_add_pitch_category`, `qab_frame`) and the `attack_zone`/`_finish` helpers.

## Global Constraints

- **Return shapes are the contract.** Every `hitting_caps` function returns the SAME column names / dict keys / types as its `hitting_wh` counterpart. The dashboard, tabs, charts, and transforms must not change.
- **GAMES id facts:** `BatterId`/`PitcherId`/`CatcherId` are RAW Trackman ids (== `current_user.trackman_id`); `GameID` is the per-game key (surrogate int carried from the warehouse); LMU hitters have `BatterTeam = 'LOY_LIO'`; team display names are in `HomeTeam`/`AwayTeam`; LMU is `HomeTeamForeignID`/`AwayTeamForeignID == 78`.
- **Dates:** after Task 1, `GAMES.Date` is ISO `YYYY-MM-DD` everywhere → plain string comparison is correct.
- **No warehouse reads in `hitting_caps`** — GAMES + `app/data/hitting.py` transforms only.
- **Parity tests hit the live DB** (matching the existing `tests/test_hitting.py` convention). Use demo hitter `BatterId = 806253` (Wadas, 1094 pitches / 64 games).
- **Prod writes (Tasks 1–2) are dry-run-first**, verified, and reversible; confirm with the user before the real write (as in Phase 1).
- TDD, DRY, YAGNI, frequent commits. Branch: `feat/caps-migration`.

---

### Task 1: Normalize `GAMES.Date` to ISO (shared prep, prod write)

**Files:**
- Create: `app/ingest/normalize_games_date.py`
- Test: `tests/test_normalize_games_date.py`

**Interfaces:**
- Produces: `iso_date(raw: str) -> str | None` (pure: `'5/3/24'`/`'5/3/2024'`/`'2024-05-03'` → `'2024-05-03'`; blank/unparseable → `None`); `normalize_dates(engine, *, dry_run=True) -> dict` (returns `{scanned, would_change, unparseable}`; UPDATEs only rows whose stored `Date` differs from its ISO form).

- [ ] **Step 1: Write failing tests for `iso_date`**

```python
# tests/test_normalize_games_date.py
import pytest
from app.ingest.normalize_games_date import iso_date

@pytest.mark.parametrize("raw,expected", [
    ("2024-05-03", "2024-05-03"),   # already ISO -> unchanged
    ("5/3/24", "2024-05-03"),       # US m/d/yy
    ("5/3/2024", "2024-05-03"),     # US m/d/yyyy
    ("12/31/25", "2025-12-31"),
    ("2026-05-16", "2026-05-16"),
])
def test_iso_date_converts_known_formats(raw, expected):
    assert iso_date(raw) == expected

@pytest.mark.parametrize("raw", ["", "   ", None, "not-a-date"])
def test_iso_date_unparseable_returns_none(raw):
    assert iso_date(raw) is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_normalize_games_date.py -q`
Expected: FAIL (`ModuleNotFoundError: app.ingest.normalize_games_date`).

- [ ] **Step 3: Implement `iso_date` + `normalize_dates`**

```python
# app/ingest/normalize_games_date.py
"""One-time: normalize GAMES.Date (mixed ISO + US m/d/yy) to ISO YYYY-MM-DD."""
from __future__ import annotations
from datetime import datetime
import pandas as pd
from sqlalchemy import text

_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")

def iso_date(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def normalize_dates(engine, *, dry_run: bool = True) -> dict:
    df = pd.read_sql(text("SELECT DISTINCT Date AS d FROM GAMES"), engine)
    scanned = would_change = unparseable = 0
    updates = []  # (old, new)
    for d in df["d"]:
        if d is None:
            continue
        scanned += 1
        new = iso_date(d)
        if new is None:
            unparseable += 1
            continue
        if str(d) != new:
            would_change += 1
            updates.append((str(d), new))
    if not dry_run and updates:
        with engine.begin() as conn:
            for old, new in updates:
                conn.execute(text("UPDATE GAMES SET Date = :new WHERE Date = :old"),
                             {"new": new, "old": old})
    return {"scanned": scanned, "would_change": would_change, "unparseable": unparseable}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_normalize_games_date.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Add CLI + commit**

Add to `app/ingest/cli.py` (import `normalize_dates`) a `normalize-games-date` command mirroring `backfill_games_command` (echo `scanned/would_change/unparseable/dry_run`). Commit:
```bash
git add app/ingest/normalize_games_date.py tests/test_normalize_games_date.py app/ingest/cli.py
git commit -m "feat(ingest): GAMES.Date ISO normalization (dry-run capable)"
```

- [ ] **Step 6: Dry-run against prod, review with user**

Run: `PYTHONIOENCODING=utf-8 python -m flask --app run ingest normalize-games-date --dry-run`
Report `would_change` / `unparseable` to the user. Spot-check a sample of `(old -> new)` conversions read-only. **Get explicit go-ahead** before Step 7.

- [ ] **Step 7: Real normalization (prod write, after approval)**

Run: `... ingest normalize-games-date --no-dry-run`
Verify: `SELECT COUNT(*) FROM GAMES WHERE Date NOT REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'` → expect only the unparseable/blank residue. Rollback path: dates are idempotently re-derivable; no destructive change (only reformatting).

---

### Task 2: Add `GameType` column to GAMES + backfill from `dim_tm_game` (shared prep, prod write)

**Files:**
- Create: `app/ingest/add_game_type.py`
- Test: `tests/test_add_game_type.py`

**Interfaces:**
- Produces: `backfill_game_type(engine, *, dry_run=True) -> dict` (`{would_update}`): ensures a `GameType` column exists (`ALTER TABLE GAMES ADD COLUMN GameType VARCHAR(64)` if absent), then sets `GAMES.GameType = dim_tm_game.game_type` joined on `GAMES.GameID = dim_tm_game.game_id` for the backfilled games.

- [ ] **Step 1: Write failing test (column-exists guard is idempotent)**

```python
# tests/test_add_game_type.py
from sqlalchemy import create_engine, text
from app.ingest.add_game_type import _ensure_column

def test_ensure_column_is_idempotent():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE GAMES (GameID INTEGER)"))
    _ensure_column(eng)   # adds GameType
    _ensure_column(eng)   # no-op second time (must not raise)
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(GAMES)")).fetchall()]
    assert "GameType" in cols
```

- [ ] **Step 2: Run test, verify fail**

Run: `python -m pytest tests/test_add_game_type.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# app/ingest/add_game_type.py
"""One-time: add GAMES.GameType and backfill from dim_tm_game.game_type."""
from __future__ import annotations
from sqlalchemy import text, inspect

def _ensure_column(engine):
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("GAMES")]
    if "GameType" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE GAMES ADD COLUMN GameType VARCHAR(64)"))

def backfill_game_type(engine, *, dry_run: bool = True) -> dict:
    _ensure_column(engine)
    count_sql = text(
        "SELECT COUNT(*) FROM GAMES g JOIN dim_tm_game d ON d.game_id = g.GameID "
        "WHERE (g.GameType IS NULL OR g.GameType <> d.game_type)")
    with engine.connect() as conn:
        would = conn.execute(count_sql).scalar()
    if not dry_run:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE GAMES g JOIN dim_tm_game d ON d.game_id = g.GameID "
                "SET g.GameType = d.game_type"))
    return {"would_update": int(would)}
```

- [ ] **Step 4: Run test, verify pass** — `python -m pytest tests/test_add_game_type.py -q`.

- [ ] **Step 5: CLI + commit** — add `backfill-game-type` command to `app/ingest/cli.py`; commit both files + cli.

- [ ] **Step 6: Dry-run, review, then real run (prod write, after approval)** — `... ingest backfill-game-type --dry-run` → report `would_update` → approval → `--no-dry-run`. Verify: `SELECT GameType, COUNT(*) FROM GAMES WHERE Date>='2025-11-01' GROUP BY GameType` shows sensible types (Scrimmage/Conference/…).

---

### Task 3: `hitting_caps` sibling-ids + pitch loaders + parity

**Files:**
- Create: `app/data/hitting_caps.py`
- Test: `tests/test_hitting_caps.py`

**Interfaces:**
- Consumes: `app.data.hitting._add_pitch_category`, `app.data.hitting.qab_frame`; `app.data.hitting_wh.attack_zone`, `app.data.hitting_wh._finish` (pure helpers — reused, NOT warehouse queries).
- Produces:
  - `_sibling_ids(batter_id) -> list[int]` (all `GAMES.BatterId` sharing this id's `Batter` name where `BatterTeam='LOY_LIO'`).
  - `game_pitches(game_id, batter_id) -> DataFrame` (== `hitting_wh.wh_game_pitches` shape, via `_finish`).
  - `range_pitches(batter_id, start, end) -> DataFrame`; `season_pitches(batter_id) -> DataFrame`.

- [ ] **Step 1: Write failing parity test for `game_pitches` (semantic level)**

```python
# tests/test_hitting_caps.py
import pandas as pd
from app.data import hitting_wh, hitting_caps
from app.data.hitting import game_batting_line, swing_decisions_by_zone

WADAS = 806253

def _first_game(bid):
    g = hitting_wh.wh_games_for_batter(bid)
    return int(g.iloc[0]["game_id"])

def test_game_pitches_matches_warehouse_batting_line():
    gid = _first_game(WADAS)
    old = hitting_wh.wh_game_pitches(gid, WADAS)
    new = hitting_caps.game_pitches(gid, WADAS)
    # same number of pitches, same core columns
    assert len(new) == len(old)
    # semantic parity: the batting line the UI shows is identical
    pd.testing.assert_frame_equal(
        game_batting_line(new).reset_index(drop=True),
        game_batting_line(old).reset_index(drop=True),
        check_dtype=False,
    )
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_hitting_caps.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `_sibling_ids` + pitch loaders**

```python
# app/data/hitting_caps.py
"""Hitting data layer on CAPS GAMES (replaces hitting_wh's warehouse reads).

GAMES stores columns under the legacy names the app/data/hitting.py transforms
expect, so no aliasing is needed -- SELECT the columns and hand to _finish.
"""
from __future__ import annotations
from app.db import query_df
from app.data.hitting_wh import _finish, _in_clause   # pure/param helpers, reused
from app.data.hitting import qab_frame

LMU_BATTER_TEAM = "LOY_LIO"
LMU_TEAM_ID = 78

# GAMES columns the transforms consume (already correctly named).
_PITCH_COLS = (
    "PlateLocSide, PlateLocHeight, PitchCall, PlayResult, KorBB, TaggedHitType, "
    "TaggedPitchType, ExitSpeed, Distance, Bearing, HangTime, Inning, PAofInning, "
    "PitchofPA, PitchNo, Balls, Strikes, RunsScored, OutsOnPlay, BatterSide, "
    "Pitcher, GameID, Angle"
)

def _sibling_ids(batter_id):
    name = query_df(
        "SELECT Batter FROM GAMES WHERE BatterId = :b AND BatterTeam = :t LIMIT 1",
        {"b": int(batter_id), "t": LMU_BATTER_TEAM})
    if name.empty:
        return [int(batter_id)]
    ids = query_df(
        "SELECT DISTINCT BatterId FROM GAMES WHERE Batter = :n AND BatterTeam = :t "
        "AND BatterId IS NOT NULL",
        {"n": str(name.iloc[0]["Batter"]), "t": LMU_BATTER_TEAM})
    return [int(x) for x in ids["BatterId"]] or [int(batter_id)]

def game_pitches(game_id, batter_id):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE GameID = :g AND BatterId IN ({ph}) "
        f"ORDER BY PitchNo", {"g": int(game_id), **idp})
    return _finish(df)

def season_pitches(batter_id):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"ORDER BY GameID, PitchNo", idp)
    return _finish(df)

def range_pitches(batter_id, start, end):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    idp["start"] = str(start); idp["end"] = str(end)
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end ORDER BY GameID, PitchNo", idp)
    return _finish(df)
```

> NOTE: `_finish` sets `Angle = NaN`; GAMES has a real `Angle`. Keep `_finish` as-is for hitting (the batting-line/zone transforms don't read `Angle`); BIP (Task 6) reads its own fresh `Angle` query. Parity is therefore asserted on transform OUTPUTS, not raw frames.

- [ ] **Step 4: Run parity test, verify pass** — `python -m pytest tests/test_hitting_caps.py -q`.

- [ ] **Step 5: Add parity tests for `plate_discipline` + `swing_decisions_by_zone` + `range_pitches`**

```python
from app.data.hitting import plate_discipline
def test_game_pitches_matches_plate_discipline_and_zone():
    gid = _first_game(WADAS)
    old = hitting_wh.wh_game_pitches(gid, WADAS); new = hitting_caps.game_pitches(gid, WADAS)
    pd.testing.assert_frame_equal(plate_discipline(new).reset_index(drop=True),
                                  plate_discipline(old).reset_index(drop=True), check_dtype=False)
    pd.testing.assert_frame_equal(swing_decisions_by_zone(new).reset_index(drop=True),
                                  swing_decisions_by_zone(old).reset_index(drop=True), check_dtype=False)

def test_range_pitches_matches_season_pitch_count():
    old = hitting_wh.wh_season_pitches(WADAS); new = hitting_caps.season_pitches(WADAS)
    assert len(new) == len(old)
```

- [ ] **Step 6: Run all Task-3 tests + commit**

```bash
git add app/data/hitting_caps.py tests/test_hitting_caps.py
git commit -m "feat(hitting): hitting_caps pitch loaders on GAMES + parity vs warehouse"
```

---

### Task 4: `hitting_caps` game list + scoreboard + player profile + parity

**Files:** Modify `app/data/hitting_caps.py`; Test `tests/test_hitting_caps.py`.

**Interfaces:**
- Produces: `games_for_batter(batter_id, start=None, end=None) -> DataFrame[game_id, game_date, GameLabel]`; `scoreboard(game_id) -> dict[date, loc, opp, game_type]`; `player_profile(batter_id) -> dict[name, bats, class_year, position, photo, jersey]`.

- [ ] **Step 1: Parity test for `games_for_batter` (labels + order identical)**

```python
def test_games_for_batter_matches_labels_and_order():
    old = hitting_wh.wh_games_for_batter(WADAS)[["game_id", "GameLabel"]].reset_index(drop=True)
    new = hitting_caps.games_for_batter(WADAS)[["game_id", "GameLabel"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(new, old, check_dtype=False)
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** (game list from GAMES; loc/opp from HomeTeam/AwayTeam + `HomeTeamForeignID == 78`; GameLabel formatted `%m/%d/%y {loc} {opp}` exactly as `hitting_wh`; scoreboard adds `game_type` from `GAMES.GameType`; profile reads `Batter`/`BatterSide` from GAMES + `roster_media.player_media` + `_roster_lookup` reused from `hitting_wh`).

```python
import pandas as pd
from app.data.hitting_wh import _roster_lookup
from app.data.roster_media import player_media

def games_for_batter(batter_id, start=None, end=None):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND Date BETWEEN :start AND :end"; idp["start"]=str(start); idp["end"]=str(end)
    df = query_df(
        f"SELECT DISTINCT GameID AS game_id, Date AS game_date, HomeTeam, AwayTeam, "
        f"HomeTeamForeignID FROM GAMES WHERE BatterId IN ({ph}){date_clause} "
        f"ORDER BY Date DESC", idp)
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    lmu_home = df["HomeTeamForeignID"] == LMU_TEAM_ID
    df["loc"] = lmu_home.map({True: "vs", False: "@"})
    df["opp"] = df["AwayTeam"].where(lmu_home, df["HomeTeam"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]
```

> Provisional: warehouse `opp` used `tm_team.team_name`; GAMES `HomeTeam`/`AwayTeam` hold the same names for backfilled games (verify in parity — if labels differ, adjust the opp source). `scoreboard`/`player_profile` mirror `hitting_wh.wh_scoreboard`/`wh_player_profile` reading GAMES instead of dim/fact.

- [ ] **Step 4: Implement `scoreboard` + `player_profile`, add parity tests** (assert `scoreboard(gid)` dict == warehouse's for a real game incl. `game_type`; `player_profile` name/bats match).

- [ ] **Step 5: Run + commit.**

---

### Task 5: `hitting_caps` season aggregates (QAB%, slash) — consolidated for speed + parity

**Files:** Modify `app/data/hitting_caps.py`; Test `tests/test_hitting_caps.py`.

**Interfaces:**
- Produces: `season_qab_rate(batter_id) -> float | None`; `slash_line(batter_id) -> dict[BA, SLG, OBP]`; `sidebar_stats(batter_id) -> dict[qab, BA, SLG, OBP]` (loads the season **once**, computes all four — fixes the 3.2 s double-load).

- [ ] **Step 1: Parity tests** — `season_qab_rate(WADAS) == hitting_wh.wh_season_qab_rate(WADAS)` (round 3) and `slash_line(WADAS) == hitting_wh.wh_slash_line(WADAS)`.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — reuse `hitting_wh.wh_slash_line`'s exact PA logic but sourced from `season_pitches` (GAMES); add `sidebar_stats` that calls `season_pitches` once and derives qab (`qab_frame`) + slash from that single frame.

```python
def sidebar_stats(batter_id):
    df = season_pitches(batter_id)          # ONE query (+ 1 sibling lookup), not two full loads
    if df.empty:
        return {"qab": None, "BA": "—", "SLG": "—", "OBP": "—"}
    q = qab_frame(df); total = len(q)
    qab = round(q["QAB"].sum() / total, 3) if total else None
    slash = _slash_from_pas(q)              # extract warehouse slash math into a pure helper
    return {"qab": qab, **slash}
```

- [ ] **Step 4: Run parity + commit.** (Refactor: extract `hitting_wh.wh_slash_line`'s PA loop into a pure `_slash_from_pas(pas_df)` in `hitting.py` so both modules share it — keep warehouse parity green.)

---

### Task 6: `hitting_caps` BIP + last-N PAs + LMU hitters + parity

**Files:** Modify `app/data/hitting_caps.py`; Test `tests/test_hitting_caps.py`.

**Interfaces:**
- Produces: `lmu_hitters() -> DataFrame[Batter, BatterId]`; `bip_points(batter_id, game_id) -> DataFrame` (== `wh_bip_points` shape); `last_n_pas(batter_id, n=27) -> DataFrame`.

- [ ] **Step 1: Parity tests** — `lmu_hitters()` row-set == warehouse `wh_lmu_hitters()` (same names/canonical ids); `bip_points(WADAS, gid)` == `wh_bip_points` on `x/y/rx/ry/hit_type` (GAMES `Angle` is real here — same math); `last_n_pas(WADAS,27)` length + PA keys match.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — `lmu_hitters` = `SELECT Batter, BatterId` deduped by name (ROW_NUMBER by COUNT(*)) `WHERE BatterTeam='LOY_LIO'`; `bip_points` = GAMES query `WHERE PitchCall='InPlay'` selecting `TaggedHitType, ExitSpeed, Angle, Bearing, Distance, PlayResult, PitchCall, TaggedPitchType, Pitcher, Balls, Strikes, GameID, Inning, PAofInning` then the identical spray/radial math from `wh_bip_points`; `last_n_pas` = the 27-PA window query against GAMES.

- [ ] **Step 4: Run parity + commit.**

---

### Task 7: Cut the hitting dashboard over to `hitting_caps` + smoke + full suite

**Files:** Modify `app/dashboards/hitting/callbacks.py`, `app/dashboards/hitting/layout.py`, `app/dashboards/hitting/selectors.py` (imports + call sites), and the sidebar to use `sidebar_stats`.

- [ ] **Step 1: Map the call sites** — grep `hitting_wh\.` under `app/dashboards/hitting/`; list every call (function + args). Expected: `wh_games_for_batter`, `wh_game_pitches`, `wh_range_pitches`, `wh_bip_points`, `wh_last_n_pas`, `wh_player_profile`, `wh_season_qab_rate`, `wh_slash_line`, `wh_scoreboard`, `wh_lmu_hitters`, `video_game_ids` (video stays until its own slice).

- [ ] **Step 2: Repoint imports** — change `from app.data import hitting_wh` call sites to `hitting_caps` equivalents (names without the `wh_` prefix per Task 3–6 interfaces); replace the sidebar's two calls (`wh_season_qab_rate` + `wh_slash_line`) with one `sidebar_stats`. Leave `video.py` calls untouched (its own slice).

- [ ] **Step 3: Full suite** — `python -m pytest -q`. Expected: all green (parity tests + existing).

- [ ] **Step 4: Live both-role smoke** — in-process `create_app` (CSRF off), load `/dash/hitting/` as coach + player (Wadas), render Game Level / Balls in Play / Last 27 tabs; confirm sidebar KPIs, game list, scoreboard populate from GAMES. Time the sidebar (expect a big drop from 3.2 s — now one season load).

- [ ] **Step 5: Commit** — `git commit -m "feat(hitting): cut hitting dashboard over to GAMES (hitting_caps)"`.

---

## Self-Review notes

- **Spec coverage:** Date normalization (T1), GameType (T2), all `hitting_wh` public functions reimplemented + parity (T3–T6), cutover (T7). `hitting_wh` retained as parity oracle → deleted in Phase 3. Video/pitching/catching = separate Phase-2 plans.
- **Parity philosophy:** assert on UI-consumed OUTPUTS (batting line, plate discipline, zone, slash, QAB, BIP math, game labels), not raw frames, because GAMES legitimately populates `Angle` where the warehouse NaN'd it.
- **Perf:** the sidebar consolidation (T5 `sidebar_stats`, one season load) is the first concrete hit at the profiled 3.2 s; more perf is Phase 5.
- **Provisional to verify during execution:** `GAMES.BatterTeam == 'LOY_LIO'` for LMU hitters; `HomeTeam`/`AwayTeam` names match the warehouse's `tm_team.team_name` labels (parity test on `GameLabel` will catch a mismatch).
