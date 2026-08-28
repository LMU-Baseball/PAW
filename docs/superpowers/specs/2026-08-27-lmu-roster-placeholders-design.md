# LMU Roster Placeholders — Design Spec (2026-08-27)

User handed over the official Fall 2026/2027 roster (`Roster Management.xlsx`, sheet `roster
26-27`: 47 players, last name + class year + position; first names filled in from the sheet's
`26-27 Breakdown` tab plus 5 names the user gave directly in chat — see §1). Wants these 47 players
to show up as the default roster everywhere in the app, and the default season flipped to
2026/2027, even though zero Trackman (GAMES/BULLPEN) rows exist for the season yet.

## 0. Why this needs new plumbing

Every roster-driven view in the app — Cauldron (`cauldron/layout.py::_roster_names`,
`cauldron/grid.py::coach_grid`), Velo Board (`app/data/velo_board.py` lines 301-419), and the
Hitting/Pitching/Catching dropdowns (`hitting_caps.lmu_hitters`, `pitching_caps.lmu_pitchers`,
`catching_caps.lmu_catchers`) — is built live from `SELECT DISTINCT ... FROM GAMES/BULLPEN`. There
is no LMU-specific "who's on the team" table anywhere. (The DB does have a table called
`roster_players` — 2,760 rows, 71 D1 schools, last scraped 2026-03-24/31 — but that's a nationwide
recruiting scrape used only for best-effort class-year/position bio lookups
(`app/data/hitting.py:_roster_lookup`), refreshed by an unrelated pipeline. It is explicitly NOT
reused here — a hand-maintained LMU-only table would collide in purpose with an auto-refreshed
nationwide scrape.)

Until a player actually throws a tracked bullpen or takes a tracked swing, they don't exist in the
app's notion of a "player" at all. This is the same wall documented in `memory/MEMORY.md` §11
(2026-08-25) for an earlier plain-text pitcher list; this spec is how we get past it.

## 1. Roster data

Source: `Roster Management.xlsx`, sheet `roster 26-27` (last name/class/position), cross-matched
by last name against sheet `26-27 Breakdown` (first names), with 5 gaps and 2 non-roster names the
user resolved directly:

- Matched by last name (42): see workbook.
- User-supplied first names (5): Geren→Lucas, Jacobsen→Gavin, Kaczynski→Will, Leitgeb→Brock,
  Marucci→Luca.
- Excluded (2, on the Breakdown $ tab but NOT on the roster tab — user confirmed not on the team):
  Alexander Chavez, Jacob Webster.

Final list (47, first/last/class/position) is committed as a small JSON file — see §2 — not
re-parsed from the 35MB workbook at runtime.

No jersey numbers or photos are collected — user confirmed the existing sun-lion placeholder
(already what `player_media`/`player_media_by_name` render when a photo is unmatched — see
`app/data/roster_media.py`) is fine for now. Nothing to change there.

## 2. Data model: `lmu_roster` table

New table, separate from the nationwide `roster_players` scrape table:

```sql
CREATE TABLE lmu_roster (
    roster_id     INT AUTO_INCREMENT PRIMARY KEY,
    season_label  VARCHAR(16)  NOT NULL,   -- e.g. "2026/2027"
    first_name    VARCHAR(64)  NOT NULL,
    last_name     VARCHAR(64)  NOT NULL,
    class_year    VARCHAR(16),             -- e.g. "RS JR"
    position      VARCHAR(8),              -- e.g. "RHP", "C", "1B"
    UNIQUE KEY uq_season_name (season_label, last_name, first_name)
);
```

Seed data lives at `data/rosters/2026-2027.json` (list of `{first_name, last_name, class_year,
position}` dicts) — committed to the repo since it's hand-curated, not scraped. A new
`scripts/load_lmu_roster.py` (mirrors `scripts/scrape_roster_media.py`'s shape) reads a season's
JSON file and upserts it into `lmu_roster` for that `season_label`, idempotently (safe to re-run
after edits). Adding a new season later = drop in a new JSON file + re-run the script with that
season's path.

`app/data/lmu_roster.py` (new module) exposes:

- `load_roster(season_label) -> pd.DataFrame` — `roster_id, first_name, last_name, class_year,
  position` for the season, empty DataFrame if none.
- `_position_group(position) -> str` — `"pitcher"` for RHP/LHP, `"catcher"` for C, `"hitter"`
  otherwise. Catchers are additionally treated as hitters (see §3) since real catchers already
  appear in both `lmu_hitters` (keyed on `BatterId`) and `lmu_catchers` (keyed on `CatcherId`)
  once they have live data — a placeholder catcher should behave the same way.
- Two-way players (a few pitchers who also hit, per the workbook's `26-27 Breakdown` tab) are
  classified by their single listed `PRIMARY` position only. Not tracked as a separate flag — a
  placeholder carries no stats either way, and once a player has real Trackman rows, they appear
  correctly in whichever list(s) their actual GAMES/BULLPEN rows put them in, independent of this
  table.

## 3. Read-path integration: placeholder union

`pitching_caps.lmu_pitchers`, `hitting_caps.lmu_hitters`, `catching_caps.lmu_catchers` each gain
the same shape of change (mirrors each other today, so this stays consistent):

1. Run the existing Trackman-derived query, as today (columns e.g. `PitcherId, Pitcher`).
2. Load `lmu_roster.load_roster(season)`, filter to the relevant `_position_group` (pitchers:
   `"pitcher"`; hitters: `"hitter"` + `"catcher"`; catchers: `"catcher"`).
3. Normalize names on both sides (reuse `roster_media._norm_name`-style last/first comparison) and
   drop any roster row whose name already matches a Trackman-derived row for that season — so a
   player with real data shows exactly once, under their real ID, never duplicated.
4. For remaining (data-less) roster rows, assign `player_id = -roster_id` and build a row in the
   same column shape as the Trackman query (e.g. `PitcherId=-roster_id, Pitcher="Last, First"`),
   append, and re-sort by name — same output contract every caller already expects, so
   `cauldron/grid.py`, `velo_board.py`, and the dashboard dropdowns need NO changes beyond this.

Negative IDs are chosen because Trackman-sourced IDs are always positive `BIGINT`s — this can never
collide, and every existing `player_id`/`pitcher_id`/`PitcherId` column is already a plain BIGINT,
so a placeholder flows through untouched (no schema changes needed anywhere downstream).

Downstream consumers that try to pull stats for a placeholder id (e.g. selecting a placeholder
player in the Pitching dashboard) will simply get empty results from every stats query, the same
as any real player with zero rows in a date range today — no special-casing needed, this is
already-handled behavior.

## 4. Write-path reconciliation: Cauldron + Velo Board

Cauldron (`cauldron_teams`, `cauldron_daily`) and Velo Board (`velo_board_entries`,
`velo_board_overrides`) are the only tables that *persist* coach-entered data keyed by
player_id/pitcher_id. If a coach assigns a placeholder player to a team or sets a velo goal before
that player has real Trackman data, and then real data starts flowing (giving them a real positive
ID), those saved rows would silently orphan under the old negative ID unless migrated.

New `app/data/lmu_roster.py::reconcile_ids(season_label) -> int` (returns rows migrated):

1. For each `lmu_roster` row with no matching Trackman row yet (i.e. still surfacing as a
   placeholder per §3), check whether one now exists (name match against
   `pitching_caps.lmu_pitchers(season)` / etc., depending on the roster row's position group).
2. For each newly-real match: `UPDATE cauldron_teams/cauldron_daily/velo_board_entries/
   velo_board_overrides SET player_id = :real_id WHERE player_id = :placeholder_id` (the four
   tables' real column names — `player_id` for Cauldron, `pitcher_id` for Velo Board).
3. Idempotent: once migrated, the placeholder id no longer appears (step 1 finds no more
   placeholder rows to check for that player), so re-running is always a safe no-op.

Exposed as a Flask CLI command, `flask roster reconcile [--season]`, following the existing
`flask ingest ...` pattern (`app/ingest/cli.py`) rather than running automatically inside a
`@cached` read path — keeps the read functions pure, keeps the write explicit and loggable. Run
it manually (or add to whatever cadence the BULLPEN/GAMES loaders end up on) after any new
Trackman data lands for the season.

## 5. Season default

`app/data/seasons.py::current_season()` currently returns the latest season **with real GAMES
rows** (`"2025/2026"` today), falling back to today's calendar season only when GAMES is entirely
empty — a deliberate guard against defaulting coaches onto a blank page. That guard is what's
currently keeping Hitting/Pitching/Catching on `"2025/2026"` even though `"2026/2027"` is already
selectable in the dropdown (`available_seasons()` already always includes today's calendar season,
landed 2026-08-25). Velo Board/Cauldron already bypass `current_season()` entirely and default to
today's calendar season directly (`cauldron/layout.py:63`).

**Fix:** `current_season()` simply returns `season_label_for(date.today().isoformat())` always —
drop the "prefer latest season with data" behavior. Safe now specifically because of §3: the
2026/2027 view won't actually be blank anymore, it'll show the 47 rostered placeholder players.

## 6. Scope boundaries

- No jersey/photo work (§1 — user confirmed not needed).
- No changes to `roster_players` (nationwide recruiting scrape) or its `_roster_lookup` helper.
- No automatic/cron-scheduled reconciliation — CLI-triggered only (§4); scheduling in general is
  still an open item tracked elsewhere (memory §10).
- Two-way players are not specially modeled (§2) — single-position classification only.
- Placeholder rows never carry stats; every stats query naturally returns empty for a negative id,
  which is already how the app renders "no data for this player" today — no new empty-state UI
  needed.

## 7. Testing

- `app/data/lmu_roster.py`: `load_roster` (empty/populated seasons), `_position_group` mapping,
  `reconcile_ids` (no matches / one match migrates all 4 tables / idempotent re-run).
- `pitching_caps.lmu_pitchers` / `hitting_caps.lmu_hitters` / `catching_caps.lmu_catchers`: union
  behavior — placeholder-only season, mixed real+placeholder (no duplicates), season with zero
  roster rows (unchanged existing behavior).
- `scripts/load_lmu_roster.py`: seeds correctly from the JSON fixture, re-run is idempotent
  (no duplicate rows, updates changed fields).
- `seasons.current_season()`: now always returns today's calendar season label.
- One live/manual check (per this repo's existing Playwright-smoke-test habit): open Cauldron and
  a Pitching dashboard and confirm all 47 names render with no numeric IDs visible anywhere.
