# SP2 — Player-Card Sidebar Stats (date-range filtered)

Date: 2026-07-28
Status: Approved design (brainstorm) — ready for plan.

## Purpose

Make the pitching dashboard's left-bar season tiles reflect the metrics the
coaches asked for, and make them **respond to the date-range filter** instead of
always showing whole-season totals.

## Scope

Replace the current sidebar tiles **APP / PITCHES / K / BB**
(`app/dashboards/pitching/layout.py::sidebar` + `P.season_summary`) with:

**Appearances · IP · K% · Walk% · Barrel%**

...scoped to the currently selected date range.

## Data flow

`layout.sidebar(pitcher_id)` currently ignores the date range and calls
`P.season_summary(pid)` (a whole-career query). The reactive sidebar is
re-rendered by `callbacks._on_selection`, which already receives `start`/`end`.

Change:
- `sidebar(pitcher_id, start=None, end=None)` — new optional range args.
- New `P.range_summary(pitcher_id, start, end) -> dict` returning the five
  display strings. When `start`/`end` are None (initial load before the picker
  resolves) it falls back to whole-career (mirrors `season_summary`).
- `_on_selection` passes `start`/`end` into `layout.sidebar(...)`.

`range_summary` queries the same sibling-id union as `season_summary`, bounded
by `dim_tm_game.game_date BETWEEN :start AND :end` (join to `dim_tm_game`, same
pattern as `range_pitches_for`). It computes the metrics in SQL where cheap,
or loads the range pitches and reuses the existing pure transforms
(`_pa_count`, `k_pct`, `bb_pct`, a new `ip`/`barrel` helper). Reusing the
in-Python transforms on `range_pitches_for(...)` is preferred for
definition-consistency and testability (row counts are sub-second per §3h perf
recon).

## Metric definitions (provisional, docstring'd, coach-confirmable)

- **Appearances** — distinct `game_id` in range.
- **IP** — `sum(outs_on_play) / 3`, formatted baseball-style: whole innings then
  `.1` / `.2` for the trailing 1 / 2 outs (e.g. 12.2 = 12⅔). Helper
  `format_ip(outs)`.
- **K%** — `k_pct` = strikeouts ÷ batters faced (`_pa_count`). Displayed `"24.1%"`.
- **Walk%** — `bb_pct` = walks ÷ batters faced. Displayed `"7.5%"`.
- **Barrel%** — balls-in-play (`pitch_call == "InPlay"`) with `exit_speed >= 95`,
  ÷ balls-in-play. **This uses the coaches' simplified "95+ mph exit velocity"
  definition and intentionally DROPS the LineDrive/FlyBall qualifier** that the
  PDF report's `barrel_pct` keeps. The two Barrel% figures therefore differ by
  design; flagged for the coach. New helper `barrel_pct_ev(df)` so the report's
  `barrel_pct` is untouched.

Empty-range / no-data → each tile shows `"—"`.

## Components / interfaces

- `P.range_summary(pitcher_id, start, end) -> {appearances, ip, k_pct, bb_pct, barrel_pct}`
  (all display strings).
- `P.format_ip(outs: int) -> str`.
- `P.barrel_pct_ev(df) -> tuple[float, int]`.
- `layout.sidebar(pitcher_id, start=None, end=None)` — five `_tile`s in the grid
  (grid can go to 2 columns × 3 rows, or a 5-tile flow; keep the existing tile
  styling).

## Testing

`test_pitching.py`: unit-test `format_ip` (0→0.0, 1→0.1, 3→1.0, 8→2.2),
`barrel_pct_ev` (95 counts, <95 excluded, LD/FB-agnostic), and `range_summary`
shape + date-bounding (fewer apps for a narrower range) against the live
warehouse. `test_pitching_dash.py`: sidebar renders five tiles with the new
labels.

## Out of scope

Hitting/catching sidebars (this is the pitching dashboard only). Aligning the
report Barrel% to this simplified def (left as a separate coach decision).
