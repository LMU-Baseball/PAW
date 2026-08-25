# Expected Called Strikes, SLAA and SL+ — Design

**Date:** 2026-08-24
**Status:** approved by user, ready for implementation plan

---

## 1. Context

The catching coach asked for nine metrics. Six of them — glove speed, time to
stick, glove path, glove orientation/rotation/angle, move distance, and load
timing/magnitude — require markerless motion-capture data that **does not
exist anywhere in the database**. A search of all 37 tables for columns
matching glove / biomech / joint / pose / reception / stick / orientation
returned zero real hits (the only matches were the word "payload" in the
HitTrax staging tables). The 2026-08-12 catching plan reached the same
conclusion independently for catch-to-presentation timing.

Those six are **deferred entirely**. They are blocked on the vendor
partnership described in `docs/vendor-biometrics-integration.md`, whose own
guidance is not to design the schema from guesses — the unblocking artifact is
one sample export file, not more design work.

The remaining three asks — called-strike rate relative to expected, SLAA
(strikes looking above average), and SL+ — are fully buildable from data
already in `GAMES`, and are what this spec covers.

### Why this is an upgrade, not a reskin

The existing framing metric (`app/data/catching_caps.py:334`) is binary: a
pitch is a "Stolen Strike" (out-of-zone called strike) or a "Lost Strike"
(in-zone called ball), judged against a rectangular box. That credits stealing
a pitch two inches off the plate exactly as much as one six inches off, and
penalises a catcher for failing to get a pitch no receiver alive would get.
A per-pitch probability model removes both distortions.

## 2. Measured facts this design rests on

All verified against the live database on 2026-08-24:

| Fact | Value |
|---|---|
| `GAMES` rows | 104,764 |
| Taken pitches (`PitchCall IN ('StrikeCalled','BallCalled')`) | 56,915 |
| Taken pitches with both location columns populated | **56,537** |
| Global called-strike rate among those | **0.3246** |
| Rows with `CatcherId` | 101,885 (97.2%) |
| LMU (`LOY_LIO`) pitches / taken / distinct catchers | 41,007 / 22,577 / 24 |
| `PlateLocSide` spread (0.1%–99.9%) | −3.49 ft to +3.26 ft |
| `PlateLocHeight` spread (0.1%–99.9%) | −1.29 ft to +5.98 ft |

Cell occupancy at candidate bin widths, over a clipped window:

| Bin width | Populated cells | Median n/cell | Cells with n<10 |
|---|---|---|---|
| 0.10 ft (1.2 in) | 2,079 | 24 | 411 (20%) |
| **0.15 ft (1.8 in)** | **952** | **56** | **67 (7%)** |
| 0.20 ft (2.4 in) | 546 | 96 | 11 (2%) |

## 3. Decisions

| Question | Decision |
|---|---|
| Glove metrics | **Deferred entirely.** No data. Blocked on a vendor sample export. |
| Model training population | **All teams' taken pitches** (~56,537). SLAA means "above average", so the baseline must be a neutral league/umpire-average zone, not LMU's own catchers. Also far denser at the zone edge, where framing is actually decided. |
| Model conditioning | **Location only.** No batter-side split. |
| Bin width | **0.15 ft (1.8 in).** Best balance: 56 pitches per cell median, only 7% sparse cells, and still finer than a baseball's 2.9 in diameter so the zone edge stays resolvable. |
| Existing STRIKES / STRIKES LOST tiles | **Kept unchanged.** SLAA and SL+ are added alongside, so coaches can build trust in the new numbers before anything is retired. |
| SL+ convention | `100 × actual / expected`. 100 = average, higher is better — the OPS+/wRC+ convention coaches already read. |

### Accepted limitation: no batter-side split

Umpires genuinely call a different zone to left- and right-handed batters,
particularly on the outside edge. With location-only conditioning, a catcher
who worked a lefty-heavy stretch will have some of that umpire tendency
attributed to him as skill. This is accepted for v1 in exchange for denser
cells and a simpler model, and it largely washes out across a full season
where catchers on one team face a similar batter mix.

**Mitigation, and it is a requirement not a nicety:** the lookup must be keyed
by a **tuple** whose arity can grow, so adding a batter-side dimension later is
a change to how keys are built, not a restructuring of the module. Do not key
cells by a packed scalar or by two positional arguments that assume exactly
two dimensions.

## 4. Component 1 — `app/data/called_strike.py` (new, isolated)

Mirrors `app/data/xba.py`, which is an established, tested 2-D empirical
lookup with two-level empirical-Bayes shrinkage in this codebase. Follow its
structure, naming, and caching conventions.

**Population.** All taken pitches, all teams, with both `PlateLocSide` and
`PlateLocHeight` populated. Deliberately NOT filtered to LMU.

**Lookup.** Cells keyed by `(side_bin, height_bin)`, each holding the smoothed
empirical `P(called strike)`.

**Modeling window and clipping — the critical detail.** Coordinates are
clipped into a window of `side ∈ [−2.0, 2.0] ft`, `height ∈ [0.0, 5.0] ft`
BEFORE binning.

This differs deliberately from `xba.py`, and copying `xba.py` here would be a
bug. `xba.py` falls back to the **global rate** for out-of-range inputs. If
that were done here, a pitch 3 ft outside — which no umpire has ever called a
strike — would be assigned the global 32.46% probability, handing catchers
large amounts of free expected strikes on balls in the dirt and systematically
deflating SLAA for good receivers. Clipping instead maps such pitches to the
edge bins, whose empirical rate is near zero, which is correct.

**Smoothing.** Two-level empirical-Bayes shrinkage, as in `xba.py`:
cell → height-band marginal → global called-strike rate, with the marginal
itself smoothed first so a sparse one-sided band cannot anchor a cell at
exactly 0 or 1. This matters more here than for xBA: the zone edge is both
where framing is decided and where cells are thinnest, so an unsmoothed 1-for-1
cell reading as a literal 100% would corrupt precisely the pitches the metric
exists to measure.

**Amendment 2026-08-25 (fix round):** the height-band-marginal anchor
described above shipped in Task 1 and was then replaced by a fix round after
calibration testing showed it over-predicted total called strikes by +2.15%
(a height band spans the full side window, so it isn't actually "local" and
drags well-sampled off-plate cells toward the band average). The shipped
smoothing instead anchors each cell to a pooled rate over its 8 grid-adjacent
neighbours, itself smoothed toward the global rate. Calibration bias with the
shipped anchor is +0.17%. See `app/data/called_strike.py`'s module docstring
("Smoothing (two-level empirical-Bayes, LOCAL anchor -- fix round 1)") for
the full mechanism and the measured numbers.

**Entry points.**

- `p_called_strike(side, height, *, lookup=None) -> float`
- `expected_called_strikes(df, *, lookup=None) -> pd.Series`

Both accept a `lookup=` override so tests can inject a synthetic lookup rather
than hitting the live database or the process cache — the same affordance
`xba.py` provides. Real callers omit it.

**Caching.** Process-level cache with the precalc data-version gate, following
`xba.py` and `app/data/cache.py`.

## 5. Component 2 — metrics in `app/data/catching_caps.py`

Reuse the existing scoping helpers (`range_pitches_for`, `game_pitches_season`)
so catcher selection and date ranges work unchanged.

- **Expected called strikes** = Σ `p_called_strike` over that catcher's taken
  pitches.
- **SLAA** = actual called strikes − expected. Units are strikes. 0 is average;
  +12 means twelve strikes gained beyond what an average receiver gets on those
  same pitches.
- **SL+** = `100 × actual / expected`.

**Sample-size floor — required, set at 100 taken pitches.** SL+ is a ratio and
becomes meaningless on a small denominator. Below **100** taken pitches in the
selected scope, display `—` rather than a number, and surface the taken-pitch
count alongside the metric so a coach can judge its weight. A catcher with 30
taken pitches reading "SL+ 148" is worse than showing nothing, because it will
be believed.

100 is chosen against the measured distribution: LMU has 22,577 taken pitches
across 24 catchers, so the regular starters clear it comfortably within a
handful of games while bullpen-catcher and one-game cameo lines — which is
exactly the noise this floor exists to suppress — do not. SLAA itself is a
difference, not a ratio, so it degrades gracefully and is shown at any n.

## 6. Component 3 — UI

- **Two new sidebar tiles, SLAA and SL+**, alongside the existing STRIKES and
  STRIKES LOST, which are unchanged.
- **Location breakdown on the Framing tab:** a grid heat map of
  (actual − expected) called strikes by zone region. This is the half of the
  coach's request that makes SLAA actionable rather than merely a scoreboard —
  it shows *where* a catcher gains and loses strikes.

  **Display grid is deliberately coarser than the model grid.** The model bins
  at 0.15 ft for resolution; the heat map aggregates into a **5 × 5 grid over
  the nominal zone plus a one-cell shadow ring (7 × 7 total)**. Rendering 952
  model cells per catcher would be unreadable and mostly noise — a single
  catcher has nowhere near enough pitches to fill them. Each display cell shows
  (actual − expected) summed over the model cells inside it, so the totals
  reconcile exactly with the SLAA tile. Cells are diverging-coloured around
  zero (gained vs lost strikes) and must be readable in both light and dark
  themes.

  **Amendment 2026-08-25 (fix round):** "reconcile exactly with the SLAA
  tile" above described the original design, where the heat map read the
  same season-wide scope as the sidebar tile. What shipped instead
  reconciles exactly with a LOCAL `slaa_summary` computed on the same
  (filtered) `df` already feeding the grid, surfaced as the figure's own
  caption/subtitle — not necessarily the sidebar's season-wide number, since
  the heat map is scoped by the Framing tab's own filters (Game dropdown,
  Batter Hand, Pitcher Throws, etc.), which the sidebar tile is not. This
  keeps the chart honest about its own scope rather than implying agreement
  with a tile that may be scoped differently. See
  `app/dashboards/catching/charts.py`'s `slaa_location_figure` docstring for
  the full rationale.

## 7. Testing

`tests/test_called_strike.py`, mirroring `tests/test_xba.py`'s conventions:

- Shrinkage never yields a raw 0% or 100%, even for an n=1 cell.
- **A pitch far outside the window gets a near-zero probability, not the global
  rate** — the regression guard for the clipping decision in §4.
- Empty frames and rows with missing location do not raise.
- A synthetic catcher whose calls exactly match the model scores SLAA ≈ 0.
- SL+ returns the sentinel below the sample-size floor.

## 8. Out of scope

- All six glove/biomechanics metrics — no data; blocked on a vendor sample.
- Batter-side and count conditioning — deliberate v1 simplification (§3).
- Retiring the existing binary STRIKES / STRIKES LOST metrics.
- Umpire effects — `GAMES` has no umpire column, so this cannot be modelled.
