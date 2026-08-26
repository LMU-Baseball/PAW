# Post-SLAA Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five issues reported right after the called-strike/SLAA merge: Velo Board/Cauldron
stuck unable to show current-week data, an unverified coach-edit save path, two broken strike-zone
chart aspect ratios (plus one confirmed width unification), and missing precalc coverage for the
new SLAA and hitting KPI tiles.

**Architecture:** Six independent, narrowly-scoped tasks against existing modules — no new
subsystems. The season/date fix and the live save verification are ordered first since they are
time-sensitive (semester starts next week). No task touches `app/data/called_strike.py` or any
already-reviewed SLAA behavior beyond adding a precalc read path in front of it.

**Tech Stack:** Python 3.12, Flask + Dash, Plotly, pandas, SQLAlchemy (`app.db.query_df`),
pytest, Playwright (already installed, used previously for a live dashboard check).

**Spec:** `docs/superpowers/specs/2026-08-25-post-slaa-fixes-design.md`

## Global Constraints

- Do not modify `app/data/called_strike.py`, or any already-reviewed SLAA behavior beyond adding
  a precalc read path (`slaa_summary`'s math, `SL_PLUS_MIN_TAKEN`, and `framing_season_tiles`/
  STRIKES/STRIKES LOST/STEAL% are UNCHANGED).
- Do not touch `app/dashboards/velo_board/visual.py`, `app/dashboards/cauldron/visual.py`,
  `app/static/brand/CauldronScript.ttf`, `app/static/reports/top-gun-logo*.png` if encountered —
  separate in-progress header work, off-limits across prior sessions.
- Follow existing patterns in each touched module. TDD: write/adjust tests first. Run only the
  relevant test files per task; the full suite runs once, in Task 6.
- Use `python -m pytest`, not bare `pytest`. Windows; Git Bash available; set
  `PYTHONIOENCODING=utf-8` for any script printing non-ASCII output.
- Full suite must stay green throughout: `python -m pytest -q --ignore=tests/test_precalc.py`
  (932 passing before this work).
- The two DB-schema-adjacent operational steps (merging `feat/2026-08-23-db-audit-perf`, adding a
  `(CatcherId,Date)` composite index on live GAMES) are handled by the controller directly,
  outside this plan's tasks — see the spec §3. Do not attempt either inside a task.

---

### Task 1: Season/week availability fix

**Files:**
- Modify: `app/data/seasons.py`
- Modify: `app/dashboards/velo_board/layout.py:29`
- Modify: `app/dashboards/cauldron/layout.py:58`
- Test: `tests/test_season_week_sync.py` (append), or wherever `app/data/seasons.py` is currently
  tested (check first — grep the test suite for `available_seasons` / `current_season` to find
  the real file before assuming)

**Interfaces:**
- Consumes: nothing new.
- Produces: no new public interface — `available_seasons()`'s return value gains one more
  possible label (today's calendar season); `current_season()`'s signature/behavior for its
  data-driven default is UNCHANGED.

- [ ] **Step 1: Write the failing test**

Find the real test file for `app/data/seasons.py` first (`grep -rn "available_seasons\|current_season" tests/*.py` and read whichever file actually exercises `seasons.py` directly — do not assume `test_season_week_sync.py` is it without checking; that file may test `velo_board.default_week_for` instead). Add a test that monkeypatches `query_df` (or whatever seam the existing tests in that file already use to avoid a live DB call) to return zero GAMES rows for the current calendar year, and asserts `seasons.available_seasons()` still includes `seasons.season_label_for(date.today().isoformat())` in its result — i.e. the current academic year is ALWAYS present even with zero underlying data. Match the file's existing mocking convention exactly (read 2-3 existing tests in it first).

- [ ] **Step 2: Run test to verify it fails**

Run the test file you just edited. Expected: FAIL — the current calendar season is missing from `available_seasons()`'s result when the mocked GAMES query returns nothing for it.

- [ ] **Step 3: Fix `available_seasons()` in `app/data/seasons.py`**

Change lines 33-40 from:
```python
@cached
def available_seasons() -> list[str]:
    """Academic-year labels present in GAMES (LMU, numeric GameID), newest first."""
    df = query_df(
        f"SELECT DISTINCT Date FROM GAMES WHERE BatterTeam = :t AND {_NUMERIC_DATE}",
        {"t": LMU_BATTER_TEAM})
    labels = {season_label_for(d) for d in df["Date"]} if not df.empty else set()
    return sorted(labels, reverse=True)
```
to:
```python
@cached
def available_seasons() -> list[str]:
    """Academic-year labels present in GAMES (LMU, numeric GameID), newest first, ALWAYS
    including today's actual calendar academic-year label even if GAMES has zero rows for
    it yet.

    Without this, a Season dropdown built from this list has a hard ceiling: once the last
    labeled season ends, no later season is ever selectable until a GAMES row for it exists
    -- which for Velo Board/Cauldron (backed by BULLPEN, not GAMES) can be months after the
    data a coach actually needs is already flowing. Purely additive: this can only ADD the
    current label to what GAMES-derived data already reports, never remove or reorder an
    existing entry."""
    df = query_df(
        f"SELECT DISTINCT Date FROM GAMES WHERE BatterTeam = :t AND {_NUMERIC_DATE}",
        {"t": LMU_BATTER_TEAM})
    labels = {season_label_for(d) for d in df["Date"]} if not df.empty else set()
    labels.add(season_label_for(date.today().isoformat()))
    return sorted(labels, reverse=True)
```

Do NOT change `current_season()` (lines 43-47) — its data-driven default ("latest season WITH
real GAMES data, else today's calendar season if GAMES is entirely empty") stays exactly as-is.
This is a deliberate scope boundary: changing it would make catching/hitting/pitching dashboards
default to an empty view every day until real Fall-2026 GAMES rows exist, which is a regression
those three dashboards don't need and didn't ask for. See spec §4 for the full reasoning if this
seems inconsistent — it isn't; only the *options list*, not the *global default*, changes here.

- [ ] **Step 4: Run test to verify it passes**

Run the same test file. Expected: PASS.

- [ ] **Step 5: Point Velo Board and Cauldron's own default at today's real calendar season**

In `app/dashboards/velo_board/layout.py`, find line 29 (`season = seasons.current_season()`
inside `serve_layout()`) and change it to:
```python
    season = seasons.season_label_for(date.today().isoformat())
```
Add `from datetime import date` to the file's imports if not already present (check the top of
the file first — it may already import `date` for other purposes).

Do the identical change in `app/dashboards/cauldron/layout.py` at line 58.

**Before making this change, grep both files for every other call to `seasons.current_season()`**
(`grep -n "current_season" app/dashboards/velo_board/layout.py app/dashboards/cauldron/layout.py`)
— there may be more than one call site (e.g. inside a layer-2 `parallel.prefetch` block, similar
to the pattern in `app/dashboards/catching/layout.py`). Change EVERY default-season resolution
call site in both files, not just the first one found, so the season used to build the initial
dropdown value, the initial week bounds, and any prefetch keys all agree — a mismatch here would
reintroduce a version of the exact bug this task fixes (one part of the page defaulting to one
season, another part to a different one). Do NOT change `season_bounds()` calls, `available_seasons()`
calls used to populate the dropdown's OPTIONS list, or anything inside `callbacks.py` — only the
DEFAULT VALUE resolution in `layout.py`.

- [ ] **Step 6: Run the neighbouring test suites**

Run: `python -m pytest tests/test_velo_board.py tests/test_velo_board_dash.py tests/test_cauldron.py tests/test_cauldron_dash.py tests/test_season_week_sync.py -q`
Expected: all pass. If any test hard-coded an assumption that the default season is
GAMES-data-driven (e.g. asserted a specific season label that only made sense under the old
behavior), update that test to reflect the new, deliberate default — but do not weaken a test
that is actually catching a real regression; if you're unsure whether a failing test reveals a
real problem or just a stale assumption, say so in your report rather than silently "fixing" it.

- [ ] **Step 7: Live sanity check against real data**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from app.data import seasons
from datetime import date
print('today:', date.today().isoformat())
print('available_seasons():', seasons.available_seasons())
print('current_season() [unchanged, GAMES-driven]:', seasons.current_season())
print('todays calendar season:', seasons.season_label_for(date.today().isoformat()))
from app.data.velo_board import default_week_for
print('default_week_for(todays season):', default_week_for(seasons.season_label_for(date.today().isoformat())))
"
```
Expected: `available_seasons()` includes today's calendar season label even though `current_season()`
still returns the old GAMES-backed one; `default_week_for` on today's calendar season returns
THIS week's Monday, not July 27. Paste the real output into your report. If `default_week_for`
still returns an old date, stop and investigate before proceeding — that would mean Step 5's
call-site change didn't actually take effect somewhere.

- [ ] **Step 8: Commit**

```bash
git add app/data/seasons.py app/dashboards/velo_board/layout.py app/dashboards/cauldron/layout.py tests/
git commit -m "fix(seasons): always offer the current calendar season, default velo/cauldron to it"
```

---

### Task 2: Live save-persistence verification for Velo Board and Cauldron (safety-critical)

**Files:**
- Create: `tests/test_velo_cauldron_save_live.py` (or find and extend an existing live/Playwright
  test file if this repo already has one for a different dashboard — check for a prior SLAA-heat-map
  live check pattern first, e.g. via `grep -rln "playwright" tests/` and `grep -rln "playwright"
  scripts/` — match whatever pattern already exists rather than inventing a new one)
- Fix (only if the live check finds a real defect): `app/dashboards/velo_board/callbacks.py`,
  `app/dashboards/cauldron/callbacks.py`, `app/dashboards/velo_board/grid.py`,
  `app/dashboards/cauldron/grid.py`

**Interfaces:**
- Consumes from Task 1: today's calendar season is now the default on both boards, so this task
  can exercise a real current week rather than needing to navigate to an old one first.
- Produces: no new interface — this task is verification, with a fix only if verification finds
  a real defect.

This task has NO pre-written test code in this plan, deliberately — you are writing a live
integration test, and the exact selectors/flow depend on the real rendered DOM, which must be
read from the live app rather than guessed. Do not skip straight to "should work" reasoning.

- [ ] **Step 1: Read the full save/edit code path for both boards before touching anything**

Read `app/dashboards/velo_board/callbacks.py` (`_on_edit`/`_on_save`), `app/dashboards/velo_board/grid.py`
(`save_board`), `app/data/velo_board.py` (`upsert_entries`/`set_override`), and the same trio for
`app/dashboards/cauldron/` (`callbacks.py`, `grid.py`, `app/data/cauldron.py`'s `upsert_daily`).
Confirm your understanding matches the spec §5 trace (real transactional writes, read paths not
cached, server-side coach re-check) — if anything in the live code differs from what the spec
describes, note the discrepancy in your report.

- [ ] **Step 2: Find (or start) a local dev server and coach login**

Check whether a dev server is already running (`Get-Process`/`ps` for a listener on the usual
port, or check recent background task state) before starting a new one. If none is running:
`PYTHONIOENCODING=utf-8 python run.py` in the background. Find a working coach login — check
`memory/MEMORY.md` for a documented demo coach account (search for "coach@" — there may be more
than one documented across different sessions; if unsure which is current, check `instance/`'s
local auth DB or `.env` for `PAW_SEED_COACH_EMAIL`/`PAW_SEED_COACH_PASSWORD`, or ask via
NEEDS_CONTEXT rather than guessing at credentials).

- [ ] **Step 3: Write and run a live Playwright test that proves (or disproves) the full round trip**

Using Playwright (already in `requirements.txt`), write a test/script that:
1. Logs in as the coach account.
2. Navigates to the Velo Board (`/dash/velo_board/`).
3. Reads the currently-rendered grid's values for one specific, identifiable row/column (note
   the exact player name or row identifier and column you're editing, and its value BEFORE your
   edit).
4. Clicks "Edit" (or whatever button unlocks the grid — read the real label from the rendered
   page, don't guess).
5. Edits ONE cell to a new, distinctive value (e.g. append a recognizable marker/timestamp if the
   field is free text, or pick a numeric value clearly different from what was there) through the
   ACTUAL DataTable UI (a real click + real keystrokes into the cell), not a JS-injected value —
   the whole point is to prove the value survives whatever the browser round-trips back to Dash.
6. Clicks "Save". Confirm the UI shows a save-confirmation state (e.g. "Saved.").
7. Closes the browser context ENTIRELY (not just navigates away) and opens a genuinely fresh
   Playwright browser context/page — simulating a different session, not a soft reload — logs in
   again (as the SAME coach, then separately if time permits as a DIFFERENT account e.g. the
   player demo login, to directly test the "no matter the account" requirement), navigates back
   to the same page, and confirms the edited cell shows your distinctive new value, not the old
   one.
8. Repeat steps 2-7 for the Cauldron (`/dash/cauldron/`), using its own edit/save button labels
   and grid.

Run this against the live dev server. **Report the exact outcome — do not round up to "probably
works."** If every step confirms the value persisted and reads back correctly across a genuinely
fresh session, that is your evidence. If it does NOT (wrong value, save silently no-ops, or the
edited row doesn't map to the right underlying id), that is a Critical finding — proceed to Step 4.

- [ ] **Step 4: If (and only if) Step 3 found a real defect, fix it**

Trace the specific failure to its root cause using the code read in Step 1 — do not patch a
symptom. Common failure shapes to consider if this happens: the hidden id column not surviving
because it's accidentally included in an `editable` column spec (letting a user's edit overwrite
it), a mismatch between the DataTable's `id` prop and what the callback's `State(...,"data")`
actually reads, or `save_board`/`upsert_entries` keying off the wrong column name after a
DataTable round-trip re-serializes the row dict. Write a regression test that fails against the
old code and passes against your fix, matching this repo's existing test conventions for these
modules (`tests/test_velo_board.py`, `tests/test_cauldron.py`).

- [ ] **Step 5: Save your test/script as a permanent regression artifact**

Whether or not Step 4 was needed, save the Playwright script from Step 3 as a real test file
(`tests/test_velo_cauldron_save_live.py` or similar) so this verification isn't a one-off — mark
it clearly if it requires a live server + DB (e.g. a `pytest.mark.skip` with a reason, or however
this repo already gates live-only tests — check `tests/test_hitting.py`'s convention, which the
called-strike/SLAA work referenced as "plain module that queries the live DB directly, no
`lookup=` mocking" — match that style) so it doesn't break CI (`tests/test_security.py` is the
only test CI runs today) but remains runnable on demand.

- [ ] **Step 6: Commit**

```bash
git add tests/test_velo_cauldron_save_live.py
# plus any fix files from Step 4, if a fix was needed
git commit -m "test(velo/cauldron): verify coach save persists across a fresh session"
```
(If Step 4 produced a real fix, use a SEPARATE commit for it with a message describing the actual
bug, e.g. `git commit -m "fix(velo_board): <the real root cause>"` — do not bundle an actual bug
fix into a "test:" commit message.)

---

### Task 3: Strike-zone rectangle fixes

**Files:**
- Modify: `app/dashboards/catching/charts.py` (`slaa_location_figure`, lines ~152-238)
- Modify: `app/dashboards/hitting/charts.py:76` (`_style_axes`)
- Modify: `app/data/practice.py:34-35` (`SZ_X0`/`SZ_X1`)
- Test: `tests/test_catching_dash.py` (adjust existing `slaa_location` tests if their assertions
  depend on index-space geometry), `tests/test_hitting_dash.py` or wherever `zone_scatter` is
  tested (check first), `tests/test_hitting_practice_dash.py` or wherever `practice.py`'s zone
  constants are tested

**Interfaces:**
- Consumes: nothing new.
- Produces: `slaa_location_figure`'s public signature is unchanged (`(df, *, lookup=None) ->
  go.Figure`); only its internal plotting coordinates change. Same for `zone_scatter`.

- [ ] **Step 1: Check the existing SLAA heat map tests for index-space assumptions**

Read `tests/test_catching_dash.py`'s `test_slaa_location_figure_totals_reconcile_with_slaa`,
`test_slaa_location_figure_on_empty_frame_does_not_raise`, and the two orientation regression
tests added during the called-strike/SLAA final review (search for `_display_cell` or
"orientation" in that file). None of these should break from a coordinate-system change alone —
they check totals/orientation, not raw pixel positions — but confirm this by reading them before
you touch `charts.py`, and note in your report if any assertion is actually coupled to the old
index-space geeometry (e.g. asserting `fig.data[0].z`'s shape without checking `fig.data[0].x`/`y`
— if a test starts relying on explicit `x`/`y` arrays existing, that's expected and fine).

- [ ] **Step 2: Write a new failing test for the real-feet zone bounds**

Append to `tests/test_catching_dash.py`:
```python
def test_slaa_location_figure_zone_outline_uses_real_feet_bounds():
    """The zone-outline shape must be drawn at the real strike-zone bounds
    (matching pitching.py's _SZ / bullpen's _ZONE: x0=-0.83,x1=0.83,
    y0=1.5,y1=3.5), not at arbitrary cell-index coordinates -- otherwise the
    box renders as a square regardless of the true (non-square) zone shape."""
    import pandas as pd
    from app.dashboards.catching import charts

    df = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    fig = charts.slaa_location_figure(df)
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == 1, "expected exactly one zone-outline rectangle"
    zone = rects[0]
    assert (zone.x0, zone.x1, zone.y0, zone.y1) == (-0.83, 0.83, 1.5, 3.5)


def test_slaa_location_figure_plots_on_real_feet_not_cell_indices():
    """The heatmap trace's x/y coordinates must be real feet (bin centers
    inside/around the +/-0.83 / 1.5-3.5 window), not the default 0..6 index
    positions Plotly would otherwise fall back to."""
    import pandas as pd
    from app.dashboards.catching import charts

    df = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    fig = charts.slaa_location_figure(df)
    xs = list(fig.data[0].x)
    ys = list(fig.data[0].y)
    assert max(xs) <= 1.3 and min(xs) >= -1.3, f"x coords look like indices, not feet: {xs}"
    assert max(ys) <= 4.0 and min(ys) >= 1.0, f"y coords look like indices, not feet: {ys}"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_catching_dash.py -k "real_feet or zone_outline" -q`
Expected: FAIL — the zone rect is currently at cell-index bounds `(0.5, 5.5, 0.5, 5.5)`, and
`fig.data[0].x`/`y` don't exist yet (Plotly defaults to implicit index positions when no `x`/`y`
is passed to `go.Heatmap`).

- [ ] **Step 4: Fix `slaa_location_figure` in `app/dashboards/catching/charts.py`**

Find the constants block above `_display_cell` (currently `ZONE_SIDE_HALF = 0.83`,
`ZONE_H_LO, ZONE_H_HI = 1.5, 3.5`, `_CELL_W`, `_CELL_H`, `_N = 7`) — these stay unchanged, they
already correctly describe the real geometry; only the PLOTTING needs to switch from implicit
index coordinates to these real values. Add bin-center coordinate arrays right after those
constants:
```python
# Real-feet bin centers for the 7 display columns/rows, so the heatmap plots
# in physical space instead of abstract cell indices -- this is what lets
# scaleanchor="x", scaleratio=1 below render the zone's TRUE (non-square)
# aspect ratio instead of an artificial square.
_COL_CENTERS_FT = [(-ZONE_SIDE_HALF - _CELL_W) + (c + 0.5) * _CELL_W for c in range(_N)]
_ROW_CENTERS_FT = [(ZONE_H_LO - _CELL_H) + (r + 0.5) * _CELL_H for r in range(_N)]
```
Then in `slaa_location_figure`, change the `go.Heatmap(...)` call (currently `z=z, zmid=0,
zmin=-lim, zmax=lim, colorscale=...`) to pass explicit `x=` and `y=`:
```python
    fig = go.Figure(go.Heatmap(
        x=_COL_CENTERS_FT, y=_ROW_CENTERS_FT,
        z=z, zmid=0, zmin=-lim, zmax=lim,
        colorscale="RdBu", reversescale=True,
        hovertemplate="strikes gained: %{z:.1f}<extra></extra>",
        colorbar=dict(title="+/- strikes"),
    ))
```
And change the zone-outline `add_shape` from the current cell-index bounds to real feet, matching
`pitching.py`'s `_SZ` / `bullpen/charts.py`'s `_ZONE` convention exactly:
```python
    # Outline the nominal strike zone at its real bounds (matches pitching.py's
    # _SZ / bullpen/charts.py's _ZONE) -- now that the heatmap plots in real
    # feet, this box's aspect ratio is finally the TRUE, non-square shape.
    fig.add_shape(type="rect", x0=-ZONE_SIDE_HALF, x1=ZONE_SIDE_HALF,
                  y0=ZONE_H_LO, y1=ZONE_H_HI, line=dict(color="#1a1a1a", width=2))
```
`scaleanchor="x", scaleratio=1` on the yaxis (already present) stays unchanged — it now correctly
locks against real feet instead of cell indices, so the true rectangle renders.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching_dash.py -q`
Expected: all pass, including the two new tests and the pre-existing reconciliation/orientation/
empty-frame tests from the called-strike/SLAA work (their assertions are about totals and
column/row ordering, not the coordinate system, so they should be unaffected — but this run is
what proves that, not an assumption).

- [ ] **Step 6: Fix `app/dashboards/hitting/charts.py`'s missing aspect lock**

First, find how `zone_scatter` is currently tested (`grep -rn "zone_scatter" tests/`) and read one
existing test to understand the fixture/assertion style. Add a test asserting the yaxis has an
aspect lock, e.g.:
```python
def test_zone_scatter_locks_aspect_ratio():
    """Without an aspect lock, Plotly can stretch/squish the already-correct
    20x26-inch zone box to fit whatever container size it's given."""
    import pandas as pd
    from app.dashboards.hitting import charts

    df = pd.DataFrame(columns=["PlateLocSide", "PlateLocHeight", "PitchCall",
                                "TaggedPitchType", "PlayResult", "TaggedHitType"])
    fig = charts.zone_scatter(df)
    assert fig.layout.yaxis.scaleanchor == "x"
```
(Match the real column set `zone_scatter` actually expects — read its full signature/body first;
this is illustrative, not necessarily complete — adjust to whatever an empty/minimal valid input
looks like for this function.)

Run it, confirm it fails (`scaleanchor` is currently `None`), then change line 76 in
`app/dashboards/hitting/charts.py`'s `_style_axes` from:
```python
    fig.update_yaxes(range=list(_YRANGE), showgrid=False, zeroline=False,
                     visible=False, scaleanchor=None, **kw)
```
to:
```python
    fig.update_yaxes(range=list(_YRANGE), showgrid=False, zeroline=False,
                     visible=False, scaleanchor="x", scaleratio=1, **kw)
```
Run the test again to confirm it passes, then run the full hitting-dashboard test file to confirm
nothing else broke (a newly-locked aspect ratio could in principle affect a snapshot-style test if
one exists — check for it).

- [ ] **Step 7: Unify the HitTrax practice zone width — with the statistical caveat documented**

**Read this before editing:** `app/data/practice.py:34-35`'s `SZ_X0, SZ_X1 = -0.708, 0.708` is
used in TWO places — the practice zone chart (cosmetic) AND `practice.py:368`'s `in_zone`
classification for swing-decision statistics (NOT cosmetic — this changes what counts as an
"in-zone" pitch for every practice report reading that classification). The user confirmed
unifying to the standard width; proceed, but the commit message and PR-facing report must state
this plainly, not bury it as a drive-by chart tweak.

Check whether `tests/test_hitting_practice.py` or similar asserts anything about `SZ_X0`/`SZ_X1`'s
specific value or about `in_zone` classification results near the old boundary (a pitch at
`px=0.75` was previously "out of zone" under the old ±0.708 width and will become "in zone" under
the new ±0.83 width) — if such a test exists, update its expected values with a comment explaining
the width change, don't just make it pass by weakening the assertion.

Change lines 34-35 from:
```python
# College strike zone (feet) — catcher's view
SZ_X0, SZ_X1 = -0.708, 0.708
SZ_Y0, SZ_Y1 = 1.5, 3.5
```
to:
```python
# Strike zone (feet) — catcher's view. Unified 2026-08-25 to the same 0.83 ft
# half-width every other zone chart in the app uses (pitching.py's _SZ,
# bullpen/charts.py's _ZONE, catching/charts.py's slaa_location_figure) --
# previously 0.708 ft here only, a pre-existing inconsistency. NOTE: this
# constant is not purely cosmetic -- practice.py's in_zone classification
# (used for swing-decision statistics, not just this chart) uses it too, so
# this change also widens what counts as "in zone" for practice reports.
SZ_X0, SZ_X1 = -0.83, 0.83
SZ_Y0, SZ_Y1 = 1.5, 3.5
```

- [ ] **Step 8: Run the neighbouring test suites**

Run: `python -m pytest tests/test_catching_dash.py tests/test_hitting_dash.py tests/test_hitting_practice_dash.py tests/test_hitting_practice.py -q`
Expected: all pass (after any deliberate, documented expected-value updates from Step 7).

- [ ] **Step 9: Commit**

```bash
git add app/dashboards/catching/charts.py app/dashboards/hitting/charts.py app/data/practice.py tests/
git commit -m "fix(charts): render strike-zone visuals as true rectangles, not squares"
```

---

### Task 4: Precalc the hitting KPIs (Hard-Hit% / Pop-Up% / xBA)

**Files:**
- Modify: `app/data/precalc.py`
- Modify: `app/data/hitting_caps.py` (`_compute_season_rollup`, `sidebar_stats`)
- Test: `tests/test_precalc.py` (or wherever `precalc.py` is tested), `tests/test_hitting_caps.py`

**Interfaces:**
- Consumes: `hitting_caps._live_batted_ball_kpis(batter_id, start, end, ab) -> dict` (existing,
  unchanged) for the compute fallback path.
- Produces: `HITTING_SEASON_TABLE` gains 3 columns (`hard_hit_pct`, `popup_pct`, `xba`);
  `_compute_season_rollup(batter_id, season=None) -> dict` return dict gains those 3 keys.

- [ ] **Step 1: Write the failing test**

Read `tests/test_hitting_caps.py`'s existing tests for `_compute_season_rollup` and `sidebar_stats`
first to match their mocking convention exactly (they likely monkeypatch `range_pitches`/
`bip_points`/the DB query seam — use the same pattern). Add:
```python
def test_compute_season_rollup_includes_batted_ball_kpis(monkeypatch):
    """The precalc rollup dict must carry hard_hit_pct/popup_pct/xba so
    rebuild_hitting can persist them -- previously these were always
    recomputed live even on the season-default path."""
    # (fill in with this file's existing fixture/monkeypatch pattern for
    # _rollup_over's dependencies, then assert the three new keys are present
    # in _compute_season_rollup(...)'s return dict with plausible values)
    ...
```
(This step's exact fixture code depends on reading the real file first — the plan cannot specify
it blind without risking a mismatch with the file's actual mocking seams; read `tests/
test_hitting_caps.py` completely before writing this test, then write real, complete assertions,
not a placeholder — the `...` above is instructive only and must not survive into the actual
test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_caps.py -k batted_ball_kpis -q`
Expected: FAIL — `KeyError: 'hard_hit_pct'` (or similar) since `_compute_season_rollup` doesn't
return those keys yet.

- [ ] **Step 3: Extend `_compute_season_rollup` in `app/data/hitting_caps.py`**

Change (around line 186-201) from:
```python
def _compute_season_rollup(batter_id, season=None) -> dict:
    ...
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    return {**_rollup_over(batter_id, s, e), "season_label": season}
```
to:
```python
def _compute_season_rollup(batter_id, season=None) -> dict:
    """The hitting season rollup for one batter, computed from raw CAPS --
    now including HARD-HIT%/POP-UP%/xBA so `rebuild_hitting` can persist
    them to precalc. Thin wrapper over `_rollup_over` (slash/QAB) plus
    `_live_batted_ball_kpis` (the three batted-ball KPIs) with the season's
    date bounds -- the single source of truth for each stays where it
    already was; this function only combines them for storage.

    `precalc.rebuild_hitting` writes this dict to
    `precalc_hitting_player_season`; `sidebar_stats` reads it back (with
    this function as the compute fallback). No metric is redefined here.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    rollup = _rollup_over(batter_id, s, e)
    kpis = _live_batted_ball_kpis(batter_id, s, e, rollup["ab"])
    return {**rollup, **kpis, "season_label": season}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hitting_caps.py -k batted_ball_kpis -q`
Expected: PASS.

- [ ] **Step 5: Extend the precalc table schema in `app/data/precalc.py`**

Change `HITTING_SEASON_TABLE`'s `_DDL` entry (lines 44-54) from:
```python
    HITTING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {HITTING_SEASON_TABLE} (
            batter_id    BIGINT NOT NULL,
            batter_name  VARCHAR(128),
            qab_pct      DECIMAL(4,3) NULL,
            ba VARCHAR(8), obp VARCHAR(8), slg VARCHAR(8),
            pa INT, ab INT, h INT, doubles INT, triples INT, hr INT, bb INT, so INT,
            season_label VARCHAR(32) NOT NULL,
            built_at     DATETIME,
            PRIMARY KEY (batter_id, season_label)
        )""",
```
to:
```python
    HITTING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {HITTING_SEASON_TABLE} (
            batter_id    BIGINT NOT NULL,
            batter_name  VARCHAR(128),
            qab_pct      DECIMAL(4,3) NULL,
            ba VARCHAR(8), obp VARCHAR(8), slg VARCHAR(8),
            pa INT, ab INT, h INT, doubles INT, triples INT, hr INT, bb INT, so INT,
            hard_hit_pct VARCHAR(8), popup_pct VARCHAR(8), xba VARCHAR(8),
            season_label VARCHAR(32) NOT NULL,
            built_at     DATETIME,
            PRIMARY KEY (batter_id, season_label)
        )""",
```
`hard_hit_pct`/`popup_pct` are already display-formatted strings (`_fmt_pct`, e.g. `"45.2%"` or
`"—"`) and `xba` is already `_fmt_avg`-formatted (matches the `ba` column's own format), so
`VARCHAR(8)` matches the existing `ba`/`obp`/`slg` columns' type exactly — no new formatting
layer needed.

Since this ADDS columns to an existing table (not a fresh CREATE), `ensure_tables`'s existing
migration logic (drop-and-recreate on PK mismatch, lines 113-126) will NOT pick up a plain
column addition — it only triggers on primary-key drift. Read `ensure_tables` and `_pk_columns`
carefully: if the table already exists in a target DB with the OLD column set, `CREATE TABLE IF
NOT EXISTS` is a no-op and the new columns will silently NOT be added. Add an `ALTER TABLE ...
ADD COLUMN IF NOT EXISTS` (or the MySQL-safe equivalent — MySQL <8.0.29 doesn't support `ADD
COLUMN IF NOT EXISTS`; check what MySQL version this repo's `INFORMATION_SCHEMA` checks assume
elsewhere, e.g. `_pk_columns`'s use of `INFORMATION_SCHEMA.KEY_COLUMN_USAGE`, and use a
column-existence check via `INFORMATION_SCHEMA.COLUMNS` guarding a plain `ALTER TABLE ... ADD
COLUMN` instead if `IF NOT EXISTS` isn't safely available) inside `ensure_tables` for the three
new columns, so a live table that predates this change gets migrated forward safely and
idempotently, matching this function's existing "safe, re-runnable" contract.

- [ ] **Step 6: Wire `read_hitting_season` and `sidebar_stats` to use the precalc columns**

`read_hitting_season` (lines 208-214) already does `SELECT *` and returns the full row dict, so
it will automatically include the 3 new columns once they exist — no change needed there beyond
what Step 5 already did, but verify this by reading the function once more.

In `app/data/hitting_caps.py`'s `sidebar_stats` (lines 274-299), change BOTH return points that
currently call `_live_batted_ball_kpis` unconditionally. The season-default path (currently):
```python
    r = _season_rollup(batter_id, season)
    s_b, e_b = seasons.season_bounds(season or seasons.current_season())
    live = _live_batted_ball_kpis(batter_id, s_b, e_b, r["ab"])
    return {"qab": r["qab_pct"], "BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"], **live}
```
becomes:
```python
    r = _season_rollup(batter_id, season)
    return {"qab": r["qab_pct"], "BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"],
            "hard_hit_pct": r["hard_hit_pct"], "popup_pct": r["popup_pct"], "xba": r["xba"]}
```
`_season_rollup`'s compute fallback (line 145, `_compute_season_rollup(batter_id, season)`) now
already returns these 3 keys per Step 3, so this works whether `r` came from the precalc table or
the live fallback — the only thing removed is the now-redundant SECOND live pull that used to run
even when the season rollup already had the answer.

**Leave the sub-range branch (the `if start and end:` block earlier in the function) UNCHANGED —
it must keep calling `_live_batted_ball_kpis` live**, since a genuine sub-range selection should
never read season-wide precalc numbers for these fields. Update the function's docstring to
reflect that only the sub-range path still does a live batted-ball pull now.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_caps.py tests/test_hitting_dash.py -q`
Expected: all pass.

- [ ] **Step 8: Live sanity check**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from app.data import precalc, hitting_caps as H
n = precalc.rebuild_hitting()
print('rebuilt', n, 'rows')
top = H.lmu_hitters()
bid = int(top.iloc[0]['BatterId'])
print(H.sidebar_stats(bid))
print(precalc.read_hitting_season(bid))
"
```
Expected: `sidebar_stats` returns `hard_hit_pct`/`popup_pct`/`xba` with plausible values matching
what `precalc.read_hitting_season` now stores for the same batter. Paste the real output into
your report.

- [ ] **Step 9: Commit**

```bash
git add app/data/precalc.py app/data/hitting_caps.py tests/
git commit -m "perf(hitting): precalculate Hard-Hit%/Pop-Up%/xBA instead of always computing live"
```

---

### Task 5: Precalc catching SLAA / SL+

**Files:**
- Modify: `app/data/precalc.py`
- Modify: `app/data/catching_caps.py` (`slaa_season_tiles`, plus a new `_compute_slaa_season_rollup`)
- Test: `tests/test_precalc.py`, `tests/test_called_strike_metrics.py`

**Interfaces:**
- Consumes from Task 1's earlier plan (already merged): `slaa_summary(df, *, lookup=None) -> dict`,
  `_resolve_season_window(season, start, end) -> tuple[str, str]`, `range_pitches_for(catcher_id,
  start, end) -> pd.DataFrame`.
- Produces: `CATCHING_SEASON_TABLE = "precalc_catching_player_season"`,
  `rebuild_catching(engine=None) -> int`, `read_catching_season(catcher_id, season=None) -> dict |
  None`, `_compute_slaa_season_rollup(catcher_id, season=None) -> dict`.

- [ ] **Step 1: Write the failing test for the new compute function**

Read `tests/test_called_strike_metrics.py`'s existing DB-free convention (every test injects a
`lookup=`) before writing this — the new function needs a DB-free seam too. Add:
```python
def test_compute_slaa_season_rollup_shape(monkeypatch):
    """The precalc-bound rollup dict must carry catcher_id, catcher_name,
    slaa, sl_plus, taken, and season_label -- everything
    slaa_season_tiles needs to read back without a live compute."""
    import pandas as pd
    from app.data import catching_caps

    def fake_range_pitches_for(cid, start, end):
        return pd.DataFrame(
            [(0.0, 2.5, "StrikeCalled")] * 100,
            columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    monkeypatch.setattr(catching_caps, "range_pitches_for", fake_range_pitches_for)
    monkeypatch.setattr(catching_caps, "catcher_name", lambda cid: "Test Catcher")

    out = catching_caps._compute_slaa_season_rollup(1, season="2025/2026")
    assert out["catcher_id"] == 1
    assert out["catcher_name"] == "Test Catcher"
    assert out["season_label"] == "2025/2026"
    assert out["taken"] == 100
    assert "slaa" in out and "sl_plus" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_called_strike_metrics.py -k compute_slaa_season_rollup -q`
Expected: FAIL — `AttributeError: module 'app.data.catching_caps' has no attribute
'_compute_slaa_season_rollup'`.

- [ ] **Step 3: Implement `_compute_slaa_season_rollup` in `app/data/catching_caps.py`**

Add near `slaa_season_tiles` (after it, or right before — match the file's existing ordering
convention of "summary function, then tiles function"):
```python
def _compute_slaa_season_rollup(catcher_id, season=None, *, lookup=None) -> dict:
    """The SLAA/SL+ season rollup for one catcher, computed from raw CAPS --
    the precalc-bound counterpart to `slaa_season_tiles`. Thin wrapper over
    `slaa_summary` with the season's resolved date window; no metric is
    redefined here.

    `precalc.rebuild_catching` writes this dict to
    `precalc_catching_player_season`; `slaa_season_tiles` reads it back
    (with this function as the compute fallback) for the season-default
    view. `lookup=` is exposed for DB-free tests; real callers omit it.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    df = range_pitches_for(int(catcher_id), s, e)
    summary = slaa_summary(df, lookup=lookup)
    return {
        "catcher_id": int(catcher_id),
        "catcher_name": catcher_name(catcher_id),
        "slaa": summary["slaa"],
        "sl_plus": summary["sl_plus"],
        "taken": summary["taken"],
        "season_label": season,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_called_strike_metrics.py -k compute_slaa_season_rollup -q`
Expected: PASS.

- [ ] **Step 5: Add the precalc table + rebuild/read functions in `app/data/precalc.py`**

Add a new table constant near the existing two (after line 32):
```python
CATCHING_SEASON_TABLE = "precalc_catching_player_season"
```
Add its DDL to the `_DDL` dict (the module docstring's "Catching has NO rollup" note at lines
9-17 needs updating too — this is no longer true for SLAA/SL+ specifically; STRIKES/STRIKES
LOST/STEAL% stay on their existing live path via `framing_season_tiles`, unchanged):
```python
    CATCHING_SEASON_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {CATCHING_SEASON_TABLE} (
            catcher_id   BIGINT NOT NULL,
            catcher_name VARCHAR(128),
            slaa         DECIMAL(6,1) NULL,
            sl_plus      DECIMAL(6,1) NULL,
            taken        INT,
            season_label VARCHAR(32) NOT NULL,
            built_at     DATETIME,
            PRIMARY KEY (catcher_id, season_label)
        )""",
```
Add it to `_ROLLUP_PK` (line 76-79) alongside the other two:
```python
_ROLLUP_PK = {
    HITTING_SEASON_TABLE: {"batter_id", "season_label"},
    PITCHING_SEASON_TABLE: {"pitcher_id", "season_label"},
    CATCHING_SEASON_TABLE: {"catcher_id", "season_label"},
}
```
Add the rebuild/read pair, following `rebuild_pitching`/`read_pitching_season`'s exact shape
(after the pitching section, before `rebuild_all`):
```python
# ---- catching (SLAA / SL+ only -- STRIKES/STRIKES LOST/STEAL% stay live) ---

def rebuild_catching(engine=None) -> int:
    from app.data import catching_caps
    engine = engine or get_engine()
    ensure_tables(engine)
    rows = _build_all_seasons(engine, catching_caps.lmu_catchers, "CatcherId",
                              catching_caps._compute_slaa_season_rollup)
    return _replace_rows(engine, CATCHING_SEASON_TABLE, rows)


@cache.cached
def read_catching_season(catcher_id, season=None) -> dict | None:
    row = _read_one(CATCHING_SEASON_TABLE, "catcher_id", catcher_id, season)
    if row is not None:
        for k in ("slaa", "sl_plus"):
            v = row.get(k)
            row[k] = None if v is None or pd.isna(v) else float(v)
    return row
```
Update `rebuild_all` (lines 233-236) to include it:
```python
def rebuild_all(engine=None) -> dict:
    engine = engine or get_engine()
    return {"hitting": rebuild_hitting(engine),
            "pitching": rebuild_pitching(engine),
            "catching": rebuild_catching(engine)}
```

- [ ] **Step 6: Wire `slaa_season_tiles` to read precalc for the season-default view**

Change `slaa_season_tiles` (lines 411-429) from always computing live to reading precalc first
for the whole-season case, mirroring `hitting_caps._season_rollup`'s fallback pattern exactly:
```python
def slaa_season_tiles(catcher_id, season=None, start=None, end=None) -> dict:
    """Display-ready SLAA / SL+ / taken-pitch count for the sidebar.

    Mirrors `framing_season_tiles`' scoping so date-range selection behaves
    identically. For the season-default view (no sub-range, or a sub-range
    equal to the season's own bounds), reads the precalc rollup -- falling
    back to a live compute when the row is absent (pre-rebuild, unbuilt
    catcher, or table not yet created), so correctness never depends on a
    rebuild having run. A genuine sub-range always computes live. Returns
    strings; "—" where a value is unavailable.
    """
    from app.data import seasons, precalc
    tiles = {"slaa": "—", "sl_plus": "—", "taken": "—"}
    if catcher_id is None:
        return tiles
    resolved_season = season or seasons.current_season()
    s_b, e_b = seasons.season_bounds(resolved_season)
    is_season_default = not (start and end) or (str(start) == s_b and str(end) == e_b)
    if is_season_default:
        row = precalc.read_catching_season(int(catcher_id), resolved_season)
        if row is not None:
            tiles["taken"] = str(row["taken"])
            tiles["slaa"] = f"{row['slaa']:+.1f}"
            tiles["sl_plus"] = "—" if row["sl_plus"] is None else f"{row['sl_plus']:.0f}"
            return tiles
    window = _resolve_season_window(season, start, end)
    df = range_pitches_for(int(catcher_id), *window)
    if df is None or df.empty:
        return tiles
    s = slaa_summary(df)
    tiles["taken"] = str(s["taken"])
    tiles["slaa"] = f"{s['slaa']:+.1f}"
    tiles["sl_plus"] = "—" if s["sl_plus"] is None else f"{s['sl_plus']:.0f}"
    return tiles
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_called_strike_metrics.py tests/test_catching_dash.py tests/test_catching_caps.py -q`
Expected: all pass. If the previous `test_slaa_season_tiles_with_no_range_defaults_to_current_season_window`
test (added during the called-strike/SLAA fix round) monkeypatched `range_pitches_for` to assert
it was called with the season window, it will now need to ALSO monkeypatch `precalc.read_catching_season`
to return `None` (forcing the live fallback path) so that test still exercises what it originally
tested — update it accordingly rather than deleting it.

- [ ] **Step 8: Live sanity check**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from app.data import precalc, catching_caps as C
n = precalc.rebuild_catching()
print('rebuilt', n, 'rows')
top = C.lmu_catchers()
cid = int(top.iloc[0]['CatcherId'])
print(C.slaa_season_tiles(cid))
print(precalc.read_catching_season(cid))
"
```
Expected: `slaa_season_tiles` returns the same numbers as `precalc.read_catching_season` for the
same catcher, and both are plausible (compare against the numbers already verified during the
called-strike/SLAA work — should match closely, since no metric is being redefined, only
precalculated). Paste the real output into your report. **A mismatch between the two means the
precalc write and the live compute disagree — stop and investigate, do not ship a precalc path
that returns different numbers than the live path it's supposed to mirror.**

- [ ] **Step 9: Commit**

```bash
git add app/data/precalc.py app/data/catching_caps.py tests/
git commit -m "perf(catching): precalculate SLAA and SL+ instead of always computing live"
```

---

### Task 6: Full-suite verification

**Files:** none modified.

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q --ignore=tests/test_precalc.py`
Expected: 932 (this plan's baseline) plus every new test from Tasks 1-5 passing, 0 failures.
Takes roughly 10-12 minutes.

- [ ] **Step 2: Run `tests/test_precalc.py` separately if it's excluded from the main run for a reason**

Check WHY it's excluded (read the top of the file / the plan's own Global Constraints line, and
`docs/superpowers/specs/2026-08-24-called-strike-slaa-design.md` if it explains the exclusion) —
if it's excluded because it needs a live DB and a rebuild, run it explicitly now since Tasks 4-5
both touch `precalc.py` directly and this is exactly the file that would catch a schema/rebuild
regression the other suites can't see:
```bash
python -m pytest tests/test_precalc.py -q
```
Expected: all pass. If this file can't run in the current environment (e.g. it needs a resource
this environment doesn't have), say so explicitly in your report rather than silently skipping it.

- [ ] **Step 3: If anything fails, fix it before finishing**

Do not finish with failures. Record the failure and its cause.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 SLAA heat map real-feet + rectangle | 3 |
| §1 hitting zone_scatter aspect lock | 3 |
| §1 HitTrax zone-width unification + stats caveat | 3 |
| §1 no shared zone module (explicitly out of scope) | 3 (documented, not built) |
| §2 hitting KPI precalc | 4 |
| §2 catching SLAA/SL+ precalc | 5 |
| §3 perf branch merge + DB index | controller operational steps (not a task) |
| §4 `available_seasons()` always includes today's season | 1 |
| §4 `current_season()` unchanged (deliberate) | 1 (explicit non-change) |
| §4 velo_board/cauldron default to today's calendar season | 1 |
| §5 save-persistence live verification | 2 |
| Global constraint: suite stays green | 6 |

No gaps.

**Placeholder scan:** one deliberate exception, flagged inline rather than left silent — Task 4
Step 1's test body is intentionally incomplete (`...`) because writing it blind risks mismatching
`tests/test_hitting_caps.py`'s real mocking seams; the step explicitly instructs the implementer
to read that file first and write real, complete assertions, and says the placeholder must not
survive into the actual test file. This is the plan's one acknowledged case of "read a
neighbouring file and match its convention" (the same allowance used in the called-strike/SLAA
plan's Task 3/Task 4), not an unresolved TBD.

**Type consistency:** `_compute_slaa_season_rollup`, `CATCHING_SEASON_TABLE`, `rebuild_catching`,
`read_catching_season` are defined in Task 5 and used only there (no downstream task depends on
them). `_compute_season_rollup`'s new return keys (`hard_hit_pct`, `popup_pct`, `xba`) are defined
in Task 4 Step 3 and consumed in Task 4 Step 6 under the same names. `available_seasons()`'s
signature is unchanged (Task 1) so every one of its 12 existing call sites keeps working
unmodified. `slaa_summary`, `_resolve_season_window`, `range_pitches_for` are consumed by Task 5
exactly as they're defined in the already-merged called-strike/SLAA code (verified against the
live file during plan-writing, not assumed from memory).
