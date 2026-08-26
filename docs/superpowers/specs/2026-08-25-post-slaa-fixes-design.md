# Post-SLAA Fixes — Design Spec (2026-08-25)

Five independent, user-reported issues surfaced right after the called-strike/SLAA merge. Scoped
via four parallel read-only research forks; three design decisions were confirmed directly by the
user. This spec captures what each fork found and exactly what "fixed" means for each item, so
the plan can be written against firm facts rather than re-deriving them.

## 1. Strike-zone rectangle consistency

**Finding:** only two charts are actually broken. Every other zone chart in the codebase
(framing scatter, pitching location, bullpen, HitTrax practice) already plots on real feet/inches
with `scaleanchor="x", scaleratio=1` and renders a correct rectangle.

- **`app/dashboards/catching/charts.py:slaa_location_figure`** (lines ~152-238). Plots the 7×7
  grid on implicit index coordinates (0-6 in both x and y) rather than real feet. The zone-outline
  `add_shape` is drawn at cell-index bounds `x0=0.5,x1=5.5,y0=0.5,y1=5.5` — inherently square in
  index space regardless of the real 1.66ft(w)×2.0ft(h) zone it represents. `scaleanchor="x",
  scaleratio=1` (line 233) locks 1 index-unit-x = 1 index-unit-y, which is why it renders square.
  **Fix:** plot the heatmap on real feet (pass explicit `x=`/`y=` bin-center arrays instead of
  relying on default index positions) and draw the zone outline at real feet bounds
  `x0=-0.83,x1=0.83,y0=1.5,y1=3.5` — matching `app/data/pitching.py:354`'s `_SZ` and
  `app/dashboards/bullpen/charts.py:18`'s `_ZONE` conventions exactly, so this chart's zone
  geometry finally uses the same real numbers everyone else already uses. With real feet on both
  axes, `scaleanchor="x", scaleratio=1` will correctly render the true (non-square) shape.
- **`app/dashboards/hitting/charts.py:_style_axes`** (line 76). `scaleanchor=None` is set
  explicitly — the only zone chart with NO aspect lock at all. Its zone box (`_SZ = (-10, -13,
  10, 13)`, i.e. 20"×26", already correctly non-square in DATA units) and its fixed axis ranges
  (`_XRANGE=(-50,50)`, `_YRANGE=(-35,35)`, i.e. 100×70) are already proportioned correctly — but
  without a scale lock, Plotly can stretch/squish the rendered plot to fit whatever container size
  it's given. **Fix:** change `scaleanchor=None` to `scaleanchor="x"` (line 76) so the already-
  correct data proportions are actually preserved on screen, matching every other zone chart's
  convention.
- **User-confirmed, out of the "broken" list but bundled in per explicit instruction:**
  `app/data/practice.py:34` (`SZ_X0, SZ_X1 = -0.708, 0.708`) uses a narrower half-width (1.42ft
  total) than the standard 0.83ft (1.66ft total) used everywhere else. User confirmed: unify to
  the standard 1.66ft. **Caveat found during scoping, not purely cosmetic:** this same constant
  is also used at `practice.py:368` to classify `in_zone` for practice swing-decision statistics
  (`in_zone = df[(df["px"].between(SZ_X0, SZ_X1)) & (df["py"].between(SZ_Y0, SZ_Y1))]`) — widening
  it will retroactively change what counts as "in zone" for every practice report that reads this
  classification, not just how the chart looks. Proceeding per the user's confirmed decision, but
  this must be called out plainly in the task's commit message and report, not silently folded in.
- **Not in scope (documented, not fixed):** no shared zone-constants module exists — the real-feet
  box is hand-copied independently in `app/data/bullpen.py`, `app/data/pitching.py`,
  `app/reports/plots.py`, and `app/dashboards/bullpen/charts.py`. Extracting a shared module is a
  legitimate future cleanup but is NOT requested here and must not be done as a drive-by — only
  the two broken charts and the one confirmed constant change are in scope.

## 2. Precalculate the new catching/hitting KPIs

**Finding:** the existing precalc system (`app/data/precalc.py`) already has exactly the right
shape to extend — one row per `(player_id, season_label)` in a dedicated MySQL table, rebuilt via
`flask rebuild-precalc`, gated by a `precalc_meta` data-version stamp that invalidates every
worker's in-process cache on a rebuild. The site's 3 Gunicorn workers (`gunicorn.conf.py`,
`preload_app=False` deliberate) each hold a *separate* in-process cache — DB-backed precalc is
what makes a computed rollup shared across all 3 workers instead of recomputed per worker.

- **Hitting:** `precalc_hitting_player_season` (schema at `precalc.py:44-54`) stores
  `qab_pct/ba/obp/slg/pa/ab/h/doubles/triples/hr/bb/so` — **no Hard-Hit%/Pop-Up%/xBA columns**.
  These three ARE already built and live in the dashboard (`hitting_caps.py:238-271`,
  `layout.py:58-59`) but were deliberately built to always compute live (per the original
  hitting-KPIs plan: "computed FRESH from a live pull... same approach used for the catcher
  STEAL% tile"), never through the precalc fast path the other four tiles use. **Fix:** add
  `hard_hit_pct`, `popup_pct`, `xba` columns to the table, compute them inside
  `hitting_caps._compute_season_rollup` (the function `rebuild_hitting` already calls per-player-
  per-season), and wire `sidebar_stats`' existing season-precalc-fast-path branch to read them
  from precalc for the whole-season view — falling back to the existing live compute for a
  sub-range selection, exactly matching how QAB%/BA/SLG/OBP already work today.
- **Catching:** no precalc table exists — `precalc_catching_player_season` was deliberately
  retired 2026-08-13 because framing tiles were "just a cheap aggregate off a cached primitive."
  That's no longer fully true: SLAA/SL+ additionally need `called_strike._get_lookup()`'s full
  952-cell lookup built from a ~56,000-row scan. **Fix:** add a new `CATCHING_SEASON_TABLE`
  (`precalc_catching_player_season`) storing `slaa`, `sl_plus`, `taken` per `(catcher_id,
  season_label)`, a `rebuild_catching()` following the exact `rebuild_hitting`/`rebuild_pitching`
  pattern (`_build_all_seasons(engine, catching_caps.lmu_catchers, "CatcherId",
  catching_caps._compute_slaa_season_rollup)`), a `read_catching_season()` mirroring
  `read_hitting_season`, and wire `slaa_season_tiles` to read from it for the whole-season view
  (same season-bounds-equality check `framing_season_tiles`/`slaa_season_tiles` already use via
  the shared `_resolve_season_window` helper), falling back to live compute for a sub-range. Add
  `rebuild_catching` to `rebuild_all()`'s dict. STRIKES/STRIKES LOST/STEAL% tiles are UNCHANGED —
  they stay on their existing live/precalc paths exactly as-is; only SLAA/SL+/taken move onto the
  new table.
- **Explicitly out of scope:** re-litigating whether `called_strike._get_lookup()` itself should
  persist to a DB table (it's already `@cached` process-wide + warmed at startup, per the prior
  session — see `memory/MEMORY.md` §12). This spec's precalc addition is about the *season rollup
  numbers* (SLAA/SL+/Hard-Hit%/Pop-Up%/xBA per player), not the underlying probability model.

## 3. Site performance

**Finding:** a concrete, non-infra cause exists. `feat/2026-08-23-db-audit-perf` (pushed
2026-08-23, full suite green at the time) was never merged into `main` — confirmed via `git
merge-base --is-ancestor`. Live `main` still has the index-defeating `DATE(...)` query wrappers
in `app/data/bullpen.py` and `app/data/velo_board.py`, and zero response compression anywhere
(`Flask-Compress` not in `requirements.txt`, no `compress=` on any of the 7 `Dash(...)`
constructors). User confirmed: merge that branch in. This is a **git merge + conflict resolution
against 38 commits of drift + full-suite re-verification** — not new feature code, so it is
handled as a direct operational step outside this plan's TDD task structure (see plan's
"Operational steps" section), not as a numbered task here.

**Also confirmed:** GAMES has composite indexes for `(BatterId,Date)` and `(PitcherId,Date)` but
only single-column indexes for `CatcherId` and `Date` separately — no `(CatcherId,Date)`
composite, which the new SLAA/framing queries (`catching_caps.range_pitches_for`) filter on
directly. User confirmed: add it. This is a direct `ALTER TABLE` against live production RDS —
also handled as a direct operational step, not a plan task (no code changes, nothing to
TDD-cycle).

**Not fixable in this scope:** Render's free-tier instance cold-starts after idling
(`memory/MEMORY.md`), which is a real, separate, non-code contributor to "loading slower" that
this spec does not attempt to address.

## 4. Velo Board / Competitive Cauldron season/week availability

**Root cause, confirmed against live data:** `GAMES` max date = 2026-05-16, `BULLPEN` max date =
2026-05-13 — genuinely zero Aug-2026 rows anywhere (pre-semester, expected). But there is also a
real code bug layered on top: `app/data/seasons.py:available_seasons()` derives "which seasons
exist" **only from `GAMES`** (`SELECT DISTINCT Date FROM GAMES WHERE BatterTeam=:t AND
<numeric-date-regex>`). With zero Fall-2026 GAME rows, `"2026/2027"` never appears in the returned
list, so `current_season()` (line 43-47) falls back to `"2025/2026"` — bounds ending
`2026-07-31`. `app/data/velo_board.py:default_week_for()` (lines 192-206) clamps
`anchor = min(today, end)` against that season's `end` bound, landing on the Monday of that
week — **July 27, 2026, exactly the reported symptom.** `app/dashboards/cauldron/` shares this
same `default_week_for` function.

**The part that matters for next week:** even once Fall-2026 `BULLPEN` data starts loading (which
happens well before any `GAMES` rows exist — bullpens run before games), `"2026/2027"` STILL
won't appear as a selectable Season option and the week picker's `max_date_allowed` stays
hard-capped at `2026-07-31`, because `available_seasons()` is blind to `BULLPEN` entirely. A coach
would have literally no way to navigate to new data even after it exists.

**Design decision — read carefully, this affects more than the two reported boards.**
`app/data/seasons.py`'s `current_season()`/`available_seasons()` are used by **12 files**
(catching, hitting, pitching dashboards + precalc + reports), not just Velo Board/Cauldron.
Two different fixes are needed for two different reasons:

1. **`available_seasons()` must always include today's actual calendar academic-year label**
   (`seasons.season_label_for(date.today().isoformat())`), unioned with whatever `GAMES` already
   reports — additive, safe, cannot remove an existing option. This makes `"2026/2027"`
   selectable in every Season dropdown across the site the moment it becomes the real calendar
   season, regardless of whether any table has a single row for it yet. This is the fix that
   actually removes the hard cap.
2. **`current_season()`'s DEFAULT-selection behavior stays unchanged** (still "latest season with
   real GAMES data, else today's calendar season if GAMES is entirely empty"). Do NOT make this
   function prefer today's calendar season by default: catching/hitting/pitching dashboards
   currently default sensibly to the last season that actually has data, and changing that global
   default would make those three dashboards open to an empty view every single day between now
   and whenever real Fall-2026 GAMES rows start landing (likely months after Velo Board/Cauldron
   need to work). This is a genuine, deliberate scope boundary — resist the urge to "fix" this
   function further than item 1 above.
3. **Velo Board and Cauldron specifically** (not the other three dashboards) should default their
   OWN initial season selection to `seasons.season_label_for(date.today().isoformat())` directly
   — bypassing `current_season()`'s GAMES-only preference — at the `app/dashboards/velo_board/
   layout.py` and `app/dashboards/cauldron/layout.py` call sites that currently call
   `seasons.current_season()` for their default. Rationale: these two boards' whole purpose is
   "what happened this week," their underlying data source is `BULLPEN` (not `GAMES`) which will
   have Fall-2026 rows well before any game is played, and once item 1 makes `"2026/2027"`
   selectable, defaulting straight to today's real calendar season means a coach opening these two
   boards next week sees the actual current week immediately — even if it's still empty on day
   one — rather than a frozen July snapshot with no visual indication anything is stale. An empty-
   but-current week is a more honest default here than a populated-but-4-months-stale one.

Find every call site in `app/dashboards/velo_board/layout.py` and `app/dashboards/cauldron/
layout.py` that resolves the DEFAULT season (there may be more than one — check `serve_layout`
and any layer-2 prefetch blocks, following the pattern documented in
`app/dashboards/catching/layout.py`) and switch each one from `seasons.current_season()` to
`seasons.season_label_for(date.today().isoformat())`. Do NOT touch how the Season dropdown's
*options list* is built (that's `available_seasons()`, fixed once in item 1 and inherited by
both boards automatically) — only the *default selected value*.

## 5. Save-persistence verification (safety-critical)

**Finding, via full code trace:** both `velo_board.upsert_entries`/`set_override` and
`cauldron.upsert_daily` do real transactional writes (`with get_engine().begin() as conn:
conn.execute(...)`), not no-ops. Read paths (`read_entries`/`read_overrides`/`read_daily`/
`read_scoring`) are NOT `@cached` — only the auto-computed Trackman metrics are cached, never
coach-edited fields — so no caching layer can mask a successful save behind a stale read.
`_on_save` (`app/dashboards/velo_board/callbacks.py:81-97`) re-checks `current_user.is_coach`
server-side inside the callback itself (not just via a hidden button), so this is correctly
enforced regardless of account, and it writes then immediately RE-READS from the DB and returns
the freshly-read rows to the UI in the same response — a real save-then-verify round trip within
one request. Real DB round-trip tests exist and pass (`test_upsert_inserts_then_updates`,
`test_set_override_roundtrip`, `test_daily_upsert_and_team_and_scoring_seed`).

**The one gap, and why it needs a live test rather than more code reading:** every row in the
rendered DataTable carries a hidden id column (present in the row's `data` dict, excluded from
the visible `columns` spec) that the save callback trusts survived the round trip through the
browser. This is a standard, normally-reliable Dash idiom — but nothing in this repo's test suite
exercises a REAL rendered table + a REAL simulated cell edit + save; every existing test calls
`save_board`/`upsert_entries` directly with a hand-built dict. The only way to close this
specific gap is a live browser test: load the dashboard as a coach, edit a cell through the
actual DataTable UI (not a direct function call), click Save, then load the dashboard AGAIN as a
genuinely fresh page load (proving the value survived past the single request/response cycle that
`_on_save`'s own re-read already covers) and confirm the edited value is present. This repo
already has Playwright installed and used it for the SLAA heat map's live check
(`.superpowers/sdd/2026-08-24-called-strike-slaa/task-4-report.md`, deleted now but referenced in
`memory/MEMORY.md` §8) — same tool, same pattern, for both Velo Board and Cauldron.

If this live test finds the hidden-id-survives-the-round-trip assumption is actually broken,
that is a Critical, stop-and-fix-before-anything-else finding — do not treat it as a nice-to-have
regression test if it fails.

## Global Constraints

- Do not touch `app/data/called_strike.py`, `app/data/catching_caps.py`'s already-reviewed SLAA
  functions' EXISTING behavior, or anything from the called-strike/SLAA plan beyond what's
  explicitly listed above (the STRIKES/STRIKES LOST/STEAL% tiles, `add_framing_cols`) — those are
  done, reviewed, and merged; this spec only adds a precalc fast-path in front of them.
- Do not touch `app/dashboards/velo_board/visual.py`, `app/dashboards/cauldron/visual.py`,
  `app/static/brand/CauldronScript.ttf`, `app/static/reports/top-gun-logo*.png` if encountered —
  these are separate in-progress header work the user has repeatedly flagged as off-limits across
  prior sessions.
- Follow existing patterns in each touched module. TDD. Run only the relevant test files per
  task, plus a full-suite run at the end (Task 5, mirroring the called-strike/SLAA plan's Task 5).
- `python -m pytest`, not bare `pytest`. Windows; Git Bash available; `PYTHONIOENCODING=utf-8`
  for any script with non-ASCII output.
- The full suite must stay green throughout: `python -m pytest -q --ignore=tests/test_precalc.py`
  (932 passing before this work, per the called-strike/SLAA plan's final state).
