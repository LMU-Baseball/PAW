# PAW Changes Batch — Design Spec (2026-08-10)

Batch of 10 coach-requested changes across the Hitting, Pitching, Catching game
dashboards, the Hittrax batting-practice dashboard, the Bullpen dashboard, and the
pitcher/bullpen reports. Delivered on one feature branch, one commit per item.

Reference implementation for the two cross-cutting patterns (range-aware sidebar,
range-aware player list) is the **pitching dashboard sidebar**, which already reads
`range_summary(pid, start, end)`. Where a change says "mirror pitching," it means
follow that existing shape.

---

## Shared context

- **Shared date-range control** — `app/dashboards/date_range.py` `date_control(id_prefix, ...)`
  emits, per dashboard, a preset dropdown `f"{id_prefix}-date-preset"` and a
  `DatePickerRange` `f"{id_prefix}-daterange"` with `start_date` / `end_date`.
  Prefixes: `hit`, `pit`, `cat`, `prac`, `bp`.
- **Season dropdowns** (game dashboards only): `hit-season`, `pit-season`, `cat-season`.
- Selection stores already mirror `start`/`end`/`season`; `_on_range` callbacks already
  consume the `*-daterange` Inputs to rebuild the game/outing dropdowns, so the date
  values are readily available as callback Inputs.

---

## Group A — Sidebar KPIs follow the selected date range (Item 1)

**Goal:** the left-sidebar KPI cards reflect the currently selected date range instead
of always showing whole-season stats. Applies to Hitting and Catching; Pitching already
does this.

### Pitching
No change. `app/dashboards/pitching/callbacks.py` `_on_sidebar` already keys on
`pitcher-dd` + `pit-daterange` start/end and calls
`pitching_caps.range_summary(pid, start, end)`.

### Hitting
- `app/dashboards/hitting/callbacks.py` `_on_sidebar`: add
  `Input("hit-daterange","start_date")` + `Input("hit-daterange","end_date")` alongside
  the existing `hitter-dd` + `hit-season` Inputs; pass start/end to
  `layout.sidebar(bid, season, start, end)`.
- `app/dashboards/hitting/layout.py` `sidebar(...)`: accept `start`/`end`, forward to a
  range-aware `sidebar_stats`.
- `app/data/hitting_caps.py` `sidebar_stats(batter_id, season=None, start=None, end=None)`:
  add a range path. **Optimization (mirror pitching's `range_summary`):**
  - No dates, or dates exactly equal to the season bounds → read the fast precalc season
    rollup (`_season_rollup`), unchanged behavior for the default view.
  - Genuine sub-range → compute on the fly over pitches in `[start, end]` using the
    existing `qab_frame` / `_slash_counts` / `_slash_from_pas` helpers (the same compute
    path `_compute_season_rollup` uses, just with caller-supplied bounds).
- Sidebar caption changes from "Slash line = recent-season game data (provisional)." to
  language that reflects the selected date range (e.g. "Stats reflect the selected date
  range.").

### Catching
- `app/dashboards/catching/callbacks.py` `_on_sidebar`: add the two `cat-daterange`
  Inputs; pass start/end to `layout.sidebar(cid, season, start, end)`.
- `app/dashboards/catching/layout.py` `sidebar(...)`: forward start/end.
- `app/data/catching_caps.py` `framing_season_tiles(catcher_id, season=None, start=None, end=None)`:
  add a range path. `_compute_season_rollup` is already a single
  `WHERE CatcherId IN (...) AND Date BETWEEN :s AND :e` aggregate — the range variant is
  the same SQL with caller bounds. Keep the precalc fast path for the default
  (dates == season bounds or absent).
- Update the sidebar caption to reflect the date range.

**Tests:** for hitting and catching, assert (a) range == season bounds returns the same
values as the season rollup, (b) a narrow sub-range returns different, correctly-scoped
values, (c) the sidebar callback lists the daterange Inputs.

---

## Group B — Player dropdowns limited to the selected date range (Items 2, 9, all six dashboards)

**Goal (user-confirmed: ALL six dashboards):** only players/pitchers/catchers with data
in the selected date range appear as selectable options. When the date range changes, the
dropdown options refresh. No data in range → not in the dropdown. The date range remains
the primary filter (defaults unchanged: "This Season").

On the three game dashboards the roster is additionally scoped by the Season dropdown; the
date range nests inside the season, so the effective option list is "players with data in
[start, end]" (which is always within the selected season).

### Data-layer additions
- `app/data/practice.py` `players_in_range(start, end, exclude_test=True)` — `SELECT
  DISTINCT user_name FROM PRACTICE_SESSIONS WHERE session_date BETWEEN :start AND :end`
  (mirror the single-date `players_on_date`).
- `app/data/bullpen.py` `lmu_bullpen_pitchers(start=None, end=None)` — add an optional
  `DATE(Date) BETWEEN :start AND :end` clause to the existing GROUP BY query; no args
  keeps today's behavior.
- `app/data/hitting_caps.py` `lmu_hitters`, `app/data/pitching_caps.py` `lmu_pitchers`,
  `app/data/catching_caps.py` `lmu_catchers` — add optional `start`/`end` params that
  further scope the season-bounded roster query to the requested window.

### Callback / layout wiring
- **Game dashboards (hit/pit/cat):** the existing `_on_range` callback already fires on
  `*-daterange` start/end; add `Output("{hitter|pitcher|catcher}-dd","options")` to it
  (or a sibling callback) so the roster options rescope with the date range. Scope the
  `serve_layout` first paint the same way.
- **Hittrax (`prac`):** `_on_filters` already reads `prac-daterange` start/end but ignores
  them for the option list; recompute options from `players_in_range(start, end)`. Scope
  the `serve_layout` first paint (currently uses all-session names).
- **Bullpen (`bp`):** add `Output("bp-pitcher-dd","options")` keyed on
  `bp-daterange` start/end (mirror the existing session-dd refresh); back it with
  `lmu_bullpen_pitchers(start, end)`. Scope the `serve_layout` first paint.

### Selection fallback
When the current selection is not in the new option list, reselect the first available
player (and refresh the selection store / sidebar) rather than rendering a blank
dashboard. Coaches remain locked to self on player-role logins (existing access gate
unchanged).

**Tests:** each new/extended list query returns only in-range players; the options
callbacks list the daterange Inputs; a fallback test asserting an out-of-range selection
resolves to an available player.

---

## Group C — Hittrax dashboard

### Item 3 — All swing-decision zones selectable
`app/dashboards/hitting_practice/tabs/swing_frequency.py` `sds_zone_chip_row` and
`app/dashboards/hitting_practice/callbacks.py` `_sds_toggle` / `_sds_styles`.

Currently a zone is `disabled` and greyed when no pitches exist in it
(`disabled=z not in present`), and the toggle callback ignores clicks on absent zones.
Change so **all 13 zones are always selectable**:
- Remove the `disabled` gate (all chips enabled).
- Stop greying absent zones (style no longer keys "not present" to the disabled look) —
  or treat the present set as all zones for styling purposes.
- Relax the `_sds_toggle` guard so clicks on empty zones toggle normally.

The score function `swing_decision_score(df, in_zones=...)` already treats `in_zones` as
in-zone and simply finds nothing in empty zones, so selecting an empty zone is safe and
just contributes zero pitches. The separate EV/distance `sfz-*` chips are **out of scope**
(unchanged).

### Item 4 — Swing-decision trend hover
`app/dashboards/hitting_practice/charts.py` `swing_decision_trend_fig`.

The trend Scatter has no `hovertemplate`, so Plotly shows the default `(May 10, -20.9)`;
the stray "trace 5" is the unnamed `add_hline` zero-line.

- Add an explicit `hovertemplate` rendering **`{date} — Swing Decision: {score}%`**
  (e.g. "May 10 — Swing Decision: -20.9%"), fed via `customdata`/`text` from the existing
  `play_date` + `score` columns.
- Suppress the zero-line's hover (name it and set `hoverinfo="skip"`, or equivalent) so
  "trace 5" no longer appears.
- **No averages.** (User decided against adding avg distance / avg EV to this popup.)

**Tests:** figure smoke asserting the main trace carries a hovertemplate and the hline
does not surface as a hover trace.

### Item 5 — Session Tables tab freeze
`app/dashboards/hitting_practice/tabs/session_tables.py`,
`app/dashboards/hitting_practice/tables.py`,
`app/dashboards/hitting_practice/callbacks.py` `_render`,
`app/data/practice.py` `load_player_stats` / `load_sessions`.

No single unbounded render is obvious from static reading (tables are `page_size=15`).
**Approach: reproduce and profile before fixing (systematic-debugging).** Confirm the real
cause against live row counts. Leading suspects to validate:
- `load_player_stats` loads the summary for *all* players then discards all but one in
  Python — scope it to the selected player.
- `sort_action="native"` ships the entire result set to the browser for client-side
  paging/sorting — reduce shipped data / consider backend paging if the set is large.
- `_render` re-runs both queries on every `prac-pitch-data` / `prac-filters` / `prac-tabs`
  change — avoid redundant reloads.

Only apply the fix that the profiling shows is the actual cause; do not guess-patch.

---

## Group D — Pitching

### Item 6 — "In Play" → specific outcome
`app/data/pitching.py` (`pretty_result`, `fig_location`), and
`app/dashboards/pitching/tabs/location_movement.py` (table + Result filter).

Today the "Result" hover is built solely from `pitch_call` via `pretty_result(call)`, so
every ball in play reads "In Play". `play_result` (aliased `PlayResult AS play_result` in
`pitching_caps._PITCH_SELECT`) carries the real outcome (Single, Double, Triple, HomeRun,
Out, Error, Sacrifice*, …; Undefined/NULL for non-in-play pitches).

- Add a two-arg `pretty_result(pitch_call, play_result)` (or a sibling) that **prefers
  `play_result` when it is a real outcome** and otherwise falls back to the pitch-call
  label — reusing the logic already proven in `app/data/video.py` `_result` (with
  `_spaced` so "HomeRun" → "Home Run"). Preserve back-compat for any single-arg callers,
  or update them.
- Wire it into: `fig_location` (catcher-view scatter hover), the "All Pitches" table
  "Result" column, and the Result(s) filter option list — the filter then offers granular
  outcomes instead of a single "In Play".
- `fig_location_split` has no live callers; update it for consistency but it is not on the
  critical path.

**Tests:** `pretty_result("InPlay","Single")` → "Single"; `pretty_result("StrikeCalled",
None)` → "Called Strike"; `pretty_result("InPlay","Undefined")` falls back sensibly.

### Item 7 — Pitcher report ~10s
`app/reports/pdf.py` `html_to_pdf`, `app/reports/pitcher_postgame.py`,
`app/data/pitching_caps.py` `game_pitches`.

On a cache **miss** the dominant cost is Playwright launching a fresh headless Chromium
per request, plus `wait_until="networkidle"`. Cache hits (~0.4s) are fine.

- Reuse a **persistent shared browser** across requests (lazily launch once, keep alive)
  instead of `p.chromium.launch()` per call. Guard for thread safety under Flask.
- Use `wait_until="load"` — the HTML inlines fonts/logos/chart PNGs, so there is no
  network activity to idle-wait on.
- Add `@cached` to `game_pitches` (its sibling `game_pitches_for` is already cached).
- **Measure before/after.** Goal: cut the miss path well below 10s; keep hits ~0.4s.

**Tests:** existing report tests stay green; a timing assertion is optional (environment
dependent) — the acceptance check is a measured before/after in the session.

---

## Group E — Bullpen

### Item 8 — Bullpen report layout restructure
`app/reports/templates/bullpen_report.html`, `app/reports/static/report.css`,
`app/reports/bullpen_report.py`, `app/reports/bullpen_plots.py`,
`app/reports/plots.py` (`_donut`, `pitch_freq_bar_uri`).

The report is HTML/CSS (flexbox panels, WeasyPrint), each panel an independent matplotlib
PNG — so this is mostly a template/CSS change plus one chart swap and one chart tweak.

Current page 1: full-width pitch-frequency bar on top → 3-up (velo, movement, location) →
2-up (release, stats table). Desired page 1:

| Row | Left | Right |
|-----|------|-------|
| Top | **Stats by pitch type** (focal) | **Pitch frequency donut** |
| Middle | Location | Avg velocity by pitch type |
| Bottom | Movement | Release |

- Move the Stats-by-pitch-type table panel to top-left; make it the focal panel.
- Replace `pitch_freq_bar_uri` (the `(6.4, 0.7)` full-width bar) with a small **donut**,
  reusing the existing `_donut` helper in `plots.py`; place it top-right.
- Re-order the flexbox rows/`charts` dict for the middle and bottom rows above.
- Add faint **reference circles** to the Movement chart (`bullpen_plots.py` `movement_uri`)
  to show movement trend/spread — port the 1σ-ellipse pattern from the interactive
  dashboard's `charts.py` `movement_fig` / `_ellipse_xy`.
- Keep the Release chart (revisit later if players get lost in the data).
- Page 2 (per-pitch session table) unchanged.

**Tests:** report builds without error and the donut/movement functions return valid data
URIs; visual check of the rendered PDF in-session.

### Item 10 — "Command" → "Strike %"
`app/dashboards/bullpen/tabs/trends.py` (`_METRICS`, radio),
`app/dashboards/bullpen/charts.py` (`_METRIC_SERIES`, `_METRIC_YTITLE`,
`trend_small_multiples`), `app/data/bullpen.py` (`trend_by_session`, `strike_pct`).

Replace the "Command" radio option (which plots `loc_spread`, an RMS-distance
command-consistency proxy) with **"Strike %"**.

- `trends.py`: change `("command","Command")` → `("strikepct","Strike %")` (update default
  `value` if it pointed at command).
- `charts.py`: replace the `command` entries in `_METRIC_SERIES` / `_METRIC_YTITLE` with a
  `strike_pct` series (y unit "%").
- `bullpen.py` `trend_by_session`: add a per-`(date, pitch_type)` `strike_pct` column to
  the emitted `cols`. **BULLPEN has no PitchCall column**, so reuse the existing
  **zone-based** definition from `bullpen.strike_pct` (`plate_loc_side`/`plate_loc_height`
  inside the strike zone + one-ball edge buffer) — the same metric already shown in the
  report header KPI and the sidebar tile, so the value is consistent across the app.
- `loc_spread` computation can remain in the data layer (harmless) but is no longer
  surfaced in the UI.

**Tests:** `trend_by_session` output includes a numeric per-session `strike_pct`; the
trends metric list contains "Strike %" and not "Command".

---

## Out of scope / non-goals

- No change to the swing-decision *formula* (In-Zone% − Chase%) or the EV/distance
  (`sfz-*`) chips.
- No PitchCall column added to BULLPEN (strike% stays zone-based).
- No redesign of the Release chart (kept as-is).
- No change to the pitcher-report *content*, only its generation speed.

## Testing summary

TDD on all new/changed data-layer functions (range slash line, range framing tiles,
`players_in_range`, date-scoped rosters, per-session strike%, two-arg `pretty_result`).
Callback-wiring tests asserting the new daterange Inputs. Render smoke on the layout and
figure changes. Empirical profiling for the Session Tables freeze (Item 5) and the pitcher
report timing (Item 7) — those two are verified by measurement, not just unit tests.
