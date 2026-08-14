# Cauldron + Velo Board round — design (2026-08-13)

Coach-review changes to the Competitive Cauldron and Top Gun Velo Board: a
weekly challenge model for the cauldron, a shared edit UX for both boards
(buttons on top, grid hidden until Edit), a cauldron team-captain feature, a
readability fix, and a grid-compute speedup.

Out of scope (own spec later, per user): precalc-by-date-range (past
week/month/X via nightly cron). Deferred.

## Goals

1. **Cauldron = weekly challenge.** The scoreboard reflects a single **week**
   (Mon–Sun), reset each week — not all-season cumulative.
2. **Shared edit UX (both boards).** Edit/Save at the top; the editable grid is
   hidden by default and only shows while editing; Save persists and hides it.
   Remove the cauldron "Recompute auto" button.
3. **Team captain (cauldron).** A coach marks one captain per team; the captain
   sorts to the top of their team with a ★.
4. **Readability (cauldron).** The scoreboard reads on the page (fix
   white-on-white).
5. **Speed.** The cauldron grid updates faster; slower-with-more-data is
   mitigated.

## Current state (verified in code)

- `cauldron_teams(player_id, cycle_id, team)` PK `(player_id, cycle_id)`;
  `cauldron_daily(player_id, play_date, metric, raw_value, points, source)` PK
  `(player_id, play_date, metric)` — **no cycle_id, no week.**
- `visual.scoreboard_view(daily_df, teams_df, scoring_df, roster_names)` sums
  `daily_df` grouped by (player, metric) over **whatever daily rows it is
  given**; `layout.serve_layout` / `callbacks._refresh` pass **`read_daily()`
  with no date filter** → all-season cumulative.
- "Cycle" (`cauldron-cycle`) only scopes `read_teams(cycle_id)` (team
  assignments); it does **not** bound scoring.
- Grid always renders (locked `editable=False`); Edit unlocks, Save re-locks.
  Buttons (Edit / Save / **Recompute auto**) sit **below** the grid.
- `compute_players_day(pids, play_date)` is batched (1 query/day) but **not
  `@cached`** — re-runs on every render/save/date change.
- Scoreboard rows use `color:#fff` on `rgba(255,255,255,0.04)` over a white
  page → names + neutral values are invisible; only green/red cells show.
- Velo board: editable `velo-grid` renders above the read-only leaderboard,
  always present (locked); Edit/Save below it.

## Design

### 1. Cauldron weekly model

- Replace the **Cycle** dropdown with a **Week (starts Monday)** selector
  (`cauldron-week`), reusing `velo_board.week_start_for` to snap to Monday and
  the same "list recent Mondays" approach as the velo week picker.
- **Scoreboard is week-bounded.** `_refresh` / `serve_layout` pass a
  week-scoped daily frame: `read_daily` gains an optional `(start, end)` window
  (or reuse `player_totals`-style bounds) and the scoreboard sums only
  `week_start .. week_start+6`. Each week is independent (reset).
- **Teams persist across weeks.** Team assignments stay keyed by the season
  `cycle_id` (`{season}-c1`), unchanged — a coach drafts once, not weekly. The
  Week selector only bounds the *scoring* window, not team membership.
- The grid's **Date** picker stays for per-day entry; it defaults to a day
  within the selected week (today clamped into the week).

### 2. Shared edit UX (both boards)

- New shared helper (extend `shell.edit_save_buttons` or add
  `shell.edit_toggle`) rendering **Edit + Save at the top**, plus a status line.
- Wrap the editable grid in a container (`*-grid-wrap`) that is **hidden by
  default** (`style={"display": "none"}`). Edit → show + `editable=True`;
  Save → persist, then hide + `editable=False`. Same pattern for
  `cauldron-grid` and `velo-grid`.
- Cauldron: **remove `cauldron-recompute`** and its callback. No behavior is
  lost: the grid already prefills every AUTO metric with its live-computed
  value, and `save_grid` already persists those prefilled cells (tagged
  `source='auto'`) alongside manual edits. So auto scores persist whenever a
  coach Edits→Saves the day — exactly what "Recompute then Save" did, minus the
  redundant button. (`score_day` stays in the data layer for a future cron;
  only the button + its callback are removed.)
- Layout order per board: header → **buttons (top)** → hidden grid → read-only
  view (scoreboard / leaderboard).

### 3. Team captain (cauldron)

- Add `is_captain TINYINT(1) NOT NULL DEFAULT 0` to `cauldron_teams`
  (`ensure_tables` ALTER-if-missing, same pattern as other migrations).
- `set_team` / a new `set_captain(player_id, cycle_id)` sets the captain and
  **clears any prior captain on that team** (one per team).
- Grid: a **Captain** control per row (checkbox/dropdown) writing `is_captain`.
- `scoreboard_view`: within each team, the captain sorts **first** (above the
  points-sorted others) and renders with a **★** next to the name.

### 4. Readability

- Give the scoreboard table/container a **solid dark background** (e.g.
  `#161616` to match its header) so white text reads; keep green/red point
  tints. Verify with a rendered preview.

### 5. Speed

- `@cache.cached` on `compute_players_day` (keyed by the sorted pid tuple +
  play_date); invalidated by the existing `maybe_invalidate` gate. The grid
  prefill + Save baseline both hit it.
- Weekly-bounded scoreboard sums/renders only one week of `cauldron_daily`
  rows instead of the whole season → less to aggregate and fewer table rows.

## Data / schema changes

- `cauldron_teams`: **+`is_captain`** (migration in `ensure_tables`).
- `cauldron_daily`: **unchanged** (weekly bound is a read-time date window; no
  cycle_id needed — team membership carries the grouping, dates carry the
  window).

## Testing

- Data: `read_daily` window filter; week-bounded scoreboard sums only the
  week; `set_captain` enforces one-per-team + clears prior; `compute_players_day`
  memoized (2nd call no query).
- Visual: `scoreboard_view` puts the captain first with ★; dark background
  present; captain-less team unaffected.
- Dash: Edit shows the grid wrapper, Save hides it (both boards); Recompute
  button/callback gone; Week selector drives `_refresh`.
- Render both dashboards (coach + player) with no 500; preview PNG for the
  readability + captain change.

## Rollout

Fresh branch off the current work; subagent-driven. No precalc schema change
→ no rebuild. `cauldron_teams` ALTER is additive + idempotent.

---

## ADDENDUM (2026-08-13) — Velo board: one unified editable table

Coach feedback after the first round: the velo board's TWO tables (read-only
leaderboard + a separate hide-until-edit grid) are confusing — the coach wants
to "type right into the existing chart" and to fix bad readings (e.g. a 100.0
outlier in Season Max). Decisions (from the user): **one table**, **weekly
cadence** kept, editable **in place** (not a separate/hidden grid).

**Design:**
- Replace the HTML `leaderboard_view` + the separate editable grid with ONE
  `dash_table.DataTable` (id `velo-grid`) shown to everyone. Columns: Pitcher ·
  Season Max · Max Date · Season Avg · Last Outing · Date · Versus · Trend ·
  **Velo Goal** · **Assessment**. Heat-row gradient preserved via
  `style_data_conditional` keyed on `row_index` (rank 0 = crimson → last = blue,
  reusing `visual._row_color`).
- **In-place edit:** the table is read-only by default (`editable=False`). The
  editable columns (Season Max, Season Avg, Velo Goal, Assessment) are left
  WITHOUT a per-column `editable` flag so they inherit the table's; the other
  columns are pinned `editable: False`. Edit flips table `editable=True`
  (unlocking exactly those four in place); Save persists + flips it back. No
  hide-until-edit wrapper for velo (supersedes the round-1 velo grid wrap).
- **Storage / cadence:** Velo Goal + Assessment stay WEEKLY in
  `velo_board_entries` (`upsert_entries`). Velo corrections (Season Max /
  Season Avg) are SEASON-level overrides in a NEW `velo_board_overrides`
  (`pitcher_id`, `season_label`, `season_max`, `season_avg`, PK
  `(pitcher_id, season_label)`; additive table). `leaderboard(season)` applies
  an override when present (and re-ranks); Save writes an override only for a
  value the coach actually CHANGED vs. the computed baseline (so a fresh higher
  reading still surfaces for untouched rows), and clears the `leaderboard`
  cache (`leaderboard.cache_clear()`).
- `board_rows(season, week)`: roster (id+name) ⟵join⟶ `leaderboard(season)` by
  name (leaderboard is name-keyed) + weekly `velo_goal`/`assessment` from
  entries. Trend rendered as a precomputed "▲ x.x"/"▼ x.x" string for the
  DataTable.
- Player sees the read-only table (no Edit/Save, no selectors → default
  season/week); coach sees Edit/Save + Season/Week selectors. Coach-write
  double gate unchanged (save callback re-checks `is_coach`).

**Tests:** overrides applied + re-rank; changed-only override write on Save;
goal/assessment persisted weekly; edit toggles table editable; player has no
Save; board_rows merges by name.
