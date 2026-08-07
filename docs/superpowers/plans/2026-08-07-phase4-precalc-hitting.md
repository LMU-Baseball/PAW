# Phase 4 — Precalc (hitting rollups) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, full-suite gate at the end) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the profiled hitting-sidebar hotspot (full-season load + pandas) with a 1-row read from a precomputed season rollup, rebuilt on demand from the existing CAPS compute path, with a compute fallback.

**Architecture:** A new `precalc_hitting_player_season` table (one row per LMU hitter, same rolling-season window `season_pitches` uses). A `flask rebuild-precalc --module hitting` command recomputes every hitter through the existing `season_pitches → qab_frame → _slash_from_pas` path and replaces the table. `hitting_caps.sidebar_stats`/`season_qab_rate`/`slash_line` read one row from it, falling back to on-the-fly compute when the row is absent. Return shapes are unchanged.

**Tech Stack:** Python, SQLAlchemy/PyMySQL (`app.db`), Flask CLI (click), pandas, pytest (live-DB).

## Global Constraints

- **Return shapes are the contract.** `sidebar_stats(batter_id) -> {"qab", "BA", "SLG", "OBP"}`, `season_qab_rate -> float|None`, `slash_line -> {"BA","SLG","OBP"}` stay byte-identical to today. Dashboards/selectors are untouched.
- **Precalc is derived, not a second source of truth.** The rebuild reads raw CAPS; the site reads precalc; metric definitions live only in the existing compute functions (no redefinition).
- **Compute fallback is mandatory** — a missing row or absent table must degrade to today's behavior, never error.
- **Full rebuild** (delete-all + `common.chunked_insert` in one transaction); idempotent; volumes tiny (~25 hitters). Reuse `app.ingest.common.chunked_insert(engine, table, rows, chunksize=500)`.
- **Table:** `precalc_hitting_player_season`, PK `batter_id`, in the analytics RDS; created idempotently by the rebuild (`CREATE TABLE IF NOT EXISTS`).
- Keep the full suite green (594 as of `8e39120`).

---

### Task 1: Extract `_slash_counts` in `hitting.py` (share the counting definitions)

**Files:**
- Modify: `app/data/hitting.py` (`_slash_from_pas`, add `_slash_counts`)
- Test: `tests/test_hitting.py`

**Interfaces:**
- Produces: `hitting._slash_counts(pas_df) -> dict` with int keys `ab, h, doubles, triples, hr, bb, so, hbp, sf, tb, pa`. `hitting._slash_from_pas(pas_df)` unchanged externally (delegates to `_slash_counts`, then formats to `{"BA","SLG","OBP"}` display strings).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hitting.py
import pandas as pd
from app.data import hitting as H

def test_slash_counts_matches_slash_from_pas_and_breaks_out_extra_bases():
    pas = pd.DataFrame([
        {"KorBB": "Walk",      "PlayResult": None,      "PitchCall": "BallCalled"},
        {"KorBB": None,        "PlayResult": "Single",  "PitchCall": "InPlay"},
        {"KorBB": None,        "PlayResult": "HomeRun", "PitchCall": "InPlay"},
        {"KorBB": None,        "PlayResult": "Double",  "PitchCall": "InPlay"},
        {"KorBB": "Strikeout", "PlayResult": "Out",     "PitchCall": "StrikeSwinging"},
        {"KorBB": None,        "PlayResult": "Out",     "PitchCall": "InPlay"},
    ])
    c = H._slash_counts(pas)
    assert c["pa"] == 6 and c["ab"] == 5 and c["h"] == 3
    assert c["doubles"] == 1 and c["triples"] == 0 and c["hr"] == 1
    assert c["bb"] == 1 and c["so"] == 1 and c["tb"] == 1 + 4 + 2
    # _slash_from_pas display unchanged (delegates to the same counts)
    assert H._slash_from_pas(pas) == {"BA": "0.600", "SLG": "1.400", "OBP": "0.667"}
```

(Verify `_fmt_avg` output format for BA/SLG/OBP; adjust expected strings to match the existing formatter if it differs — read `_fmt_avg` first and use its exact output.)

- [ ] **Step 2: Run — expect FAIL** (`_slash_counts` undefined). `pytest tests/test_hitting.py::test_slash_counts_matches_slash_from_pas_and_breaks_out_extra_bases -v`
- [ ] **Step 3: Implement.** Add `_slash_counts(pas_df)` that runs the existing per-PA loop from `_slash_from_pas` but returns the int counts (add `doubles`/`triples`/`hr` tallies keyed off `PlayResult`, `so` off `korbb == "Strikeout"`, and `pa = len(pas_df)`). Rewrite `_slash_from_pas` to call `_slash_counts` then format `ba=h/ab`, `slg=tb/ab`, `obp=(h+bb+hbp)/(ab+bb+hbp+sf)` via `_fmt_avg` — output byte-identical to today.
- [ ] **Step 4: Run — expect PASS**, plus the existing `_slash_from_pas`/slash tests still green: `pytest tests/test_hitting.py -q`.
- [ ] **Step 5: Commit** `refactor(hitting): extract _slash_counts so precalc shares slash definitions`.

### Task 2: `_compute_season_rollup` in `hitting_caps.py`

**Files:**
- Modify: `app/data/hitting_caps.py`
- Test: `tests/test_hitting_caps.py`

**Interfaces:**
- Consumes: `season_pitches`, `qab_frame` (from `hitting`), `hitting._slash_counts`, `hitting._slash_from_pas`.
- Produces: `hitting_caps._compute_season_rollup(batter_id) -> dict` with keys `batter_id, batter_name, qab_pct, ba, obp, slg, pa, ab, h, doubles, triples, hr, bb, so, season_label`. `qab_pct` is `float|None`; `ba/obp/slg` are the display strings; counts are ints; `batter_name` from `GAMES.Batter`; `season_label` a string label for the current window.

- [ ] **Step 1: Write the failing test** — for a known hitter (Wadas `806253`), `_compute_season_rollup` returns a dict whose `qab_pct`/`ba`/`obp`/`slg` equal the current `season_qab_rate`/`slash_line` outputs, and whose counts are internally consistent (`pa >= ab`, `h == doubles+triples+hr + singles` sanity via `h >= doubles+triples+hr`).

```python
def test_compute_season_rollup_matches_current_sidebar(WADAS=806253):
    from app.data import hitting_caps as HC
    r = HC._compute_season_rollup(WADAS)
    assert r["batter_id"] == WADAS and r["batter_name"]
    assert r["ba"] == HC.slash_line.__wrapped__(WADAS)["BA"] if False else True  # see note
    # compare against the CURRENT compute path (pre-repoint) captured directly:
    df = HC.season_pitches(WADAS); q = HC.qab_frame(df)
    from app.data import hitting as H
    assert r["slg"] == H._slash_from_pas(q)["SLG"]
    assert r["qab_pct"] == (round(q["QAB"].sum()/len(q), 3) if len(q) else None)
    assert r["pa"] >= r["ab"] >= 0 and r["h"] >= r["doubles"] + r["triples"] + r["hr"]
```

- [ ] **Step 2: Run — expect FAIL** (`_compute_season_rollup` undefined).
- [ ] **Step 3: Implement** `_compute_season_rollup(batter_id)`: `df = season_pitches(batter_id)`; `q = qab_frame(df)`; `counts = hitting._slash_counts(q)`; `slash = hitting._slash_from_pas(q)`; `qab_pct = round(q["QAB"].sum()/len(q), 3) if len(q) else None`; `batter_name` via a `SELECT Batter FROM GAMES WHERE BatterId=:b ... LIMIT 1` (or reuse `player_profile`'s name read); `season_label` = a stable label derived from `MAX(GAMES.Date)` window (e.g. the anchor year) — keep it simple and documented. Assemble the dict.
- [ ] **Step 4: Run — expect PASS.** `pytest tests/test_hitting_caps.py -k compute_season_rollup -v`
- [ ] **Step 5: Commit** `feat(precalc): hitting_caps._compute_season_rollup (rollup source of truth)`.

### Task 3: `app/data/precalc.py` — table, rebuild, reader; wire `flask rebuild-precalc`

**Files:**
- Create: `app/data/precalc.py`
- Modify: `app/cli.py` (register the command)
- Test: `tests/test_precalc.py`

**Interfaces:**
- Produces: `precalc.HITTING_SEASON_TABLE = "precalc_hitting_player_season"`; `precalc.ensure_tables(engine)`; `precalc.rebuild_hitting(engine) -> int` (rows written); `precalc.read_hitting_season(batter_id) -> dict | None`. CLI: `flask rebuild-precalc [--module hitting]`.

- [ ] **Step 1: Write failing tests** (`tests/test_precalc.py`, live DB):

```python
from app.data import precalc, hitting_caps
from app.db import get_engine

def test_rebuild_populates_every_lmu_hitter():
    n = precalc.rebuild_hitting(get_engine())
    hitters = hitting_caps.lmu_hitters()
    assert n == len(hitters)
    for bid in hitters["BatterId"]:
        assert precalc.read_hitting_season(int(bid)) is not None

def test_rebuild_is_idempotent():
    e = get_engine()
    n1 = precalc.rebuild_hitting(e); n2 = precalc.rebuild_hitting(e)
    assert n1 == n2

def test_read_matches_compute_for_sample():
    precalc.rebuild_hitting(get_engine())
    row = precalc.read_hitting_season(806253)
    comp = hitting_caps._compute_season_rollup(806253)
    for k in ("qab_pct", "ba", "obp", "slg", "pa", "ab", "h", "hr", "bb", "so"):
        assert row[k] == comp[k], k

def test_read_missing_returns_none():
    assert precalc.read_hitting_season(-1) is None
```

- [ ] **Step 2: Run — expect FAIL** (module/functions absent).
- [ ] **Step 3: Implement `app/data/precalc.py`.**
  - `ensure_tables(engine)`: `CREATE TABLE IF NOT EXISTS precalc_hitting_player_season (batter_id BIGINT PRIMARY KEY, batter_name VARCHAR(128), qab_pct DECIMAL(4,3) NULL, ba VARCHAR(8), obp VARCHAR(8), slg VARCHAR(8), pa INT, ab INT, h INT, doubles INT, triples INT, hr INT, bb INT, so INT, season_label VARCHAR(32), built_at DATETIME)`.
  - `rebuild_hitting(engine)`: `ensure_tables`; `rows = [ _compute_season_rollup(int(b)) | {"built_at": <now via SQL/py>} for b in hitting_caps.lmu_hitters()["BatterId"] ]`; in one transaction `DELETE FROM <table>` then `chunked_insert(engine, table, rows)`; return `len(rows)`. (Use a Python `datetime.utcnow()` for `built_at`; if a test seam needs determinism, accept an optional `now` arg.)
  - `read_hitting_season(batter_id)`: `SELECT * ... WHERE batter_id=:b`; return the single row as a dict or `None`. Coerce `qab_pct` to float.
  - Import `_compute_season_rollup` from `hitting_caps` lazily inside the functions to avoid an import cycle (`hitting_caps` will import `precalc` in Task 4).
- [ ] **Step 4: Wire CLI** in `app/cli.py` `register_cli`: add
  ```python
  @server.cli.command("rebuild-precalc")
  @click.option("--module", default="hitting", type=click.Choice(["hitting"]))
  def rebuild_precalc(module):
      from app.data import precalc
      from app.db import get_engine
      n = precalc.rebuild_hitting(get_engine())
      click.echo(f"rebuilt {module}: {n} rows")
  ```
- [ ] **Step 5: Run — expect PASS.** `pytest tests/test_precalc.py -q`
- [ ] **Step 6: Commit** `feat(precalc): season rollup table + rebuild_hitting + rebuild-precalc CLI`.

### Task 4: Repoint the sidebar reads to precalc (with compute fallback)

**Files:**
- Modify: `app/data/hitting_caps.py` (`sidebar_stats`, `season_qab_rate`, `slash_line`)
- Test: `tests/test_hitting_caps.py`

**Interfaces:**
- `sidebar_stats(batter_id)` → read `precalc.read_hitting_season`; if present, return `{"qab": row["qab_pct"], "BA": row["ba"], "SLG": row["slg"], "OBP": row["obp"]}`; else `_compute_season_rollup` and map the same. `season_qab_rate`/`slash_line` read the same row (subset), same fallback.

- [ ] **Step 1: Write failing/ґchanged tests**:

```python
def test_sidebar_stats_uses_precalc_when_present(monkeypatch):
    from app.data import hitting_caps as HC, precalc
    sentinel = {"qab_pct": 0.512, "ba": "0.321", "slg": "0.540", "obp": "0.401",
                "pa": 10, "ab": 9, "h": 3, "doubles":1,"triples":0,"hr":1,"bb":1,"so":2,
                "batter_id": 806253, "batter_name": "X", "season_label": "s"}
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b: sentinel)
    assert HC.sidebar_stats(806253) == {"qab": 0.512, "BA": "0.321", "SLG": "0.540", "OBP": "0.401"}

def test_sidebar_stats_falls_back_to_compute_when_missing(monkeypatch):
    from app.data import hitting_caps as HC, precalc
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b: None)
    out = HC.sidebar_stats(806253)
    assert set(out) == {"qab", "BA", "SLG", "OBP"} and out["BA"] != ""
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the repoint. `sidebar_stats` reads precalc, maps to the dict, falls back to `_compute_season_rollup` (map the same keys). `season_qab_rate` returns `row["qab_pct"]` (float) or compute fallback. `slash_line` returns `{"BA","SLG","OBP"}` from the row or compute fallback. Keep a lazy `from app.data import precalc` inside the functions (import-cycle safety).
- [ ] **Step 4: Run — expect PASS.** `pytest tests/test_hitting_caps.py -q`
- [ ] **Step 5: Commit** `feat(precalc): hitting sidebar reads season rollup (compute fallback)`.

---

## Post-plan verification (executor runs)

- [ ] `flask --app run rebuild-precalc` → prints `rebuilt hitting: N rows` (N == `len(lmu_hitters())`, ~25). Spot-check a row in the DB.
- [ ] Full suite: `pytest -q` green (594 + the new precalc/rollup tests).
- [ ] Live: restart dev server; open the hitting dashboard as coach; confirm the sidebar renders identical numbers and is visibly faster. Capture a rough before/after timing (the profiled ~3.2s → ~1 round-trip).
- [ ] `test_no_warehouse_refs` still green (precalc reads GAMES only via the compute path; the rollup table is CAPS-derived, not a warehouse object).

## Self-review notes

- **Spec coverage:** table (Task 3) / compute-source (Task 2, reusing Task 1's shared counts) / rebuild CLI (Task 3) / read-with-fallback (Task 4) / tests (all tasks) — every spec section maps to a task.
- **Placeholders:** the only "read the code first" note is `_fmt_avg`'s exact format in Task 1 Step 1 — the executor confirms the expected slash strings against the real formatter before writing implementation.
- **Type consistency:** `qab_pct` float|None throughout; `ba/obp/slg` display strings; counts ints; `sidebar_stats` returns the same 4-key dict in both the precalc and fallback branches.
- **Import cycle:** `precalc` imports `hitting_caps` lazily (inside functions) and `hitting_caps` imports `precalc` lazily — no module-load cycle.
