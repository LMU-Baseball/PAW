# Hitting Module — Slice 1 (Shell + Tabs 1–3) Design

**Date:** 2026-07-20
**Branch:** `feat/pitcher-postgame-report` (current working branch)
**Status:** Approved (brainstorming) → ready for implementation plan

## Goal

Build the first usable, end-to-end **Hitting** page in Dash by translating the
first three tabs of the R "Hitter Postgame" app (`src/app 1`) — the shell
(persistent sidebar + role-aware hitter/game selector + tab frame) plus:

1. **Game Level** — coach note, batting line, batted-ball profile.
2. **Plate Appearances** — per-PA strike-zone scatter + PA pitch table; all-PAs facet.
3. **Zone Location** — swing/take by zone + plate-discipline tables, zone-filtered scatter.

The analytical **data layer is already complete** (`app/data/hitting.py`, 16
tests passing against the live DB). This slice is the **UI + wiring** on top of it.

Tabs 4–7 (Last 27 PA, Spray/Radial, Video, Dev-Plans PDF), spray/diamond charts,
the real season slash-line source, and PA↔zone click-linking are **deferred** to
later slices (see §7).

## Context / why a slice

The full R hitter app is one ~2,600-line file with 7 tabs and ~15 visualizations,
plus video and a PDF viewer. Two pieces are blocked on external inputs:

- **Missing field-background images** `player.png` / `diamond_2.png` block the
  spray/diamond charts (memory §4, §6).
- **Season slash line** (BA/SLG/OBP) is a stub — the R app scraped lmulions.com;
  no source decided yet (memory §6).

So we build a **vertical slice**: the shell + the three tabs that have **no
blockers**, giving players and coaches a real page now, and add the rest in
subsequent slices.

## 1. Architecture (modular package — Approach A)

`app/dashboards/hitting.py` (current placeholder) becomes a package:

```
app/dashboards/hitting/
  __init__.py               build_hitting_dash(server) -> Dash; shared index_string
                            (grey+palms background + lion favicon, matching the site)
  layout.py                 serve_layout(): sidebar + selector row + dcc.Tabs frame
  selectors.py              role-aware hitter/game dropdown options + resolution
  charts.py                 Plotly figures: strike-zone scatter, faceted-PA figure
  tables.py                 Dash DataTable builders for the stat tables
  tabs/
    __init__.py
    game_level.py           render(game_df) -> components
    plate_appearances.py    render(game_df, appearance) + render_all_pas(game_df)
    zone_location.py        render(game_df, zone_choice) -> components
  callbacks.py              register_callbacks(dash_app): selection -> data -> tabs
```

Rules that keep boundaries clean and units testable:

- **No DB access inside `tabs/*`, `charts.py`, `tables.py`.** They receive
  pandas DataFrames (already-transformed via `app/data/hitting.py`) and return
  Dash components / Plotly figures. Pure functions of their inputs.
- **Only `selectors.py` and `callbacks.py` touch data-layer query functions**
  (`hitters_for_game`, `games_for_batter`, `game_pitches`, `game_notes`,
  `season_qab_rate`).
- **Only `selectors.py` reads `current_user`** for role scoping; tab renderers
  never see auth. Everything downstream operates on a resolved `batter_id`.

Each unit answers: what it does (render X from a df), how you use it
(`render(df, ...) -> component`), what it depends on (pandas + Dash, nothing else).

## 2. The shell

### Sidebar (persistent, left column)
- **Headshot** from the `PLAYERS` table URL (fallback: neutral placeholder box if
  URL missing/empty — no crash).
- **Identity block:** jersey number, name, class year, bats/throws.
- **Season stat tiles:**
  - **QAB%** — live via `season_qab_rate(batter_id)`.
  - **BA / SLG / OBP** — rendered as `—` placeholders with a small
    "season stats pending" caption. `season_slash_line` stays a stub (memory §6);
    tiles are wired so dropping in a real source later is a one-function change.
- **Scoreboard** for the selected game: LMU score vs Opp score with team logos
  from `STANDINGS` (logo URL columns), opponent name. Hidden until a game is
  selected.

### Selector row (top of main column)
- **Coach:** hitter-name dropdown (all LMU hitters, "Last, First") → game dropdown
  (that hitter's games, newest first, default = newest).
- **Player:** hitter fixed to self (shown as a label, no dropdown) → game dropdown.
- Game options come from `games_for_batter(batter_id)`. Hitter options for coaches
  come from a distinct-LMU-hitters query (see §4).

### Tab frame
- `dcc.Tabs` with three `dcc.Tab`s (Game Level / Plate Appearances / Zone Location).
- A `dcc.Store(id="selection")` holds the resolved `{batter_id, game_id}`.
- A `dcc.Store(id="game-data")` holds the current game's pitch DataFrame as JSON
  (loaded once per selection; tabs read from it).

## 3. Tabs

### Game Level (`tabs/game_level.py`)
- **Coach note** (read-only) from `game_notes(game_id, batter_id)` — empty state
  "No note for this game."
- **Batting line** table from `game_batting_line(game_df)`
  (PA, H, RBI, SO, BB, 2B, 3B, HR, QAB).
- **Batted-ball profile** — overall table (`batted_ball_profile(df)`) and
  by-pitch-type table (`batted_ball_profile(df, by_pitch_type=True)`).

### Plate Appearances (`tabs/plate_appearances.py`)
- **"Appearance" dropdown** (1..N PAs in the game) → **strike-zone scatter**
  (`charts.zone_scatter`) of that PA's pitches: drawn strike-zone boxes
  (Heart/Shadow reference rectangle), one marker per pitch colored by pitch type,
  hover shows pitch #, type, call, result, velo.
- **PA pitch table** for the selected appearance (pitch-by-pitch).
- **"All PAs" view:** faceted small-multiples (`charts.all_pas_figure`) — one
  mini strike-zone per PA across the game, markers = pitch sequence. Plotly facet
  (subplots) replacing the R base-plot `PA_all`.
- *Deferred:* video-angle radios; click-a-row-to-highlight linking.

### Zone Location (`tabs/zone_location.py`)
- **Zone-area dropdown**: All Swings / All Takes / Heart / Shadow / Chase / Waste
  → strike-zone scatter filtered to that selection.
- **Swing/Take by zone** table from `swing_decisions_by_zone(df)`.
- **Plate discipline** tables: by zone (`plate_discipline(df, by="zone")`) and by
  pitch type (`plate_discipline(df, by="pitch_type")`) — Swing%/Whiff%/Take%/Contact%.

## 4. Data flow & role enforcement

1. On load, `serve_layout()` builds the shell. For a **player**, the hitter is
   resolved from `current_user.trackman_id` and locked; for a **coach**, the
   hitter dropdown is populated.
2. Hitter/game selection → `callbacks.py` writes `{batter_id, game_id}` to the
   `selection` store, then loads `game_pitches(game_id, batter_id)` into the
   `game-data` store (JSON).
3. Each tab callback reads `game-data` (+ its own control value) and returns
   rendered components. Empty/no-selection states return a friendly placeholder,
   never an exception.
4. **Role guard:** `selectors.resolve_batter(requested_id, current_user)` returns
   the player's own id regardless of any client-supplied value; coaches pass
   through. Callbacks resolve through this so a tampered client input cannot pull
   another player's data. (Server-side gate, mirrors the pitching report's
   self-only rule.)

Hitter list for coaches: a distinct-LMU-hitters query. Add
`app/data/hitting.py::lmu_hitters(season_prefix="2025")` returning
`Batter, BatterId` (distinct, from `GAMES WHERE BatterTeam='LOY_LIO'`), ordered by
name — the one small data-layer addition this slice needs.

## 5. Visual style

- **PAW brand**, consistent with the rest of the app: grey `#f5f5f5` + `palms-grey.png`
  fixed background and lion favicon set via the package `index_string` (same as the
  current placeholder). Crimson `#9A0021` accents, blue `#0076A5`, Teko display font.
- Because the Dash `index_string` **hardcodes** bg color/image (can't use base.html
  CSS tokens — memory §3c), keep it identical to the site; note the duplication.
- Charts use stable per-pitch-type colors (reuse the palette convention already in
  the report `plots.color_for`; a small shared map is fine — do not over-couple to
  the report module).
- Tables: Dash `DataTable`, compact, brand header color.

## 6. Testing (`tests/test_hitting_dash.py`)

Follows the existing **live-DB, unguarded** convention (like `test_hitting.py`):

- `build_hitting_dash(server)` returns a Dash app; layout renders without error.
- **Role scoping:** with a coach user the hitter dropdown has options; with a
  player user the hitter is locked to self and `resolve_batter` ignores a
  spoofed id.
- **Selector data:** `lmu_hitters()` returns rows; `games_for_batter()` used for
  game options.
- **Each tab renderer** returns components for (a) a real game DataFrame and
  (b) an empty DataFrame (no crash, placeholder shown).
- **Chart/table builders**: `zone_scatter`, `all_pas_figure`, DataTable builders
  return the expected object types / non-empty figures for real data.

Auth in tests: reuse the app factory + login test helpers already used by the
existing auth/report tests.

## 7. Deferred (explicitly out of this slice)

- Tabs 4–7: Last 27 PA, Spray/Radial, Video, Dev-Plans PDF.
- Spray/diamond charts (need `player.png` / `diamond_2.png`).
- Real BA/SLG/OBP source (`season_slash_line` stays a stub; tiles show `—`).
- PA↔zone click-to-highlight linking; per-PA video-angle switching.
- `PAW_LOGS` visit logging on view (coach/player parity item; add later).
- Player-scoped niceties beyond the self-only guard.

## Open items / risks

- **Strike-zone geometry:** confirm the zone rectangle bounds/units used by the R
  plots (`PlateLocSide` / `PlateLocHeight` in feet) so the drawn boxes match the
  team's mental model. Pull exact constants from the R `location`/`zones_location`
  renderers during implementation.
- **Facet count:** a game can have up to ~6–7 PAs; the all-PAs facet must lay out
  cleanly for 1..~7 subplots.
- **`index_string` duplication** of brand colors is a known wart (memory §3c) —
  acceptable for now; a shared Dash index factory is a possible later cleanup.
