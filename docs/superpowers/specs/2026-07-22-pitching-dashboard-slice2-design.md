# Design: Pitching Dashboard — Slice 2 (refinements + roster media fix)

**Date:** 2026-07-22
**Branch:** `feat/pitcher-postgame-report` (continues the working branch)
**Status:** Approved — ready for implementation plan

Follows Slice 1 (`2026-07-22-section-hubs-and-pitching-dashboard-design.md`). Coach-feedback
refinements to the new pitching dashboard, one QoL nav change, and a roster-photo data fix.

## 1. Roster media fix (data) — the Bender mismatch

**Symptom:** the pitcher sidebar showed "#4 · Zachary Bender" with Noah Malone's photo.
**Root cause:** `instance/roster_media.json` is keyed by raw Trackman id and was built from
**hitters only**. Bender's pitcher raw id `832473` is *also* a 1-pitch **stray batter id
mis-attributed to Malone** (Memory §3d), so `pitcher_profile → player_media(pitcher_tm_id)`
returns Malone's card. **6 raw ids are shared between LMU pitchers and hitters**, so this is
systemic, and most pure pitchers have no entry at all (blank).

**Fix (decided: re-scrape all + tighter matching):** extend `scripts/scrape_roster_media.py`:
- Gather distinct `(raw_tm_id, name, n_pitches)` for **both** LMU batters (`batter_tm_id`/
  `batter_name`) **and** LMU pitchers (`pitcher_tm_id`/`pitcher_name`), from
  `fact_tm_game_pitch`.
- Match each to a roster card by the existing tightened logic (exact `_norm_name`, else
  **unambiguous** last + first-initial). Confident matches only — otherwise leave unmapped
  (render falls back to the lion placeholder; **never show a wrong face**).
- **Collision resolution:** when two different warehouse names claim the same raw id, keep
  the mapping for the identity with the **most tracked pitches** (dominant identity), so a
  1-pitch stray loses. This reassigns `832473` from the Malone stray to Bender-the-pitcher.
- Malone's hitter sidebar is unaffected — hitting uses his canonical id `832474`.
- Keep the `roster_media.json` shape + `player_media(id)` API unchanged, so
  `app/data/hitting_wh.py` and `app/data/pitching.py::pitcher_profile` call sites are untouched.
- **The controller runs the actual scrape** (needs network + the analytics DB) and verifies
  Bender → #42 + a real photo, plus a count of matched pitchers. The implementer writes the
  code; the controller regenerates the JSON.

## 2. Back arrow everywhere (QoL)

The Dash header already carries a "← Pitching" back link (Slice 1 `shell.header(back_href=…)`).
Add an equivalent back link to the **Jinja** pages that lack one — at minimum the Pitching
Reports landing (`app/templates/reports/pitching_landing.html`) → back to the Pitching hub
(`main.pitching`). Audit the other hub-child Jinja templates; any that lack a back link get
one to their logical parent. Reuse the existing back-link style already used on the hub pages
(`<p><a href=…>← Back to …</a></p>`) so it is consistent and future pages inherit the pattern.

## 3. Pitch Breakdown tab

- **Delete the "By Inning" sub-tab.** The Velocity chart shows **By Pitch Count only** — no
  `dcc.Tabs` wrapper, just the one chart (retitled e.g. "Velocity Across Outing").
  `fig_velo_by_inning` stops being used by the dashboard (leave the function in place; it is
  unused by the shipped report too).
- **X-axis = the pitcher's own pitch sequence (1…N) for THAT outing**, not the game-global
  `pitch_no`. The tab's df is already a single pitcher + single game (`game_pitches_for`),
  so compute a per-outing sequential index (order by `pitch_no`, then `1..N`) and plot velo
  against it. A reliever who entered at game pitch 100 shows their first pitch as **1**.

## 4. Location / Movement tab

- **Pitch-type filter = clickable color chips.** A row of pitch-type chips above the charts,
  each in that type's chart color, all selected by default. Toggling a chip filters the
  **movement chart, the location chart, AND the all-pitches table** together. Implement as a
  reactive control (a styled `dcc.Checklist` or chip buttons backed by a Store) with a
  callback that filters the game df to the selected types and re-renders the three outputs.
- **Location hover shows the pitch RESULT** (prettified `pitch_call` — Strike/Ball/In Play/
  Foul/HBP/…) instead of break.
- **Color the location + movement dots by pitch type** using one shared pitch-type→color map
  (reuse the existing chart color source so chips, charts, and any colored pitch names all
  agree). The location scatter is currently single-color — it becomes color-by-type.

## 5. RHH v. LHH tab

- **Color the vs-LHH / vs-RHH location dots by pitch type** (same shared palette as §4).
- **Add the same chip filter** to this tab — toggling filters both side location charts (and
  the per-side usage tables) by pitch type. (Filter state is per-tab; it does not need to be
  shared across tabs.)

## 6. Last Outings tab

- **Coach chooses how many outings** via a **preset dropdown: 3 / 5 / 10 / 15 / All** (default
  5). Selecting a value re-renders the table and the chart for the last-N outings (ending at /
  including the selected outing, newest first — same anchoring as today's `recent_outings`).
- **Add a time-series line chart of avg velo AND max velo** across the selected outings (x =
  outing date, two lines). Placed below the table.
- **Round** the Avg Velo / Max Velo columns to 1 decimal (they currently render long floats).

## 7. Components / files touched

- `scripts/scrape_roster_media.py` (+ maybe a small helper in `app/data/roster_media.py` for
  collision-aware build; `player_media` API unchanged).
- `app/templates/reports/pitching_landing.html` (+ any hub-child Jinja templates missing a back link).
- `app/dashboards/pitching/tabs/pitch_breakdown.py`, `location_movement.py`, `rhh_lhh.py`,
  `last_outings.py`.
- `app/dashboards/pitching/callbacks.py` (new callbacks for chip filters + outings-count dropdown).
- `app/data/pitching.py` — velo-by-pitch per-outing sequence; color map helper; location/
  movement/split figure changes (result-on-hover, color-by-type); a last-N outings helper
  parametrized by N (extend `recent_outings`/`averages_last5` or add a new function) + a velo
  trend figure over outings.
- Tests: extend `tests/test_pitching.py` (data/figure helpers) and `tests/test_pitching_dash.py`
  (tab renders + filter callbacks + outings-count).

## 8. Constraints (carry over from Slice 1)

Warehouse-only; LMU-only (`pitcher_team='LOY_LIO'`); role gating unchanged (chips/dropdowns are
display filters, not security boundaries); brand via the shared shell; no CDN; provisional
metric/color choices isolated + coach-confirmable. The Plotly `fig_*` builders in
`app/data/pitching.py` are **unused by the shipped one-pager report** (which uses matplotlib
`app/reports/plots.py`), so modifying them affects only the dashboard.

## 9. Deferred (unchanged from Slice 1)

Counts / Heatmaps / Pitch Level (video) tabs; coach notes on warehouse games; player-scoped
picker; the HitTrax practice hitting dashboard (own future spec); cross-tab shared filter state.

## 10. Success criteria

- Bender (and the other shared-id pitchers) show the correct photo/jersey or the placeholder —
  never a wrong face; matched-pitcher count reported.
- Every page reachable from home has a visible back link.
- Pitch Breakdown: single velo chart, x-axis 1…N per outing.
- Location/Movement + RHH: chip filter toggles all charts + tables; location hover shows result;
  dots colored by pitch type.
- Last Outings: N dropdown (3/5/10/15/All) drives table + a 2-line velo trend chart; velo rounded.
- Full test suite green; verified live (both roles) via the running app.
