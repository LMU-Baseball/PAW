# Competitive Cauldron Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily team pitching competition — coaches enter/auto-score metrics, players see a team scoreboard — backed by new RDS tables. Ship the machine now with placeholder scoring config; the coach tunes the rubric in-app and the 4 non-standard metric formulas get wired once defined.

**Architecture:** New `app/data/cauldron.py` (storage + metric computation + scoring engine) and a new Dash dashboard `app/dashboards/cauldron/` at `/dash/cauldron/`. Directly mirrors the merged Top Gun velo board (`app/data/velo_board.py`, `app/dashboards/velo_board/`): RDS DDL via `ensure_tables()`, `ON DUPLICATE KEY UPDATE` upserts, `serve_layout` role-branch, double-gated coach writes, coach editable `DataTable` + player read-only visual.

**Tech Stack:** Python, Dash/Plotly, `dash_table.DataTable`, pandas, SQLAlchemy Core (`app.db.get_engine`/`query_df`), inline HTML/CSS visual.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-competitive-cauldron-design.md`.
- **Reference implementation to mirror (now on main): the velo board.** `app/data/velo_board.py` (ensure_tables/upsert/read/auto-compute), `app/dashboards/velo_board/{index,layout,callbacks,visual,grid}.py` (mount, role-branch, double-gated save, coach grid, player visual). Follow its shapes exactly.
- Locked: fixed per-metric scoring (`+points_met` / `+points_missed`); auto from Trackman where derivable, coach override wins; manual columns = Mod Command, Recovery Command, AH/Rehab; auto = Strike%, First-Pitch Strike, Early-&-Ahead, Pre-2K zone, 2K-Kill, K%, BB%, Off-Speed zone, count work, Barrel; Paw-only; coaches assign teams manually; coach edits / player views.
- The 4 non-standard metrics (Early-&-Ahead, Pre-2K zone, 2K-Kill, count work) have coach-specific formulas NOT yet provided → implement as clearly-marked `TODO` stubs returning `None` (config-present, not scored) so the rest ships. Standard metrics (Strike%, FPS, K%, BB%, Off-Speed zone, Barrel) compute now — REUSE existing `app/data/pitching.py` computations where they exist (K%/BB%/Barrel%/strike%) scoped to (pitcher, date).
- Pitcher id = raw `GAMES.PitcherId` == `User.trackman_id`. Roster = `pitching_caps.lmu_pitchers(season)`.
- Storage = new RDS tables in the existing analytics DB via `app.db`.
- Run tests in the FOREGROUND (env kills background bash ~5min); `PYTHONIOENCODING=utf-8 python -m pytest ...`. Commit per task. Do NOT push/merge. Branch: `feat/competitive-cauldron`.

---

### Task 1: Storage — `cauldron_scoring` / `cauldron_teams` / `cauldron_daily`

**Files:** Create `app/data/cauldron.py`; Test `tests/test_cauldron.py`.

**Interfaces:**
- Produces: `ensure_tables(engine=None)`; `seed_default_scoring()` (idempotent insert of the metric config rows from the spec with placeholder points, `ON DUPLICATE KEY UPDATE` NOTHING so it never clobbers coach edits); `read_scoring() -> DataFrame`; `upsert_daily(rows, updated_by=None)`; `read_daily(play_date=None, player_id=None) -> DataFrame`; `set_team(player_id, cycle_id, team, updated_by=None)`; `read_teams(cycle_id) -> DataFrame`.
- Tables per the spec (`cauldron_scoring` PK metric; `cauldron_teams` PK (player_id, cycle_id); `cauldron_daily` PK (player_id, play_date, metric)).

- [ ] **Step 1: Failing test** — ensure_tables idempotent; daily upsert insert-then-update; seed_default_scoring populates the metric rows and is idempotent; set_team upserts.

```python
def test_daily_upsert_and_team_and_scoring_seed():
    from app.data import cauldron as C
    C.ensure_tables(); C.seed_default_scoring()
    sc = C.read_scoring()
    assert "strike_pct" in set(sc["metric"]) and len(sc) >= 10
    C.upsert_daily([{"player_id": 999999002, "play_date": "2026-03-02",
                     "metric": "strike_pct", "raw_value": 58.0, "points": 20,
                     "source": "auto"}], updated_by=1)
    d = C.read_daily("2026-03-02", 999999002)
    assert int(d.iloc[0]["points"]) == 20
    C.set_team(999999002, "2026-c1", "Team 1", updated_by=1)
    assert C.read_teams("2026-c1").query("player_id == 999999002").iloc[0]["team"] == "Team 1"
    # cleanup
    from app.db import get_engine; from sqlalchemy import text
    with get_engine().begin() as c:
        for t in ("cauldron_daily", "cauldron_teams"):
            c.execute(text(f"DELETE FROM {t} WHERE player_id=999999002"))
```

- [ ] **Step 2: Verify failure** — module/tables absent.
- [ ] **Step 3: Implement** mirroring `velo_board.ensure_tables`/`upsert_entries`. `seed_default_scoring` inserts the spec's metric rows (metric key, label, threshold, direction gte/lte, placeholder points_met/points_missed, is_manual flag for command/recovery/rehab, min_sample, sort_order) with `INSERT ... ON DUPLICATE KEY UPDATE metric=metric` (no-op on conflict → never overwrites coach tuning).
- [ ] **Step 4: Run** — `pytest tests/test_cauldron.py -k "upsert or team or scoring" -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(cauldron): storage tables + scoring seed + daily/team upserts"`.

---

### Task 2: Metric computation from GAMES

**Files:** Modify `app/data/cauldron.py`; Test `tests/test_cauldron.py`.

**Interfaces:**
- Produces: `compute_player_day(pitcher_id, play_date) -> dict {metric: raw_value_or_None}` — one entry per AUTO metric. Standard metrics computed; the 4 non-standard return `None` (TODO stub, clearly commented). Returns `{}` if the pitcher has no GAMES pitch data that day.

- [ ] **Step 1: Failing test** — for a known (pitcher, game date) with data, standard metrics are populated and in range; non-standard are None; a no-data day → {}.

```python
def test_compute_player_day_standard_metrics():
    from app.data import cauldron as C, pitching_caps, seasons
    # pick a pitcher + a date they pitched (derive from _pitcher_velo_appearances)
    pid = int(pitching_caps.lmu_pitchers(seasons.current_season()).iloc[0]["PitcherId"])
    apps = pitching_caps._pitcher_velo_appearances(pid)
    date = str(apps.sort_values("game_date")["game_date"].iloc[-1])
    m = C.compute_player_day(pid, date)
    assert "strike_pct" in m and (m["strike_pct"] is None or 0 <= m["strike_pct"] <= 100)
    for stub in ("early_ahead", "pre2k_zone", "twok_kill", "count_work"):
        assert m.get(stub) is None   # not yet defined
    assert C.compute_player_day(pid, "1900-01-01") == {}   # no data
```

- [ ] **Step 2: Verify failure** — function absent.
- [ ] **Step 3: Implement.** Load the pitcher's GAMES pitch rows for `play_date` (sibling-id union via `pitching_caps._sibling_pitcher_ids`, mirroring the velo board fix). Compute: `strike_pct` (PitchCall strike set / pitches), `first_pitch_strike` (strike on pitch 1 of each PA), `k_pct`/`bb_pct` (KorBB per batter faced), `offspeed_zone` (in-zone rate on off-speed types), `barrel` (InPlay & exit velo ≥ barrel threshold, per PA/BIP — direction lte). REUSE `app/data/pitching.py` helpers where they already compute these (read that module first). The 4 non-standard metrics: return `None` with a `# TODO(coach-def)` comment each.
- [ ] **Step 4: Run** — `pytest tests/test_cauldron.py -k compute -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(cauldron): standard auto-metric computation from GAMES (non-standard stubbed)"`.

---

### Task 3: Scoring engine + team/cycle aggregation

**Files:** Modify `app/data/cauldron.py`; Test `tests/test_cauldron.py`.

**Interfaces:**
- Produces: `score_value(metric, raw_value, scoring_row) -> int|None` (fixed: meets threshold per direction → points_met else points_missed; None if raw None or below min_sample handled by caller); `score_day(play_date, season=None) -> int` (rows written: for each rostered pitcher compute metrics, score via config, upsert `cauldron_daily` with `source='auto'` — NEVER overwrite an existing `source='manual'` row); `player_totals(cycle_id, play_date_range=None) -> DataFrame` (points summed per player); `team_totals(cycle_id) -> DataFrame` (summed per team via `cauldron_teams`).

- [ ] **Step 1: Failing test.**

```python
def test_score_value_fixed_and_manual_not_clobbered():
    from app.data import cauldron as C
    row_gte = {"direction": "gte", "threshold": 55.0, "points_met": 20, "points_missed": -10, "min_sample": 0}
    assert C.score_value("strike_pct", 58.0, row_gte) == 20
    assert C.score_value("strike_pct", 50.0, row_gte) == -10
    row_lte = {"direction": "lte", "threshold": 6.0, "points_met": 15, "points_missed": -15, "min_sample": 0}
    assert C.score_value("bb_pct", 4.0, row_lte) == 15
    assert C.score_value("bb_pct", 9.0, row_lte) == -15
    assert C.score_value("x", None, row_gte) is None
```

- [ ] **Step 2: Verify failure** — functions absent.
- [ ] **Step 3: Implement.** `score_value` applies gte/lte vs threshold. `score_day` loops the roster, computes `compute_player_day`, joins `read_scoring()`, writes points via `upsert_daily` guarding manual rows (read existing `cauldron_daily` for that day; skip metrics already `source='manual'`). `player_totals`/`team_totals` aggregate `cauldron_daily.points` joined to `cauldron_teams`.
- [ ] **Step 4: Run** — `pytest tests/test_cauldron.py -k "score or total" -v` → PASS. (score_day is a live-DB integration path — a light smoke that it runs without error + writes ≥0 rows.)
- [ ] **Step 5: Commit** — `git commit -am "feat(cauldron): fixed scoring engine + player/team totals (manual override wins)"`.

---

### Task 4: Player scoreboard visual

**Files:** Create `app/dashboards/cauldron/__init__.py`, `app/dashboards/cauldron/visual.py`; Test `tests/test_cauldron_visual.py`.

**Interfaces:**
- Produces: `cauldron_header()` (LMU "Competitive Cauldron" branded header, inline SVG/HTML, mirror `velo_board/visual.top_gun_header` approach); `scoreboard_view(daily_df, teams_df, scoring_df) -> html.Div` — rows grouped by team (team header rows + players beneath), point cells green (met/positive) / red (missed/negative), per-player Total + team Total, columns ordered by `scoring.sort_order`.

- [ ] **Step 1: Failing test** — build from a small fixture: two teams, a couple players with points; assert team headers + player names + a team-total render; header contains "Competitive Cauldron".
- [ ] **Step 2: Verify failure** — module absent.
- [ ] **Step 3: Implement** mirroring `velo_board/visual.leaderboard_view` (html.Table, conditional cell colors, null-safe formatting, empty-df guard). Group rows by team; compute per-player and per-team totals from the daily points.
- [ ] **Step 4: Run** — `pytest tests/test_cauldron_visual.py -v` → PASS. Produce a preview PNG (Playwright, like the velo board) to `scratchpad/cauldron_preview.png`; note the path.
- [ ] **Step 5: Commit** — `git commit -am "feat(cauldron): player scoreboard visual grouped by team"`.

---

### Task 5: Coach grid — team assignment + daily entry/override

**Files:** Create `app/dashboards/cauldron/grid.py`; Test `tests/test_cauldron_grid.py`.

**Interfaces:**
- Produces: `coach_grid(play_date, cycle_id, season) -> html.Div` (Date picker `cauldron-date`, Cycle selector `cauldron-cycle`, editable `DataTable` id `cauldron-grid` one row per rostered pitcher with a Team column (editable dropdown) + metric columns (auto prefilled/overridable, manual open), a **Save** button `cauldron-save`, a **Recompute auto** button `cauldron-recompute`, status div); `save_grid(grid_data, play_date, cycle_id, updated_by=None) -> None` (maps rows → team upserts (`set_team`) + daily upserts (`upsert_daily`, marking coach-edited cells `source='manual'`)).

- [ ] **Step 1: Failing test** — `coach_grid(...)` contains ids `cauldron-grid`/`cauldron-save`/`cauldron-recompute` and is editable; `save_grid(...)` (with `set_team`/`upsert_daily` monkeypatched) routes team → `set_team` and metric cells → `upsert_daily` with `source='manual'`, attaching play_date.
- [ ] **Step 2: Verify failure** — module absent.
- [ ] **Step 3: Implement** mirroring `velo_board/grid.py` (editable DataTable, coach columns, blank→None coercion). Team column uses `presentation:"dropdown"` with Team 1..N options. `save_grid` splits team vs metric writes.
- [ ] **Step 4: Run** — `pytest tests/test_cauldron_grid.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(cauldron): coach grid (team assignment + daily entry/override)"`.

---

### Task 6: Dashboard assembly, registration, auth, hub card

**Files:** Create `app/dashboards/cauldron/index.py`, `layout.py`, `callbacks.py`; Modify `app/dashboards/__init__.py`, `app/templates/main/pitching_hub.html`; Test `tests/test_cauldron_dash.py`.

**Interfaces:**
- Produces: `build_cauldron_dash(server) -> Dash` at `/dash/cauldron/`; `serve_layout()` role-branched (always scoreboard; coach also gets the grid); `register_callbacks(dash_app)`.

- [ ] **Step 1: Failing test** — route registered (anon → 302); coach `serve_layout` contains `cauldron-grid`; player `serve_layout` omits it but shows the "Competitive Cauldron" scoreboard. Mirror `tests/test_velo_board_dash.py`.
- [ ] **Step 2: Verify failure** — dashboard absent.
- [ ] **Step 3: Implement** mirroring `velo_board/{index,layout,callbacks}.py`. Callbacks: Date/Cycle change → refresh grid + scoreboard; Save → re-check `is_coach` server-side → `save_grid` → refresh; Recompute → re-check `is_coach` → `score_day(date)` → refresh (manual overrides preserved). Register in `app/dashboards/__init__.py`; add hub card `{"title":"Competitive Cauldron","desc":"Daily team pitching competition.","href":"/dash/cauldron/"}`.
- [ ] **Step 4: Run** — `pytest tests/test_cauldron_dash.py tests/test_cauldron*.py -v` → PASS (coach-sees-grid / player-does-not; double-gated Save + Recompute).
- [ ] **Step 5: Commit** — `git commit -am "feat(cauldron): mount dashboard, role-branched layout, save/recompute callbacks, hub card"`.

---

## Final verification

- [ ] `PYTHONIOENCODING=utf-8 pytest tests/ -k cauldron -v` green.
- [ ] Live smoke: `/dash/cauldron/` as coach (assign teams, enter/override a day, Recompute, Save persists) and player (scoreboard only, grouped by team, totals). Hub card links.
- [ ] Do NOT push/merge — hand back for the coach to supply the real rubric (point values + the 4 non-standard formulas), then wire those.

## Self-review notes

- Spec coverage: storage/3 tables + scoring seed (T1), metric computation w/ non-standard stubs (T2), fixed scoring engine + manual-wins + team/cycle totals (T3), player scoreboard (T4), coach grid + team assignment + daily override (T5), assembly + role gate + registration + hub card (T6).
- Coach-write double-gated (layout hides grid + Save/Recompute callbacks re-check is_coach), mirroring the velo board.
- Non-standard metrics are config-present TODO stubs (return None) so the board ships; standard metrics compute now; point values are placeholder config the coach edits.
- Table/column names consistent across T1 (DDL), T3 (score_day writes), T5 (save_grid writes).
