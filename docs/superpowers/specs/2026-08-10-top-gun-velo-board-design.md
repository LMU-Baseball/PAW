# Top Gun Velo Board — Design Spec (2026-08-10)

A pitcher velocity leaderboard for The PAW, replacing the Google-Sheet "Bluff
Inferno." Coaches maintain a weekly grid (mostly auto-filled from Trackman, a
couple of coach-entered columns); players see a branded, read-only Top-Gun-themed
heat leaderboard. This is the **pilot** that establishes the coach-edit-grid +
player-visual + AWS-append pattern the Competitive Cauldron will reuse.

## Decisions locked (user, 2026-08-10)

- **Auto-populate from Trackman day one.** Derivable columns compute from
  existing velo data; coaches enter only what Trackman can't know.
- **Velo source: both, season-aware.** Game outings when they exist (carry an
  opponent), bullpen/assessment velo as the offseason fallback.
- **Coach-entered columns: Velo Goal + Assessment.** Coaches can also override
  any auto cell before saving.
- **Cadence: stored weekly snapshots.** One row per (pitcher, season, week);
  change = this week vs last week; full history retained.
- **Access: coach edits, player views.** Players see the whole board (as the
  sheet did), read-only.
- Storage = a **new table in the existing RDS MySQL** (that is AWS; no new
  service). Follows the app's existing coach-writes-to-RDS pattern (coach notes,
  dev plans).

## Non-goals

Competitive Cauldron and Performance Council (separate specs). No Google Chat
push. No live snake-draft tool. No change to existing pitching dashboards/reports.

---

## Data model — `velo_board_entries` (new RDS table)

Append/upsert, one row per `(pitcher_id, season_label, week_start)`:

| Column | Source | Notes |
|---|---|---|
| `pitcher_id` | roster | RAW GAMES.PitcherId (== trackman id) |
| `pitcher_name` | roster | "Last, First" |
| `season_label` | derived | academic-year label (`seasons.py`) |
| `week_start` | selector | Monday of the tracked week (ISO date) |
| `velo_avg` | **auto** | avg Fastball/Sinker RelSpeed over that week (games+bullpens) |
| `velo_max` | **auto** | max Fastball/Sinker RelSpeed over that week |
| `velo_goal` | **coach** | target velo |
| `assessment` | **coach** | coach-recorded assessment/pulldown velo |
| `max_pr` | **auto** | running personal-best max across all stored + live history |
| `updated_by` | auth | coach user id |
| `updated_at` | server | timestamp |

- `change_avg` / `change_max` are **computed at read time** (this week's
  `velo_avg`/`velo_max` minus the pitcher's previous week row), not stored.
- Upsert semantics: saving a week that already exists updates it in place (so a
  coach can correct entries); a new week appends. Mirror the idempotent
  `chunked_insert`/notes write patterns already in `app/data`.
- `ensure_tables()` creates it if absent (same lazy-DDL pattern as
  `precalc.ensure_tables` / `notes`).

## Auto-population (data layer — new `app/data/velo_board.py`)

Velo = **Fastball/Sinker RelSpeed**, the same pitch set used everywhere else for
velo (`_pitcher_velo_appearances`, `avg_fb_velo`).

- **Weekly aggregates** (`velo_avg`/`velo_max` for a given `week_start`): union
  the pitcher's Fastball/Sinker pitches from **GAMES** (via the existing
  `_pitcher_velo_appearances` shape / a windowed query) and **BULLPEN** (via
  `bullpen.session_pitches`/`avg_fb_velo`) whose date falls in
  `[week_start, week_start+6]`; avg and max over the union.
- **Season leaderboard fields** (player visual, computed live, not stored):
  - `season_max`, `season_max_date`, `season_avg`: over the season's
    Fastball/Sinker pitches (games+bullpens).
  - `last_outing` velo + `date` + `versus`: the pitcher's most recent **game**
    appearance (opponent = the non-LMU team from `home_team_name`/`away_team_name`,
    LMU = HomeTeamForeignID 78); if no games yet this season, show the most
    recent bullpen velo with a blank/"—" opponent.
  - `trend`: last outing avg vs the prior appearance in the same season
    (reuse `velo_trend`'s `velo_change`), rendered as ▲/▼ + delta.
- **`max_pr`**: running max of `velo_max` across the pitcher's full stored +
  live history (a new PR flags in the coach grid, matching the sheet's yellow).
- Roster = `lmu_pitchers(season)` (already season-scoped).

All new readers `@cached`; the writer clears the cache (mirror `precalc`).

## Coach view — editable grid

- Coach-only (auth gate: `current_user.is_coach`). A player hitting the edit
  route is redirected to the visual.
- Controls: **Season** dropdown (default `current_season()`), **Week** picker
  (default = current/most-recent week).
- A `dash_table.DataTable` with `editable=True`, one row per rostered pitcher:
  auto columns (`velo_avg`, `velo_max`, `max_pr`, computed `change_*`)
  pre-filled and editable-as-override; coach columns (`velo_goal`, `assessment`)
  open. A **Save week** button upserts the week's rows into
  `velo_board_entries` and re-reads.
- New-PR cells highlighted (conditional style), matching the sheet.

## Player view — Top Gun leaderboard (visual)

- Read-only, all pitchers, ranked by velo (season max desc by default).
- **Header:** the Top Gun "wings + star" logotype recolored to **LMU crimson
  (#8C1D40) / blue (#2864A8)** with "COMPETE EVERYDAY," rendered as **inline
  SVG** (crisp, theme-safe, no external asset). Reuses the palm-tree banner
  motif already in the app.
- **Heat gradient** down the ranked rows (crimson = hardest throwers → blue =
  softest), matching the Bluff Inferno look.
- **Columns:** Pitcher · Season Max · Max Date · Season Avg · Last Outing · Date
  · Versus · Trend (▲/▼ + delta). (Superset of the sheet's visual.)
- Rebrand: title is **"TOP GUN"** (LMU-themed), retiring "Bluff Inferno."

## Routing / placement

- New page under Pitching, e.g. a Dash page at `/dash/velo-board/` (or a Flask
  page + Dash component, matching whichever pattern the pitching hub uses), with
  a link from the pitching hub (`app/templates/main/pitching_hub.html`).
- One page, two states by role: coach sees the grid + a preview of the visual;
  player sees only the visual.

## Access control

- Reuse `app/auth/access.py` + `current_user.is_coach`. Writes require coach;
  reads (visual) allowed for any authenticated user. Players are never shown the
  editable grid or a write route.

## Testing

- Data layer (TDD): weekly avg/max union over games+bullpens; season
  max/avg/last-outing/opponent derivation; `max_pr` running max; `change_*`
  vs prior week; empty-fall (no games) fallback to bullpen velo with blank
  opponent; upsert idempotency; roster scoping by season.
- Auth: coach can write, player cannot (route + function-level).
- Render smoke: coach grid renders with pre-filled auto columns; player visual
  renders the ranked heat board + inline-SVG header.
- No live Chat/draft anything.

## Rollout

Ship the velo board, then reuse this exact pattern (coach grid + AWS append +
player visual + role gate) for the Competitive Cauldron (its own spec).
