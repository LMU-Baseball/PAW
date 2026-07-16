# Pitcher Postgame One-Pager — Design

**Date:** 2026-07-16
**Branch:** `feat/pitcher-postgame-report`
**Status:** Approved (design), pending spec review → implementation plan
**Revert point for the current report:** git tag `report-detailed-v1` (commit 0693403)

## Goal

Replace the current detailed multi-section pitcher report with a **single-page
report that matches the layout the coaches already use and like** (last year's
Google-Drive PDF; sample: "Laine, Avery (RHP)", 1/13/2026 Intrasquad). The PAW
generates it natively from the AWS Trackman warehouse — no scraping of the old
PDFs, no dependency on last year's pipeline or Google Drive.

Secondary goal: make it **fast** (~3s build, instant when cached) by rendering
the plots with matplotlib instead of Plotly+kaleido.

## Approach (decided)

- **Build native**, not scrape. One source of truth (warehouse), works for every
  game past and future, full control of branding/speed.
- **Replace** the current report. The `Download Report` button produces the new
  one-pager. The old detailed report is retired but preserved at tag
  `report-detailed-v1` (see revert command in that tag / MEMORY.md).
- **Build now, refine metric definitions later.** Ship the full layout with every
  metric we can compute plus documented best-guess definitions for the
  LMU-specific ones; correct definitions and goal benchmarks once coaches confirm.
- **matplotlib** for the report's static plots (in-process, fast, precise);
  Plotly stays for the interactive Dash dashboards.

## Layout (single US-Letter page)

Mirrors the sample top to bottom:

1. **Header band (crimson):**
   - Left: LMU wordmark (`lmu.png`).
   - Center: `Last, First (RHP/LHP)`; below it `M/D/YYYY | vs OPP | GameType`.
   - Right of center: horizontal stat line — `BF (R/L)`, `OUTS`, `H`, `R`, `BB`,
     `SO`, `PITCHES`.
   - Far right: **lion logo**, recolored white on transparent for the crimson band.
2. **Row 1 (two tables side by side):**
   - **Process Metrics** — columns: Metric | Value | Goal | vRHH | vLHH.
     Rows: Strike%, FPS%, E&A%, Pre2K%, 2K Kill%.
   - **Outcome Metrics** — same columns. Rows: K%, BB%, Barrel%.
   - Value cells show `pct% (count)`. Conditional highlight: green when Value
     beats Goal (direction per metric — higher is better for Strike%/FPS%/E&A%/
     Pre2K%/2K Kill%/K%; lower is better for BB%/Barrel%).
3. **Row 2 (two tables side by side):**
   - **Pitch Usage** — Pitch Type | Strike% | Usage | 2K Usage | vRHH | vLHH.
     One row per pitch type (by usage desc).
   - **Movement Summary** — Pitch | Velocity | Vert Break | Horiz Break | Spread.
     Velocity shows `avg (max)`; Vert/Horiz Break show `avg (vRHH/vLHH)`; Spread
     is a single value. One row per pitch type.
4. **Row 3 (three plots):**
   - **vRHH Zone** — strike-zone scatter of pitches thrown to RHH; 3×3 zone grid +
     home-plate outline; dots colored by pitch type.
   - **Movement Map** — Horizontal Break (x) vs Induced Vertical Break (y); points
     colored by pitch type with a 1-σ confidence ellipse per type.
   - **vLHH Zone** — same as vRHH Zone but pitches to LHH.

## Metric definitions

**Directly computable (unambiguous), from `fact_tm_game_pitch`:**
- Header stat line: BF = max(`batters_faced`); R/L split via `batter_side`;
  OUTS = sum(`outs_on_play`); H = count(`play_result` in Single/Double/Triple/
  HomeRun); R = sum(`runs_scored`); BB = count(`korbb`=Walk); SO =
  count(`korbb`=Strikeout); PITCHES = row count.
- **Strike%** = strikes / pitches (strikes = existing `_STRIKE_CALLS` set).
- **FPS%** = first-pitch strikes / PAs (`pitch_of_pa`==1 and strike).
- **K%** = strikeouts / BF; **BB%** = walks / BF.
- **Pitch Usage**: Usage% = pitches of type / total; Strike% per type; 2K Usage% =
  share of a type's pitches thrown in 2-strike counts (`strikes`==2); vRHH/vLHH =
  usage split by `batter_side`.
- **Movement Summary**: Velocity avg/max = `rel_speed`; Vert Break = `induced_vert_break`;
  Horiz Break = `horz_break`; vRHH/vLHH = split by `batter_side`.
- vRHH/vLHH columns everywhere = the same metric restricted to `batter_side`.

**Best-guess v1 definitions (ASSUMPTIONS — flagged in code, confirm with coaches):**
- **E&A% (Early & Ahead)** = % of PAs where the pitcher reached an ahead count
  (strikes − balls ≥ 1) within the first two pitches of the PA.
- **Pre2K%** = strike% on pitches thrown in counts with fewer than 2 strikes
  (strikes in <2-strike counts / pitches in <2-strike counts).
- **2K Kill%** = strikeouts / PAs that reached a 2-strike count.
- **Barrel%** = barreled batted balls / batted balls, where "barrel" ≈
  `exit_speed` ≥ 95 mph AND `tagged_hit_type` in {LineDrive, FlyBall} (the
  warehouse has no plain launch-angle column — only approach/release angles — so
  hit type stands in for launch angle until confirmed).
- **Spread** (per pitch type) = std dev of total break magnitude
  `sqrt(induced_vert_break² + horz_break²)`, in inches (a movement-consistency
  measure).

Each assumption is isolated in one function with a docstring stating it's a v1
guess, so a coach-confirmed formula is a one-place change.

**Goal benchmarks:** an editable config (Python dict, `app/data/report_goals.py`
or similar) seeded from the sample's visible numbers — Strike% 55, FPS% 65,
E&A% 70, Pre2K% 48, 2K Kill% 55, K% 27, BB% 6, Barrel% 7 — with a comment that
these are placeholders to confirm. Missing goal → blank Goal cell, no highlight.

## Rendering engine

- **Tables:** HTML/CSS in a new Jinja template `pitcher_onepager.html`, styled to
  match the sample (crimson section headers, teal accents, value chips, green
  conditional highlight). New/updated `report.css` tuned to fit one Letter page
  with the existing print CSS approach. Teko fonts + logos inlined as data URIs
  (reuse `_inline_fonts` / `_data_uri`).
- **Plots (matplotlib):** a new module `app/reports/plots.py` with three builders
  returning PNG bytes / data URIs: `zone_chart(df_side)`, `movement_map(df)`.
  Rendered in-process (Agg backend), embedded as `data:image/png;base64`. No
  kaleido, no headless browser for charts.
- **PDF:** reuse `app/reports/pdf.py` `html_to_pdf` (Playwright, ~1.5s).
- **Caching:** reuse the existing on-disk cache (`build_pitcher_postgame`,
  `instance/report_cache`, versioned by `report_data_version`). Unchanged.
- Expected build ~3s (matplotlib <1s + Playwright ~1.5s + DB ~1s); instant cached.

## Assets / branding

- Header uses `lmu.png` (existing) + the new **lion** logo. The supplied lion is
  crimson on white; produce a **white-on-transparent** PNG for the crimson band
  (recolor + alpha). Save to `app/static/reports/lion-white.png` (source kept as
  `lion.png`).
- Crimson `#9A0021`, Teko display font (already inlined for PDFs via data URIs).

## What changes / file structure

- Add: `app/reports/plots.py` (matplotlib plot builders), `app/reports/templates/
  pitcher_onepager.html`, goals config module, `app/static/reports/lion*.png`.
- Add/extend transforms in `app/data/pitching.py`: header stat line, E&A%, Pre2K%,
  2K Kill%, Barrel%, per-type usage incl. 2K usage, movement summary w/ spread,
  all with vRHH/vLHH splits. (These are new; existing transforms/Plotly builders
  stay in place — still tagged for revert — but are no longer used by the report.)
- Modify: `app/reports/pitcher_postgame.py` `_build_html` to assemble the new
  template + matplotlib charts. Route, caching, and download delivery unchanged.
- Update `app/reports/static/report.css` for the one-page layout.

Dependency: add **matplotlib** to `requirements.txt`.

## Non-goals (v1)

- Not scraping/importing last year's PDFs.
- Not building the interactive dashboard version of this report.
- Not finalizing the LMU-specific metric formulas or goal numbers (best-guess now,
  coach-confirmed later).
- Not player-scoping the picker (separate deferred item).
- Dropdown open-direction (left native).

## Verification

- Full suite green; new unit tests for each new transform (counts/percentages on
  the fixture game 166 / pitcher 1, plus empty-input safety) and for the goals
  config + conditional-highlight logic. matplotlib builders return non-empty PNG
  bytes. Cache/route tests unchanged and still pass.
- Live: `python run.py` → download a report; confirm it is one page, matches the
  sample layout, shows both logos, builds in ~3s, and is instant on re-download.
- Sanity-check computed values against the sample where the same game exists in
  the warehouse; document any metric whose definition still needs coach input.
