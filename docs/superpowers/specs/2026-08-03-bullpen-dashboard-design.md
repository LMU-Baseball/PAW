# Bullpen Dashboard — Design Spec

**Date:** 2026-08-03
**Status:** Approved (brainstorming)
**Branch base:** current `feat/data-ingestion-loaders` state (BULLPEN now populated through 2026-05-13). Dashboard work will proceed on its own feature branch.

## 1. Goal

Give coaches (and players, self-scoped) an interactive, in-browser **Bullpen Dashboard** to:

1. Review a single bullpen session in detail (interactive version of the existing PDF report).
2. Track a pitcher's **development over time** across bullpen sessions (velo, spin, movement, command-proxy trends per pitch type).

The static PDF `Bullpen Reports (PDF)` at `/reports/bullpen` stays as-is; this dashboard is the explorable counterpart.

## 2. Data source

Reads the legacy `BULLPEN` table (raw Trackman practice-pitching export, PascalCase columns), freshly backfilled 2026-08-03 (24,581 rows, span 2023-09-17 → 2026-05-13). LMU scope = `PitcherTeam IN ('LOY_MAR','LOY_LIO')` (both codes confirmed present). One bullpen **session = one calendar date per pitcher** (confirmed: a pitcher throws at most one session per day; multiple same-day Trackman files merge).

`BULLPEN.PitcherId` **is the raw Trackman id**, so player self-scoping maps directly from `user.trackman_id` — no `tm_player_alias` lookup needed. The existing `can_view_bullpen(user, pitcher_id)` gate is reused verbatim.

## 3. Placement & entry point

- New card in `app/templates/main/pitching_hub.html` (4th in the `card_grid`):
  > **Bullpen Dashboard** — "Explore bullpen sessions and track pitch development over time." → `/dash/bullpen/`
- New Dash app mounted at `/dash/bullpen/`, registered in `app/dashboards/__init__.py` alongside hitting/pitching/catching/practice.

## 4. Package structure

New `app/dashboards/bullpen/` mirroring `app/dashboards/pitching/`:

| File | Responsibility |
|------|----------------|
| `index.py` | Thin app factory `build_bullpen_dash(server)`; uses shared shell `index_string`. |
| `selectors.py` | **Pure** role-aware helpers: `pitcher_options(is_coach, own_trackman_id)`, `resolve_pitcher(requested, *, is_coach, own_trackman_id)` (discards `requested` for a player, returns own id). Never reads `current_user`. |
| `layout.py` | `serve_layout()` (reads `current_user`, passes role+own id into pure selectors), `sidebar(pid, start, end)`, selector row, tabs, Stores. |
| `callbacks.py` | `register_callbacks(dash_app)`: selection → stores → sidebar/session-options/tab-content; tab bodies. |
| `tables.py` | `df_table(...)` DataTable helper (mirror pitching). |
| `charts.py` | Plotly figure builders (see §7). |
| `tabs/session_detail.py` | Pure render fn for Tab A. |
| `tabs/trends.py` | Pure render fn for Tab B. |

Reuses shared infra: `app/dashboards/shell.py` (`header`, `index_string`, `BANNER`, `CRIMSON`, `PHOTO_PLACEHOLDER`), `app/dashboards/date_range.py` (`date_picker`), `app/data/roster_media.py` (sidebar photo/jersey), `app/reports/plots.py::color_for` (consistent pitch-type colors).

## 5. Scoping

Exactly like the other game dashboards:
- **Coach:** pitcher dropdown enabled, may pick any LMU pitcher.
- **Player:** dropdown disabled, locked to self; `resolve_pitcher` discards any requested id and returns the player's own `trackman_id`. `can_view_bullpen` enforces this defensively.

## 6. Selector row, sidebar, date-range

**Selector row** (crimson `BANNER` bar): Pitcher dropdown · Date-range picker · Session-date dropdown (Tab A) · (scoreboard-style session label).

**Date-range picker** (`dr.date_picker("bp", ...)`):
- `min_date_allowed = 2025-09-01`, `max_date_allowed = today`. **All BULLPEN queries are bounded to this window** — the 2023–24 backlog is never loaded (performance guardrail; keeps the site within ~1 year of data for now).
- **Default selected range = the full bounded window** (2025-09-01 → present), so the Trends tab has a full season to plot. Mirrors the game dashboards, which default the range to the whole season.

**Session-date dropdown** (Tab A): the pitcher's session dates within the selected range, newest first (label = date + pitch count). **Defaults to the most-recent session** — mirrors how game dashboards open on the most-recent single game.

**Sidebar:** roster photo + name + `Throws {L/R}`, plus date-range-aware tiles:
`SESSIONS` (distinct dates) · `PITCHES` (rows) · `PITCH TYPES` (distinct TaggedPitchType) · `LAST` (most-recent session date). All computed within the selected range.

## 7. Tabs

### Tab A — Session Detail (value `session`)
Interactive version of the PDF report, for the one selected session date:
1. **Pitch-type summary table** — reuses `B.summary_by_pitch_type(session_pitches(...))`: pitch, qty, velo min/max/avg, spin min/max/avg, IVB, HB, VB, rel height, rel side, ext. Pitch-type names colored via `color_for`.
2. **Four Plotly charts** (`charts.py`): 
   - `velo_fig` — RelSpeed per pitch, points colored by pitch type.
   - `movement_fig` — IVB (y) × HB (x) scatter, colored by type, with per-type mean markers.
   - `release_fig` — RelSide (x) × RelHeight (y) scatter, colored by type.
   - `location_fig` — PlateLocSide (x) × PlateLocHeight (y) scatter with a strike-zone box, colored by type.
3. **Per-pitch table** — all pitches in the session (snake_case), ordered by PitchNo.

Empty-state when the pitcher has no session on the resolved date.

### Tab B — Development Trends (value `trends`)
"Development over time" across all sessions in the selected range:
- **Metric selector** (`dcc.RadioItems`, id `bp-trend-metric`): **Velocity · Spin · Movement · Command**. Swaps the single trend chart to keep it uncluttered.
- **Pitch-type chips** (`bp-trend-chips`, reuse the pitching `chip_row` pattern) to show/hide pitch types.
- **Trend chart** (`charts.trend_fig(df, metric, active_types)`): x = session date, one line (markers) per pitch type.
  - **Velocity:** avg RelSpeed (solid) + max RelSpeed (dashed) per type.
  - **Spin:** avg SpinRate + avg SpinAxis3dSpinEfficiency (secondary axis or paired lines).
  - **Movement:** avg InducedVertBreak + avg HorzBreak per type.
  - **Command (proxy):** per-type **plate-location spread** per session — e.g. RMS distance of (PlateLocSide, PlateLocHeight) from that type's session-mean location; lower = tighter. **Labeled as a consistency proxy, not true command** (bullpens have no intended-target column). Coach-confirmable.

Empty-state when the range contains fewer than 2 sessions (a trend needs ≥2 points) — show a note.

## 8. Data layer additions (`app/data/bullpen.py`)

Extend the existing module (existing `lmu_bullpen_pitchers`, `sessions_for`, `session_pitches`, `summary_by_pitch_type`, `bullpen_data_max_date` reused):

- `session_options(pitcher_id, start, end) -> DataFrame[date, pitches]` — sessions within `[start, end]`, newest first (date-bounded `sessions_for`).
- `bullpen_session_summary(pitcher_id, start, end) -> dict` — `{sessions, pitches, pitch_types, last_date}` for the sidebar tiles, within range.
- `trend_by_session(pitcher_id, start, end) -> DataFrame` — tidy per `(date, tagged_pitch_type)` aggregates: `velo_avg, velo_max, spin_avg, eff_avg, ivb_avg, hb_avg, loc_spread`. One query (plus a small pandas step for `loc_spread`); the trend chart pivots per selected metric.

All new helpers scope to `PitcherId = :pid` and `DATE(Date) BETWEEN :start AND :end`. Start/end always provided by the layout (bounded to the picker window).

## 9. Charts (`app/dashboards/bullpen/charts.py`, Plotly)

New interactive builders. Pitch-type color always via `plots.color_for(pitch_type)` for cross-app consistency. The existing `app/reports/bullpen_plots.py` (matplotlib) stays untouched — it serves the PDF; the dashboard gets its own Plotly figures. White plot background (readable over palms), zone box on `location_fig` reusing the established plate geometry.

## 10. Testing

- `tests/test_bullpen_dash.py` — pure `selectors` logic (coach sees options / player discards requested id), `serve_layout()` renders, each tab render fn returns a component (mirrors `test_pitching_dash.py` conventions).
- Additions to `tests/test_bullpen.py` — `session_options`, `bullpen_session_summary`, `trend_by_session` against the live DB (matches existing live-DB test convention; unguarded like `test_pitching.py`).

## 11. Provisional decisions (isolated, coach-confirmable)

1. **Session = one calendar date per pitcher** (confirmed by user).
2. **Command metric = plate-location spread/consistency proxy** (confirmed by user) — not true command.
3. **Date-range window = 2025-09-01 → present** for now (deliberate data cap; widen later).
4. **LMU scope = `PitcherTeam IN ('LOY_MAR','LOY_LIO')`** (inherited from `bullpen.py`; both codes verified present).

## 12. Out of scope

- Bullpen video (no bullpen video source).
- Coach notes / dev-plans on bullpen sessions (game dashboards have these; not requested here).
- Widening the date window past one year (performance decision, revisit later).
- Any change to the existing PDF bullpen report or the ingestion loaders.
