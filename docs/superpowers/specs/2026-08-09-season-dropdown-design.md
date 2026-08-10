# Season dropdown design

**Date:** 2026-08-09
**Status:** Design approved (brainstorm). Adds an academic-year Season filter to the Hitting/Pitching/Catching dashboards, backed by per-season precalc so any season stays fast.

## Goal

Let coaches pick a **season** (an academic year = fall + spring) as the primary scope on the three game dashboards, defaulting to the current season, without slowing the site.

## Season model

- **Academic year = Aug 1 → Jul 31**, labeled `"YYYY/YYYY+1"` (e.g. `"2025/2026"` covers Aug 2025 – Jul 2026, i.e. Fall 2025 + Spring 2026).
- **`season_bounds(label) -> (start, end)`** — pure: `"2025/2026" -> ("2025-08-01", "2026-07-31")`.
- **`available_seasons() -> list[str]`** — academic years present in `GAMES` (LMU, numeric-GameID), newest first. Cached (`@cached`) + warmed. Today: 2025/26, 2024/25, 2023/24, 2022/23, 2021/22.
- **`current_season() -> str`** — the academic year of `MAX(GAMES.Date)` (latest season **with data**), NOT today's calendar year. So 2025/26 now; auto-rolls to 2026/27 when fall-2026 games load. This is the dropdown's default.
- Some older seasons only have spring data — the model handles that (bounds still span the academic year; the data simply starts later).

## UI / interaction (season = outer scope, dates nest)

- A **Season dropdown, the first (leftmost) filter**, on Hitting/Pitching/Catching, options = `available_seasons()`, default = `current_season()`.
- Selecting a season sets, for that dashboard:
  - the **game list** (`games_for_batter/pitcher/catcher(id, *season_bounds)`),
  - the **date-range calendar bounds** (`min_date`/`max_date` = the season's clamped span) and the **default selected range** = the whole season,
  - the **sidebar KPIs** (read the (player, season) rollup),
  - the **default game** (most recent in that season).
- The existing date-range/preset control **refines within** the season (calendar clamped to season bounds). Today's half-year "This Season" preset is superseded by the dropdown; the default window is the full selected academic year.
- The selection store gains a `season` key threaded through the selection → sidebar/scoreboard/game-data callbacks.

## Precalc (per season)

The 3 rollup tables change from **one row per player** to **one row per (player, season)**:

- **Schema:** add `season_label VARCHAR(9)` to the PRIMARY KEY of `precalc_hitting_player_season` (PK `(batter_id, season_label)`), `precalc_pitching_player_season` (PK `(pitcher_id, season_label)`), `precalc_catching_player_season` (PK `(catcher_id, season_label)`). `season_label` already exists as a column; it moves into the key. (`precalc_meta` unchanged.)
- **Migration:** the precalc tables are a derived cache, so `ensure_tables` will `DROP` any table whose PK is the old single-column form and recreate with the composite PK (a one-time, safe drop+rebuild — no source data touched). Alternatively a guarded `ALTER`; drop+recreate is simpler and the rebuild repopulates.
- **Compute:** `_compute_season_rollup(id, season_label)` computes over `season_bounds(season_label)` (date-bounded) instead of the rolling window. Same metrics, same shared transforms.
- **Rebuild:** `rebuild_{hitting,pitching,catching}` loops over `available_seasons()` × each player, writing one row per (player, season). ~130 hitting rows (25 × ~5) + pitching/catching — still tiny; the rebuild does more compute but it's offline. Cache-clear + version-bump unchanged.
- **Read:** `read_{hitting,pitching,catching}_season(id, season_label) -> dict | None`.

## Data-layer changes

- `app/data/seasons.py` (new, pure + one cached query): `season_bounds`, `season_label_for(date)`, `available_seasons`, `current_season`.
- Sidebar/summary reads take a `season_label`:
  - hitting: `sidebar_stats(batter_id, season)`, `season_qab_rate`, `slash_line` → read (batter, season) rollup, compute-fallback over `season_bounds`.
  - pitching: `range_summary(pitcher_id, start, end)` keeps its signature but reads the (pitcher, season) rollup when the range == the season bounds (its existing "covers span" logic generalizes); a dedicated `season_summary(pitcher_id, season)` backs the sidebar.
  - catching: `framing_season_tiles(catcher_id, season)`.
- Game-list + pitch reads already accept `start`/`end` → pass `season_bounds`.

## Dashboard changes (×3, same pattern)

- `serve_layout`: prepend the Season dropdown; compute `season = current_season()`, derive the season's bounds + default game from `games_for_*(id, *bounds)`; seed the selection store with `season`.
- Callbacks: a season-change Input recomputes game options + date range + sidebar for the new season (players stay locked); the selection/sidebar/game-data callbacks read `season` from the store.
- Startup warm: warm the default (current) season for each module's default player (as today).

## Testing

- **seasons.py (pure/light):** `season_bounds("2025/2026") == ("2025-08-01","2026-07-31")`; `season_label_for` on Aug/Jul boundaries; `available_seasons()` newest-first + all valid labels; `current_season()` == academic year of `MAX(GAMES.Date)`.
- **Precalc:** rebuild writes one row per (player, season); `read_*_season(id, season)` == `_compute_season_rollup(id, season)`; a past season returns that season's numbers (differs from the current season's).
- **Dashboards:** serve_layout renders with the Season dropdown defaulting to `current_season()`; selecting a past season rescopes game list + sidebar; return shapes unchanged elsewhere.
- Full suite green; the `_pa_count`/parity/caching behaviors preserved.

## Out of scope

Bullpen + HitTrax dashboards (different date models — later if wanted); changing the report pages' season handling; any change to how games are ingested.

## Success criteria

Coaches pick a season (default = current) on all 3 game dashboards; it scopes game list + dates + sidebar to that academic year; any season's sidebar is a ~0.2 s 1-row read; full suite green.
