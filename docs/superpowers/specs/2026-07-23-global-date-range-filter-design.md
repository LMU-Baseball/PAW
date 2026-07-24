# Design: Global Date-Range Filter (Sub-project B)

**Date:** 2026-07-23
**Branch:** `feat/dashboards-date-range` (off `feat/catching-dashboard-rebuild` — so the rebuilt catching tabs are present; see §9)
**Status:** Approved for implementation (user, 2026-07-23)
**Part of:** a 3-sub-project enhancement set — **B (this)** → A (catching enhancements) → C (hitting-practice overhaul). A and C depend on B and get their own specs.

---

## 1. Motivation

Coaches want to review a **span** of games/practices — "last week's work" — not just one game or a fixed "3 weeks ago" preset. Today the game dashboards (Catching/Pitching/Hitting) pick exactly one game; the practice dashboard has only relative presets. This adds a **calendar date-range picker** to every stats dashboard and, on the game dashboards, an **"All games in range"** option that pools the games in the selected span.

## 2. Goals

1. Add a `dcc.DatePickerRange` calendar to all four stats dashboards (Catching, Pitching, Hitting, Hitting-Practice).
2. On game dashboards: the range scopes the game dropdown to in-range games and prepends an **"All games in range (N)"** option that aggregates them; default remains the most recent single game.
3. On practice: the calendar drives the existing range filter, kept **alongside** the quick presets.
4. No behavior regression for the current single-game / single-preset paths.

## 3. Non-goals / Deferred

- **Caching / precompute.** Recon shows current volumes are tiny (≤~1,300 pitch rows per player-season; ~18k practice plays total), so a per-selection query is fast. A short "future caching" note is included (§8) but no cache layer is built now.
- Cross-player or team-wide range aggregation (still one player at a time).
- The catching caught-stealing time-series visual and the practice visual overhauls — those are sub-projects A and C.

## 4. Confirmed decisions (from brainstorming)

- **Default range** = the selected player's full season span; **game dropdown defaults to the most recent single game** (dashboard opens exactly like today).
- **Practice** keeps the quick-preset dropdown **and** adds the calendar.
- **Hitting** Game-Level batting line, when "All games in range" is selected, becomes a **single combined line over the range** (totals/rates across those games), labeled as a range summary.
- **Aggregation is opt-in** via the "All games in range" dropdown entry — never automatic.

## 5. Architecture

### 5a. Shared helpers — `app/dashboards/date_range.py` (new)
Small, dependency-light module reused by all game dashboards:
- `ALL_IN_RANGE = "__all_in_range__"` — sentinel dropdown value.
- `date_picker(id_prefix, start, end, min_date, max_date) -> dcc.DatePickerRange` — a styled calendar (crimson accents, Teko) with ids `f"{id_prefix}-daterange"`; `display_format="YYYY-MM-DD"`.
- `game_options(games_df, *, n_label="game") -> list[dict]` — builds dropdown options: prepends `{"label": f"All games in range ({len(games_df)})", "value": ALL_IN_RANGE}` then one option per game (`GameLabel` → `game_id`). Returns `[]` when no games.
- `range_scoreboard_text(games_df, start, end) -> str` — `"{start} – {end} · {N} games"` for the aggregate scoreboard.
Pure functions (no DB, no `current_user`), unit-tested.

### 5b. Data layer — add a range filter + a pooled loader per game module
Backward-compatible additions (existing single-game functions untouched):

**Pitching (`app/data/pitching.py`)**
- Extend `games_for_pitcher(pitcher_id, start=None, end=None)` — when both given, `WHERE game_date BETWEEN :start AND :end` (still newest-first, sibling-union). Existing callers pass nothing → unchanged.
- `range_pitches_for(pitcher_id, start, end) -> df` — union all in-range games' pitches for the pitcher (sibling-id union, mirrors `game_pitches_for` but `game_date BETWEEN` instead of a single `game_id`).

**Catching (`app/data/catching.py`)**
- Extend `games_for_catcher(catcher_id, start=None, end=None)`.
- `range_pitches_for(catcher_id, start, end) -> df` — sibling-union across in-range games.

**Hitting (`app/data/hitting_wh.py`)**
- Extend `wh_games_for_batter(batter_tm_id, start=None, end=None)`.
- `wh_range_pitches(batter_tm_id, start, end) -> df` — sibling-union across in-range games (mirrors `wh_season_pitches` but bounded by date).

Each pooled loader returns the **same column shape** as its single-game sibling, so tabs consume it unchanged.

### 5c. Selector row + callbacks (each game dashboard)
- Selector row gains the date picker (id prefix = dashboard name, e.g. `pit`/`cat`/`hit`). Layout order: Player · Date range · Game.
- **New callback** `_on_range`: Inputs = player dd + date-range start/end → Output = game dropdown `options` + `value`. Computes in-range games via the extended `games_for_*`, builds options via `date_range.game_options`, sets value to the most recent single game (first non-sentinel option). If the range is empty, options = `[ALL_IN_RANGE]` only (or a disabled state) and the tab shows "No games in range."
- **Existing** `_on_selection` / data-load callback: when the game value is a concrete `game_id` → existing single-game loader (unchanged). When it is `ALL_IN_RANGE` → the pooled `range_pitches_for(...)` loader using the current range. The `selection`/`game-data` stores carry either the game_id or the sentinel + range.
- **Scoreboard:** concrete game → existing matchup; `ALL_IN_RANGE` → `date_range.range_scoreboard_text(...)`.
- **Default range:** `_on_selection`/layout seeds the picker to `[min(game_date), max(game_date)]` for the default player; the game dd defaults to the most recent single game.

### 5d. Per-tab behavior when `ALL_IN_RANGE` is selected
Tabs consume a pooled pitch/PA df and mostly "just work" (they already operate on a DataFrame that may span innings/PAs). Explicit handling:
- **Catching:** Overall Framing / Static Framing / Caught Stealing all pool naturally. (The caught-stealing *time-series* visual is sub-project A.)
- **Pitching:** Pitch Breakdown (characteristics pool), Location/Movement (pool), RHH v LHH (pool). Velo trend: use the existing per-*outing* trend (`fig_outings_velo_trend`), which is already multi-game. Last Outings unchanged (already multi-game; independent of this selection).
- **Hitting:** Plate Appearances / Zone Location pool their PAs. **Game Level** batting line → a single **combined** line computed over the pooled PAs (reuse `game_batting_line` on the pooled df; batted-ball profile likewise), with the note field blank and a "range summary" caption. Faceted "all PAs" small-multiples: cap at the **12 most recent PAs** when aggregating (avoids a 100-facet wall); when capped, show a caption "showing 12 most recent of N PAs."

### 5e. Practice dashboard (`app/dashboards/hitting_practice`)
- Add `dcc.DatePickerRange` (id `prac-daterange`) to the filter row, seeded from `P.date_bounds()`.
- Keep the existing `prac-date-preset` dropdown; selecting a preset sets the picker range (preset → `P.preset_date_range` → picker), and editing the picker sets preset to a "Custom" sentinel. The `prac-filters` store already carries `start`/`end`; wire the picker into it. `P.apply_filters` already filters by `start`/`end` — no data-layer change needed beyond exposing bounds.

## 6. Components & interfaces (summary)

| Unit | Responsibility |
|------|----------------|
| `app/dashboards/date_range.py` | `ALL_IN_RANGE`, `date_picker`, `game_options`, `range_scoreboard_text` (pure) |
| `pitching.games_for_pitcher(…, start, end)` / `range_pitches_for` | in-range games + pooled pitches |
| `catching.games_for_catcher(…, start, end)` / `range_pitches_for` | same |
| `hitting_wh.wh_games_for_batter(…, start, end)` / `wh_range_pitches` | same |
| each dashboard `layout.py` / `callbacks.py` | picker UI + `_on_range` + aggregate branch in load/scoreboard |
| practice `layout.py` / `callbacks.py` | calendar wired to existing `start`/`end` filter, presets kept |

## 7. Testing

- `tests/test_date_range.py` (new) — pure: `game_options` prepends the sentinel with correct count and empty-safe; `range_scoreboard_text` formatting; sentinel constant.
- Per-dashboard data-layer tests: `games_for_*(…, start, end)` filters correctly; `range_pitches_for` unions exactly the in-range games (synthetic/live per each module's existing convention).
- Per-dashboard dash tests: `_on_range` returns options with the sentinel + a most-recent default; selecting `ALL_IN_RANGE` routes to the pooled loader and every tab renders (live-DB smoke, matching each module's existing unguarded live test).
- Practice: picker ↔ preset ↔ `prac-filters` store round-trips; aggregation unchanged.
- Full suite stays green.

## 8. Performance (future caching note)

At present each range selection is a single indexed query (`game_date BETWEEN`, `player_id IN (siblings)`) returning ≲~1,300 rows (game) or a few thousand (practice) — sub-second. If seasons accumulate and wide ranges slow down, options in priority order: (a) cache `range_pitches_for` results by `(player_id, start, end)` in an in-process LRU keyed on a data-version token (mirror the report cache pattern), (b) precompute per-game aggregates in a summary table. Not built now; revisit when a range query exceeds ~1s.

## 9. Branch / sequencing

- Base branch = `feat/catching-dashboard-rebuild` (unmerged) so the rebuilt catching module is present. New branch `feat/dashboards-date-range`.
- A (catching enhancements) and C (practice overhaul) branch off this once merged/stacked. Recommend merging rebuild → B → A/C in order. Merge/creds settle per the standing baseline note.

## 10. Success criteria

- Each dashboard shows a working calendar date-range picker.
- Game dashboards default to the most recent single game; selecting "All games in range" pools the in-range games and every tab renders; scoreboard shows the range summary.
- Practice calendar + presets both work and agree.
- Single-game / single-preset behavior unchanged; full suite green.
