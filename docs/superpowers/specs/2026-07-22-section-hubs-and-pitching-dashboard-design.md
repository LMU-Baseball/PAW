# Design: Section Hubs + Pitching Game-Stats Dashboard (Slice 1)

**Date:** 2026-07-22
**Branch:** `feat/pitcher-postgame-report` (continues the same working branch)
**Status:** Approved — ready for implementation plan

---

## 1. Motivation

Today the home page has three module cards (Hitting / Pitching / Catching) that jump
**directly** into a single destination each (Hitting → the Dash app, Pitching → the
postgame-report landing, Catching → disabled). Coaches keep asking for more per-section
capability. Cramming every feature onto one page per section would make each page slow to
load and hard to grow.

**Goal of this work:**
1. **Restructure navigation** so each section becomes a *hub*: clicking a section card
   opens a submenu of that section's actions (Stats Dashboard, Postgame Reports, …).
   New capabilities become new cards on a hub instead of new tabs on one ever-growing page.
2. **Build a new Pitching game-stats dashboard** (a Dash module mirroring the hitting one),
   reconstructing the most-used tabs of the old R pitching-coach app on the modern warehouse.

Out of scope for this slice but explicitly planned: a **HitTrax practice hitting dashboard**
(modeled on an existing Streamlit dashboard in another repo) — its own spec in a later session.

## 2. Reference: the old R pitching-coach dashboard

`src/app 4` (pitching-coach) had 7 game-stats tabs: **Pitch Breakdown** (coach-notes box +
pitch characteristics + pitch usage/batted-ball + velo trend by inning & pitch count),
**Location/Movement** (zone plots, movement map, clickable all-pitches table),
**Last Outings** (averages over last N appearances + trend plot + best-appearance table),
**Counts** (filter by count state → usage + location), **RHH v. LHH** (usage + location
split by batter hand), **Heatmaps** (density by pitch type / hand / count), and
**Pitch Level** (dual-angle pitch video).

**Slice 1 ports four:** Pitch Breakdown, Location/Movement, RHH v. LHH, Last Outings.
**Deferred to a later slice:** Counts, Heatmaps, Pitch Level (video).

## 3. Architecture decisions (settled during brainstorming)

- **Warehouse-based.** Built on the modern Trackman warehouse (`fact_tm_game_pitch`,
  `dim_tm_game`, `vw_pitcher_*`), the source of truth for new work — **not** legacy `GAMES`.
  Same decision as the hitting module (Slice 1, §3d).
- **Role-scoped exactly like hitting.** Coach picks any LMU pitcher + outing; player is
  locked to self via `current_user.trackman_id` → `pitcher_tm_id`. LMU-only
  (`pitcher_team = 'LOY_LIO'`, constant `P.LMU_PITCHER_TEAM`).
- **Navigation = Flask/Jinja hub pages** (not Dash, not a flattened mega-menu). Consistent
  with the existing home page and `pitching_landing`; zero new tech.
- **Extract the shared Dash shell now.** The hitting module's `index.py` INDEX_STRING
  (brand bg/palms/favicon/fonts), crimson header, and brand constants are duplicated
  boilerplate that any new Dash page must copy. Factor them into a shared module and
  refactor hitting to use it *before* building pitching, so there is one source of truth
  for brand chrome. (Memory §3d flagged this duplication as a Minor.)
- **Reuse existing pitching metrics.** `app/data/pitching.py` already computes pitch usage,
  movement summary, velo, and process/outcome primitives for the postgame report — the
  dashboard data layer extends that file rather than reinventing it.

## 4. Component design

### 4a. Navigation restructure (Flask/Jinja)

- **Home page (`app/templates/main/index.html`):** the three module cards now link to hub
  routes instead of terminal destinations: Hitting → `main.hitting`, Pitching →
  `main.pitching`, Catching → `main.catching`. Visual style unchanged.
- **Three hub routes** in the `main` blueprint (`app/main/routes.py`), all `@login_required`:
  `main.pitching` (`/pitching`), `main.hitting` (`/hitting`), `main.catching` (`/catching`).
  Each renders a hub template extending `base.html` that shows a grid of **action cards**.
- **Shared card partial.** Factor the module-card markup/style (currently inline in
  `index.html`) into a reusable Jinja partial (e.g. `app/templates/partials/_card_grid.html`
  or a macro) consumed by both the home page and the hub pages, so the card component has
  one definition. Supports enabled cards (link) and disabled "Coming soon" cards.
- **Hub contents (this slice):**
  - **Pitching hub:** `Stats Dashboard` → `/dash/pitching/` (new) · `Postgame Reports (PDF)`
    → `reports.pitching_landing` (existing).
  - **Hitting hub:** `Stats Dashboard` → `/dash/hitting/` (existing) ·
    `Practice Dashboard (HitTrax)` → disabled "Coming soon" (later spec).
  - **Catching hub:** disabled "Coming soon" card(s) only.
- **Back-navigation.** Hub pages link back to home; the Dash dashboards link back to their
  hub (in addition to the existing THE-PAW header that links home). Keeps home ↔ hub ↔
  dashboard traversable without the browser back button.

### 4b. Shared Dash shell (`app/dashboards/shell.py`)

New module holding what the hitting module currently hardcodes:
- `index_string(...)` — factory returning the Dash INDEX_STRING with the grey `--bg #f5f5f5`
  field, dark-grey palms (`palms-grey.png`), lion favicon, and Teko `@font-face` blocks.
  (INDEX_STRING can't read base.html CSS tokens, so brand values live here as the single
  hardcoded copy — see Memory §3c gotcha.)
- `header(user)` — the crimson banner component (LMU logo → home, "THE PAW" Teko wordmark,
  `{name} · {role} · Log out`).
- Brand constants (`CRIMSON = "#9A0021"`, blue, etc.) and the `_section(title)` header helper.

**Refactor:** update `app/dashboards/hitting/{index,layout}.py` to import from `shell.py`
instead of defining these locally. The existing hitting test suites
(`test_hitting_dash.py`, `test_shell.py`) must stay green — this is a behavior-preserving
refactor, verified by re-running them.

### 4c. Pitching Dash module (`app/dashboards/pitching/`)

Package mirroring `app/dashboards/hitting/`:
- `index.py` — `build_pitching_dash(server)`, uses `shell.index_string(...)`; mounts at
  `/dash/pitching/`; calls `register_callbacks`.
- `selectors.py` — pure, role-aware option builders + `resolve_pitcher()` self-only guard
  (coach: any LMU pitcher; player: locked to own `trackman_id`). No `current_user` inside.
- `layout.py` — sidebar + selector row (pitcher dropdown → outing dropdown) + `dcc.Tabs`
  (4 tabs) + `dcc.Store`s; reads `current_user` for role gating; includes the crimson
  header from the shell and a "← Back to Pitching" link to `main.pitching`.
- `callbacks.py` — selection → stores → per-tab renders; `register_callbacks(dash_app)`.
- `charts.py` — Plotly figures (zone scatter, movement map with 1σ ellipses, velo-trend
  line, usage bars) with stable per-pitch-type colors.
- `tables.py` — `dash_table.DataTable` builders (characteristics, usage, all-pitches,
  best-appearance).
- `tabs/{pitch_breakdown,location_movement,rhh_lhh,last_outings}.py` — pure render fns.

**Selection model:** pick pitcher → their outings (newest first, default = most recent),
directly analogous to hitting's pick-hitter → games.

**Sidebar:** roster headshot + `#jersey` (reuse `app/data/roster_media.py`), name /
class-year / **throws** (`pitcher_throws`), and season summary tiles (e.g. appearances, IP,
K, BB) computed from warehouse PAs. Blanks fall back to the lion placeholder (same pattern
as hitting).

**Tabs (map to the old R app):**
1. **Pitch Breakdown** — per-pitch-type characteristics table (avg/max velo, spin, IVB/HB),
   pitch-usage + batted-ball tables, and a velo-trend chart toggleable by Inning / Pitch
   Count. (No coach-notes box — see §6.)
2. **Location/Movement** — zone scatter by pitch type + movement map (IVB vs HB, 1σ
   ellipses, cluster means) + a clickable all-pitches DataTable. Closest parallel to the
   hitting module's zone tab; reuse its zone-computation approach where applicable.
3. **RHH v. LHH** — side-by-side usage tables + location scatters vs left- and
   right-handed hitters (`batter_side`).
4. **Last Outings** — averages across the last N appearances (N selector: 2–5), a trend
   plot, and a best-appearance table. Multi-game rollup via `vw_pitcher_recent_outings` /
   `vw_pitcher_appearance_summary`.

### 4d. Data layer (`app/data/pitching.py`, extended)

Reuse existing report helpers (pitch usage, movement summary, velo, process/outcome
primitives). Add dashboard helpers, all LMU-scoped:
- `wh_lmu_pitchers()` — one row per pitcher for the dropdown; **dedupe split Trackman ids**
  the same way the hitting module does (`_sibling_ids`, canonical = most-tracked id via a
  ROW_NUMBER window), so a pitcher with two `pitcher_tm_id`s unions cleanly.
- `games_for_pitcher(pitcher_id)` — that pitcher's outings, newest first.
- `wh_game_pitches(game_id, pitcher_id)` — pitch-level df for one outing (feeds tabs 1–3).
- Per-pitch-type **characteristics** (avg/max velo, spin, IVB/HB), **velo-trend** by inning
  and by pitch count, **L/R splits** (usage + location by `batter_side`), and **last-N
  outings** aggregation.

Column-aliasing to reuse existing tested transforms where practical (as the hitting module
did with `hitting_wh.py`). Provisional metric definitions are docstring'd and coach-confirmable.

### 4e. Testing

Mirror the hitting test suites:
- `tests/test_pitching_wh.py` — data transforms against the live DB (guarded the same way
  the existing live-DB tests are).
- `tests/test_pitching_dash.py` — pure render / selector functions (no DB).
- Extend `tests/test_shell.py` with hub-navigation assertions (routes render, cards link to
  the right endpoints, disabled cards are marked "Coming soon") and shared-shell assertions
  after the refactor.
- Keep the full suite green (currently 168 passing).

## 5. Data flow

```
Home card (Pitching)  →  /pitching hub  →  "Stats Dashboard" card  →  /dash/pitching/
                                          "Postgame Reports" card  →  /reports/pitching

/dash/pitching/:
  layout reads current_user (role) → selectors build pitcher options (coach=all LMU,
    player=self) → user picks pitcher → games_for_pitcher() → outing dropdown →
    callbacks load wh_game_pitches()/aggregations into Stores → each tab renders from Stores.
```

## 6. Known constraints / decisions

- **No coach-notes box in slice 1.** The old Pitch Breakdown tab had a notes textarea +
  submit. Warehouse games cannot be keyed to the legacy `NOTES` table (same blocker as the
  hitting module, Memory §3d). Rather than ship a non-functional control, the notes box is
  omitted this slice; revisit when warehouse-keyed notes exist.
- **INDEX_STRING hardcodes brand values.** The shared shell centralizes them to ONE place,
  but they still can't reference base.html's CSS tokens — a site-wide color change touches
  `shell.py` (once) in addition to `base.html`.
- **Provisional metrics.** New pitching metric definitions are provisional/coach-confirmable
  and isolated in docstring'd functions, consistent with the postgame-report approach.
- **Reliability caveat:** the warehouse pipeline's health is unconfirmed (Memory §9); this
  slice consumes existing data and does not depend on new ingests.

## 7. Deferred (future work)

- Pitching tabs: **Counts**, **Heatmaps**, **Pitch Level (video)**.
- **HitTrax practice hitting dashboard** — its own spec (review the Streamlit repo first);
  shows as a "Coming soon" card on the Hitting hub this slice.
- **Catching** module — hub is a "Coming soon" placeholder.
- Coach **notes** on warehouse games (blocked on warehouse-keyed NOTES).
- **Player-scoped picker** (a player sees only their own outings in the dropdown; download/
  view gate already enforces self-only).

## 8. Success criteria

- Home → each section hub → each action works, both roles, no console errors.
- Pitching dashboard: coach can pick any LMU pitcher + outing and see all four tabs render;
  player is locked to self and sees the same tabs for their own outings.
- Hitting module unchanged in behavior after the shell extraction (its tests still pass).
- Full test suite green.
