# SP1 — Pitching Dashboard Refresh (rename + RHH/LHH merge + filters)

Date: 2026-07-28
Status: Approved design (brainstorm) — ready for plan.

## Purpose

Apply the coaching-staff naming conventions to the dashboards, retire the
standalone RHH v. LHH tab by folding handedness in as a *filter toggle*, and add
count / result / handedness filters where the coaches asked for them. This is
the first of five sub-projects from the 2026-07-28 meeting.

## Scope

### 1. Tab + card renames

Internal `dcc.Tab` `value` keys are **kept unchanged** (so callbacks/tests that
branch on `tab == "location"` etc. do not churn); only the display `label`
changes.

Pitching dashboard (`app/dashboards/pitching/layout.py`):

| `value` | Current label | New label |
|---|---|---|
| `breakdown` | Pitch Breakdown | **Personal Breakdown** |
| `location` | Location / Movement | **Movement Profile** |
| `splits` | RHH v. LHH | **deleted** (see §2) |
| `outings` | Last Outings | **Outing Overview** |
| `pitchlevel` | Pitch Level | **Outing Video** |
| `counts` | Counts | **Count Performance** |
| `heatmaps` | Heatmaps | **Zone Frequency** |

Hub cards (`app/templates/main/pitching_hub.html`, `hitting_hub.html`):
"Stats Dashboard" → **"Player Dashboard"** on both the pitching and hitting hubs.

Catching dashboard (`app/dashboards/catching/layout.py`): the "Pitch Level" tab
label → **"Outing Video"** (keep its `value`).

Renaming applies "everywhere the names appear" (user decision 2026-07-28).

### 2. Retire RHH v. LHH → handedness toggle on Movement Profile

Delete the `splits` tab from the pitching `dcc.Tabs`, its `render`/`body`
branch in `callbacks._render_tab`, and the `splits-*` chip callbacks. Keep
`app/dashboards/pitching/tabs/rhh_lhh.py` deletion **and** remove now-dead
`splits_by_batter_side`/`fig_location_split` only if nothing else uses them
(verify; `fig_location_split` may be reused by the new toggle — prefer reuse).

The handedness split moves into **Movement Profile** as an All / vs RHH / vs LHH
**segmented toggle** (a `dcc.RadioItems` styled as pills), NOT the old
side-by-side usage tables. This is the user-approved interpretation of "combine
verse right/verse left into this tab … implement as a filter toggle, not
separate charts."

### 3. Movement Profile filters

`app/dashboards/pitching/tabs/location_movement.py` gains three filter controls
above the existing pitch-type color chips. All filters compose (AND) and drive
the Movement chart + Location chart + All Pitches table (the existing `body`):

- **Count filter** — a count-state multiselect reusing `P.count_states(df)` and
  the same `balls-strikes` masking already used by the Counts tab
  (`callbacks._counts_body`). Default = all present count states.
- **Result filter** — pitch outcome multiselect over `df["pitch_call"]` mapped
  through `P.pretty_result` (values: Ball / Called Strike / Whiff / Foul /
  In Play …). Default = all present outcomes.
- **Handedness toggle** — All / vs RHH / vs LHH, filtering `df["batter_side"]`
  (`Right`/`Left`). Default = All.

Implementation follows the existing chip pattern: a `-body` div re-rendered by a
callback that reads `game-data`, applies the pitch-type active set (existing
`lm-active` store) **plus** the three new filters, then calls
`location_movement.body(filtered_df)`. New component ids namespaced `lm-*`
(`lm-count`, `lm-result`, `lm-hand`).

### 4. Zone Frequency handedness toggle

`app/dashboards/pitching/tabs/heatmaps.py` already has an `hm-side` dropdown
(All / Right / Left) wired in `callbacks._hm_body`. Restyle it into a segmented
**All / vs RHH / vs LHH** toggle (RadioItems pills) for parity with Movement
Profile; keep the existing pitch-type (`hm-pt`) and count (`hm-count`) filters
and the `_hm_body` logic. This satisfies "add vs-left/vs-right split to Zone
Frequency, as a toggle not separate charts."

## Data flow

Unchanged plumbing: `selection` store → `game-data` (JSON df) → tab bodies. The
new filters are pure DataFrame masks applied inside the tab `-body` callbacks
before the existing chart/table builders run. No new queries.

## Components / interfaces

- `location_movement.render(df)` — adds the filter row (count/result/hand +
  existing chips) above `#lm-body`.
- `location_movement.body(df)` — unchanged signature; receives the pre-filtered
  df.
- New callback `_lm_body` inputs: `lm-active`, `lm-count`, `lm-result`,
  `lm-hand`; state `game-data`.
- `heatmaps.render(df)` — `hm-side` dropdown → RadioItems pills (same id/values,
  so `_hm_body` is untouched apart from the All/Right/Left value mapping which is
  preserved).

## Testing

- Update `test_pitching_dash.py`: tab labels assert the new strings; assert the
  `splits` tab is gone; assert Movement Profile renders count/result/hand
  controls; assert the filters mask the df (e.g. vs-RHH toggle drops Left rows).
- Update `test_home.py` / hub tests for "Player Dashboard".
- Catching + hitting tab-label tests updated.
- Keep the existing `is not None` render smoke tests; add at least one
  behavioral filter assertion per new filter.

## Provisional / coach-confirmable

- Folding RHH/LHH into a *toggle* (not side-by-side tables) — user-approved.
- "Result" = pitch outcome (user decision), not play result or contact quality.

## Out of scope

Sidebar stat tiles (SP2), report changes (SP3), bullpen (SP4), scheduling (SP5).
