# Dashboard & Report Polish — Design Spec

**Date:** 2026-08-03
**Status:** Approved (brainstorming)
**Branch:** `feat/dashboard-report-polish-2026-08` off `main@0585847` (bullpen dashboard already merged).

A batch of coach-requested changes from a live review of the Bullpen Dashboard and the Pitcher Postgame Report, decomposed into 5 sub-projects (SP1–SP5). Built together on one branch, each independently reviewable.

---

## SP1 — Global date-range dropdown (all dashboards)

Replace the calendar-first `dcc.DatePickerRange` with a **preset dropdown** on every dashboard (pitching, catching, hitting-game, bullpen). The calendar is kept but only revealed for "Custom Range."

**Presets** (dropdown, in order): **This Season** (default) · Past Week · Past Month · Past 3 Months · Past 6 Months · Past Year · **Custom Range**.

**Semantics:**
- **Anchor date = the latest data date for the current selection** (the selected pitcher's most-recent session/outing date), NOT `today`. So "Past Month" = `[anchor − 30d, anchor]` and always lands on real data (works in the offseason).
- **"This Season" = the half-year block containing the anchor.** Blocks: Spring = Jan 1–Jun 30, Fall = Jul 1–Dec 31. Range = `[block_start, anchor]`. (Anchor 2026-05-13 → Spring 2026 → `2026-01-01 … 2026-05-13`.)
- **Custom Range** reveals the existing `DatePickerRange` calendar; picking dates sets the range directly.
- The single-item selector (session/outing/game dropdown) still defaults to the most-recent item in range (unchanged behavior).

**Shared component** (`app/dashboards/date_range.py`):
- `PRESETS` list of `(value, label)`.
- `season_block(anchor_date) -> (start, end)` — the half-year block containing `anchor`.
- `preset_range(preset, anchor_date) -> (start, end)` — resolves any preset to a `(start, end)` pair (Custom returns the current calendar values, handled in the callback).
- `date_control(id_prefix, anchor, selected_preset="season")` — renders the preset `dcc.Dropdown` (`{prefix}-date-preset`) + a `DatePickerRange` (`{prefix}-daterange`) hidden unless preset == "custom".
- Keep the bullpen window cap (`min_date=2025-09-01`) where it applies; game dashboards keep their existing data-driven bounds.

**Per-dashboard wiring:** each dashboard's layout uses `date_control(...)`; a callback resolves `preset (+ calendar if custom) → start/end`, then feeds the existing selection/store flow. The default selected preset is "This Season," computed from that dashboard's anchor. No change to the downstream data queries (they already take `start,end`).

**Testing:** `season_block` / `preset_range` pure-unit tested (fixed anchors → exact windows, incl. block boundaries Jun 30 / Jul 1); each dashboard still mounts and renders with the new control.

---

## SP2 — Bullpen dashboard polish

**Sidebar tiles** (`app/data/bullpen.py::bullpen_session_summary` + `app/dashboards/bullpen/layout.py::sidebar`): replace `Sessions/Pitches/Pitch Types/Last` with **Sessions · Pitches · Strike % · Avg FB Velo**.
- **Strike %** = share of pitches whose `(PlateLocSide, PlateLocHeight)` land inside the strike zone **plus a one-ball edge buffer** (≈ 2.9 in ≈ 0.24 ft beyond each zone edge). Zone box = the shared `_SZ` (x ±0.83 ft, y 1.5–3.5 ft). New helper `strike_pct(df_or_pid, ...)` — provisional (coach-confirmable buffer).
- **Avg FB Velo** = mean `RelSpeed` for `TaggedPitchType == 'Fastball'` in range; "—" if none. (Provisional: Fastball only, not Sinker/Cutter.)

**Fit side-to-side (no horizontal scroll)** (`session_detail.py` + `tables.py`):
- **Summary table** ("Stats by pitch type"): condense to fit page width — friendly Title-Case headers, **round all numbers to 2 decimals**, and collapse min/max/avg into compact columns where it helps readability (e.g. `Velo (min/avg/max)`), so the table needs no horizontal scroll at normal widths.
- **All-pitches table**: **renumber the pitch column 1…N within the displayed session** (currently shows raw Trackman `PitchNo` 33–48). Round every numeric cell to 2 decimals. Friendly headers. Condense to fit width.

**Chart hover / naming conventions** (`charts.py`) — all bullpen session charts get clean `hovertemplate`s:
- Velocity: `Velo: 78.4 mph` (pitch type in the point's group).
- Movement: `IVB: 12.3 in · HB: 8.1 in`.
- Release: `Rel H: 5.1 ft · Rel S: 1.7 ft`.
- Location: `<PitchType>` (+ optional plate coords), no raw tuples.
- Add the pitch type name into each hover.

**Movement chart**: add the **opaque light mean circle + 1σ ellipse per pitch type** (mirror `plots.movement_map_uri`'s hollow mean marker + `_add_ellipse`, ported to Plotly). **Location chart**: add the **nine-pocket** 3×3 grid inside the zone box (see SP5 shared zone helper).

---

## SP3 — Bullpen Velocity & Release redesign

Research-backed (Trackman one-pager conventions). Replace the two dot-strip charts in `app/dashboards/bullpen/charts.py`:

- **`velo_fig`** → **horizontal range-lollipop per pitch type**: one row per type, a thin min→max bar, a filled dot at the average, and the average value labeled at the dot (`91` etc.). Ordered by velocity (fastest on top). Matches Trackman "Avg. velocity by pitch type." Clean hover `Velo: 78.4 mph`.
- **`release_fig`** → **release-point dispersion plot**: equal aspect ratio, axes framed tight to the release cluster (data extent + small pad), per-type **mean marker + 1σ ellipse**, dots colored by type. From the pitcher's perspective (Rel side x, Rel height y). Tight cluster = consistent delivery reads clearly. Hover `Rel H: 5.1 ft · Rel S: 1.7 ft`.

Both keep `color_for` colors and the empty-state guard.

---

## SP4 — Bullpen Trends redesign (small multiples)

Kill the spaghetti-line single chart. `app/dashboards/bullpen/tabs/trends.py` + `charts.py`:
- **One mini-panel per pitch type**, laid out **2 per row** (N types → ⌈N/2⌉ rows). Each panel plots the selected metric over session dates for that one pitch type.
- The **Velocity / Spin / Movement / Command** RadioItems (`bp-trend-metric`) drives **all panels at once**.
- Within a panel: Velocity = avg (solid) + max (dashed); Spin = rate + efficiency; Movement = IVB + HB; Command = loc_spread. Small per-panel legend or title = pitch type name (colored).
- **Remove the pitch-type chip filter** (each type has its own panel now) — delete `chip_row`, the `bp-trend-active` store, and the chip callbacks.
- New `charts.trend_small_multiples(df, metric) -> Figure` using Plotly subplots (`make_subplots`, 2 cols). Shared date x-axis range across panels. Empty/one-session states preserved (a note when <2 sessions).

---

## SP5 — Pitcher report + shared visuals

**Report top bar** (`app/reports/templates/pitcher_onepager.html` + `app/data/pitching.py::header_stat_line`): add **Total Pitches · Strike % · Max Velo** to the KPI line (alongside the existing OUTS/H/R/BB/SO/PITCHES — dedupe if PITCHES already present). Strike% = existing report strike definition; Max Velo = max `rel_speed` over the outing.

**Gridlines** (`app/reports/plots.py`): add light gridlines to the report charts, especially horizontal gridlines on the velocity/zone charts (the horizontal ones make the velocity strip readable). Match the old report's subtle grid.

**Nine-pocket on EVERY strike zone, app-wide.** Factor a single shared zone-drawing helper and use it in every zone chart:
- Report zone charts already draw a 3×3 grid (`plots._draw_zone`) — keep.
- Add the 3×3 grid to: bullpen `location_fig` (SP2), and any hitting/catching/pitching dashboard zone/location charts that currently draw only the outer box. Enumerate all zone charts at plan time (grep for zone/plate_loc plotting) and give each the nine-pocket.

**Fastball callouts** (report + bullpen dashboard): in the whitespace under "Stats by pitch type," add a small callout block for the pitcher's Fastball: **Avg Velo · Max Velo · Avg Spin** (mirrors the Trackman one-pager's "Fastball / Pitch Speed Avg X Max Y / Total spin Avg Z"). New helper computing the three values from the loaded pitch df.

**Pitch-frequency bar** (report + bullpen dashboard): a **horizontal stacked bar** showing the pitch-type mix (each segment width ∝ count, colored by type, count labeled) with the total — the "Pitches: Total N" bar from the Trackman one-pager. New builder (matplotlib for report `plots.py`; Plotly for the dashboard) fed by pitch-usage counts.

---

## Cross-cutting notes

- **Provisional / coach-confirmable:** Strike% edge buffer size; Avg FB Velo = Fastball-only; season block boundaries (Jun 30 / Jul 1). Each isolated in one function.
- **Shared color source** stays `app.reports.plots.color_for`.
- **No data-model changes** — all new metrics derive from existing `BULLPEN` / warehouse columns already loaded.
- **Testing convention** unchanged: pure helpers unit-tested; live-DB render smoke; each dashboard still mounts.

## Out of scope
- Widening the bullpen date window past one year (SP1 keeps the 2025-09-01 cap on bullpen).
- Applying the SP2 pitcher-scoping fix to the sibling pitching dashboard (tracked separately in memory).
- KDE/violin velocity distributions (chose the range-lollipop for small bullpen samples; revisit if sample sizes grow).
