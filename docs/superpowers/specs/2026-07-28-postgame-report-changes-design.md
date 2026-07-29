# SP3 — Post-Game Report Changes (VAA, usage donuts, contact key)

Date: 2026-07-28
Status: Approved design (brainstorm) — ready for plan.

## Purpose

Three coach-requested changes to the pitcher one-pager PDF
(`app/reports/pitcher_postgame.py` + `templates/pitcher_onepager.html` +
`plots.py` + `app/data/pitching.py`). The report stays a single Letter page,
in-process matplotlib rendering (no headless browser).

## Change 1 — "Spread" → VAA (Vertical Approach Angle)

- `P.movement_summary`: replace the provisional `spread` value (std dev of
  break magnitude) with **average `vert_appr_angle`** per pitch type. Column key
  `vaa` (drop `spread`). Warehouse column `vert_appr_angle` (decimal, 41,035 /
  41,188 populated) — verified 2026-07-28. Rounded to 1 decimal, degrees;
  values are typically negative (ball descending). Keep the None-guard for
  empty groups.
- `templates/pitcher_onepager.html`: Movement Summary header cell
  `Spread` → `VAA`; row cell `r.spread` → `r.vaa`.
- Tests: `test_pitching.py::movement_summary` asserts a `vaa` key, no `spread`.

## Change 2 — Pitch Usage table → donut charts

Replace the **Pitch Usage table panel** (template lines ~47–56) with three
donut charts matching the coach's preferred visual (meeting Image #4):

- **Overall** — usage % by pitch type (share of all pitches).
- **2K** — usage % among 2-strike-count pitches.
- **Splits** — a single split donut, vLHH on the left half | vRHH on the right
  half (two concentric/side half-rings labeled `vLHH | vRHH`), usage % by type
  within each side.

Rendering: matplotlib in `app/reports/plots.py`, consistent with the static PDF
engine. New `pitch_usage_donuts_uri(df) -> str` returning one base64 PNG data
URI containing all three donuts (one figure, 1×3 subplots) so the template
embeds a single `<img>` in the panel. Wedge colors use the existing
`plots.color_for(pitch_type)` palette; percentage labels on wedges ≥ a small
threshold (mirror the reference — center label "Overall" / "2K" / "Splits").
Data comes from the existing `P.pitch_usage_table(df)` fields
(`usage_pct`, `twok_usage_pct`, `vrhh`, `vlhh`) — no new query; add a small
donut-data shaper if convenient.

Template: the Pitch Usage `<div class="panel">` keeps its title, its `<table>`
body is replaced by `<img src="{{ charts.pitch_usage_donuts }}">`. The
assembler (`pitcher_postgame._build_html`) adds `charts.pitch_usage_donuts` to
the render context. `pitch_usage_table` stays (still unit-tested / usable) but
is no longer rendered as a table.

## Change 3 — Contact-result key on the zone charts

On the vRHH and vLHH zone plots (`plots.zone_chart_uri`), encode **contact
outcome by marker shape**, with a small shape legend:

- **Whiff** (`pitch_call == "StrikeSwinging"`) → circle `o`
- **Barrel** (`pitch_call == "InPlay"` & `exit_speed >= 95`) → x `X`
- **In Play** (other `InPlay`) → square `s`
- everything else (balls, called strikes, fouls) → small plain dot `.`

Color still encodes pitch type (`plots._color_for`), unchanged. Add a compact
shape-only legend (three glyphs) that does NOT overlap the zone (place below the
title or in a corner with tight bbox). The marker-shape mapping is a new small
helper `_contact_marker(row)`; the scatter loop groups by (pitch_type, marker).

Barrel here uses the simplified **95+ EV** definition (matches SP2's dashboard
Barrel%), not the LD/FB-qualified report `barrel_pct`.

## Provisional / coach-confirmable

- Contact key currently shows ALL pitches (takes/balls as plain dots) plus the
  three shaped contact classes. If the coach wants ONLY contact events shown
  (hiding takes/balls), that's a one-line filter change — flag it.
- VAA sign/formatting convention (negative degrees) — confirm display.
- Donut label threshold + the Splits half-ring layout — match the reference as
  closely as matplotlib allows; confirm on first render.

## Cache note

Editing report code changes output but the on-disk PDF cache
(`instance/report_cache/`) is keyed on `report_data_version` (latest game_date),
not code version — clear the cache after deploying these changes so existing
cached PDFs rebuild.

## Testing

- `test_pitching.py`: `movement_summary` VAA (above).
- `test_reports` (or the report test module): assert the render context now
  contains `charts.pitch_usage_donuts`; assert the template no longer emits the
  Pitch Usage `<table>` header row; a build smoke test still produces a valid
  PDF. `plots` unit: `pitch_usage_donuts_uri` returns a `data:image/png` URI;
  `_contact_marker` maps the four classes correctly.

## Out of scope

Dashboard changes (SP1/SP2), bullpen report (SP4), scheduling (SP5). The other
open report questions from memory §3b (season column, IP in header, velo bar,
zone-score grids, count-specific charts) are NOT in this sub-project.
