# PAW Changes Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 10 coach-requested changes across the Hitting/Pitching/Catching game dashboards, the Hittrax practice dashboard, the Bullpen dashboard, and the pitcher/bullpen reports.

**Architecture:** Dash (Flask) app reading an RDS MySQL `GAMES`/`BULLPEN`/`PRACTICE_SESSIONS` schema through `app/data/*` data-layer modules; dashboards under `app/dashboards/<module>/`; reports under `app/reports/`. Two cross-cutting patterns already exist and are the reference: pitching's range-aware sidebar (`range_summary`) and its `_on_range` daterange callback. Most changes are data-layer functions + callback wiring + a couple of report/template edits.

**Tech Stack:** Python, Dash/Plotly, pandas, SQLAlchemy (`query_df`), matplotlib (report PNGs), WeasyPrint + Playwright (report PDF), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-changes-batch-design.md`.
- Player-list-by-date-range applies to **all six dashboards** (user-confirmed).
- Swing-decision trend hover shows the **percentage only** — no avg EV/distance (user-confirmed).
- Bullpen has **no PitchCall column**; per-session strike% uses the existing **zone-based** `bullpen.strike_pct` definition (matches the report header + sidebar KPI).
- No change to the swing-decision formula (In-Zone% − Chase%) or the EV/distance `sfz-*` chips.
- Run tests in the FOREGROUND (env kills background tasks ~5min); long suites `timeout=600000`.
- Dev server: `PYTHONIOENCODING=utf-8 PAW_WARM_CACHE=1 python run.py`; `taskkill //F //IM python.exe` before restart to avoid stale servers on 8050.
- Commit per task. Do not push or merge (user reviews first).

---

### Task 1: Hitting sidebar reflects the selected date range

**Files:**
- Modify: `app/data/hitting_caps.py` (`sidebar_stats`, add range compute path)
- Modify: `app/dashboards/hitting/layout.py` (`sidebar` signature + caption)
- Modify: `app/dashboards/hitting/callbacks.py` (`_on_sidebar` Inputs)
- Test: `tests/data/test_hitting_caps.py` (or the existing hitting_caps test module)

**Interfaces:**
- Produces: `hitting_caps.sidebar_stats(batter_id, season=None, start=None, end=None) -> {"qab","BA","SLG","OBP"}`; `hitting/layout.sidebar(batter_id, season=None, start=None, end=None)`.

- [ ] **Step 1: Write the failing test** — range equal to season bounds matches the season rollup; a narrow sub-range differs.

```python
def test_sidebar_stats_range_equals_season_matches_rollup():
    from app.data import hitting_caps, seasons
    bid = hitting_caps.lmu_hitters().iloc[0]["batter_id"]
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    full = hitting_caps.sidebar_stats(int(bid), season)
    ranged = hitting_caps.sidebar_stats(int(bid), season, start=str(s), end=str(e))
    assert ranged == full

def test_sidebar_stats_subrange_is_scoped():
    from app.data import hitting_caps, seasons
    bid = int(hitting_caps.lmu_hitters().iloc[0]["batter_id"])
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    # a 1-day window should not error and returns the 4 keys
    narrow = hitting_caps.sidebar_stats(bid, season, start=str(s), end=str(s))
    assert set(narrow) == {"qab", "BA", "SLG", "OBP"}
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/data/test_hitting_caps.py -k sidebar_stats -v` (TypeError: unexpected kwargs / signature mismatch).

- [ ] **Step 3: Implement.** In `hitting_caps.sidebar_stats`, add `start=None, end=None`. When both are given AND they are not equal to `season_bounds(season)`, compute over `range_pitches`/`game_pitches` in `[start,end]` using the same helper chain `_compute_season_rollup` uses (`qab_frame` + `_slash_counts`/`_slash_from_pas`) but with the caller's bounds; otherwise keep the current `_season_rollup(batter_id, season)` fast path. Factor the compute so the season-bounds and range paths share one function (e.g. `_rollup_over(batter_id, start, end)`), and have `_compute_season_rollup` call it with season bounds. Return the same dict shape.

- [ ] **Step 4: Wire callback + layout.** In `hitting/callbacks.py` `_on_sidebar`, add `Input("hit-daterange","start_date")` and `Input("hit-daterange","end_date")`; call `layout.sidebar(bid, season, start, end)`. In `hitting/layout.py` `sidebar`, accept/forward `start`/`end` to `sidebar_stats`; change the caption to "Stats reflect the selected date range."

- [ ] **Step 5: Run tests + a callback-wiring test.**

```python
def test_hitting_sidebar_callback_lists_daterange_inputs():
    from app import create_app
    app = create_app()
    ids = _input_ids_for_output(app, "sidebar", "children", dash_prefix="hitting")  # helper in this test module
    assert any(i for i in ids if i == ("hit-daterange", "start_date"))
```
(If no such helper exists, assert against the registered callback map the way sibling tests do — follow the existing `test_game_options_refresh_on_hitter_change` pattern.)

Run: `pytest tests/ -k "hitting and sidebar" -v` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat(hitting): sidebar KPIs reflect selected date range"`.

---

### Task 2: Catching sidebar reflects the selected date range

**Files:**
- Modify: `app/data/catching_caps.py` (`framing_season_tiles`, add range path)
- Modify: `app/dashboards/catching/layout.py` (`sidebar` signature + caption)
- Modify: `app/dashboards/catching/callbacks.py` (`_on_sidebar` Inputs)
- Test: catching_caps test module + a callback-wiring test

**Interfaces:**
- Produces: `catching_caps.framing_season_tiles(catcher_id, season=None, start=None, end=None) -> {"games","pitches","net_strikes","steal_pct"}`; `catching/layout.sidebar(catcher_id, season=None, start=None, end=None)`.

- [ ] **Step 1: Failing test** — mirror Task 1: range==season bounds equals the season tiles; a sub-range returns the 4 keys without error.

```python
def test_framing_tiles_range_equals_season_matches():
    from app.data import catching_caps, seasons
    cid = int(catching_caps.lmu_catchers().iloc[0]["catcher_id"])
    season = seasons.current_season(); s, e = seasons.season_bounds(season)
    assert catching_caps.framing_season_tiles(cid, season, str(s), str(e)) \
        == catching_caps.framing_season_tiles(cid, season)
```

- [ ] **Step 2: Verify failure** — signature mismatch.

- [ ] **Step 3: Implement.** `framing_season_tiles` gains `start=None, end=None`. `_compute_season_rollup` is already `WHERE CatcherId IN (...) AND Date BETWEEN :s AND :e`; extract a `_rollup_over(catcher_id, s, e)` used by both the season path (season bounds) and the range path (caller bounds). Keep the precalc fast path when dates are absent or equal season bounds.

- [ ] **Step 4: Wire.** `catching/callbacks.py` `_on_sidebar`: add `cat-daterange` start/end Inputs → `layout.sidebar(cid, season, start, end)`. `catching/layout.py` `sidebar`: forward start/end; caption → "Stats reflect the selected date range."

- [ ] **Step 5: Run** — `pytest tests/ -k "catching and (framing or sidebar)" -v` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat(catching): sidebar tiles reflect selected date range"`.

---

### Task 3: Hittrax player dropdown limited to the date range

**Files:**
- Modify: `app/data/practice.py` (add `players_in_range`)
- Modify: `app/dashboards/hitting_practice/callbacks.py` (`_on_filters` uses range for options)
- Modify: `app/dashboards/hitting_practice/layout.py` (`serve_layout` scopes first paint)
- Modify: `app/dashboards/hitting_practice/selectors.py` (`resolve_player` fallback if needed)
- Test: practice test module + a callback test

**Interfaces:**
- Produces: `practice.players_in_range(start, end, exclude_test=True) -> list[str]`.

- [ ] **Step 1: Failing test.**

```python
def test_players_in_range_scopes_by_date():
    from app.data import practice
    everyone = set(practice.all_player_names())
    d = practice.latest_session_date()
    on_last = set(practice.players_in_range(str(d), str(d)))
    assert on_last <= everyone
    assert on_last == set(practice.players_on_date(d))  # single-day equivalence
```

- [ ] **Step 2: Verify failure** — `AttributeError: players_in_range`.

- [ ] **Step 3: Implement** in `practice.py` (model on `players_on_date`, lines 96-105):

```python
def players_in_range(start, end, exclude_test: bool = True) -> list[str]:
    """Alphabetical player names with a session in [start, end]."""
    if not start or not end:
        return all_player_names(exclude_test)
    where = ("WHERE session_date BETWEEN :s AND :e AND user_name IS NOT NULL "
             "AND TRIM(user_name) <> ''" + _test_clause("user_name", exclude_test))
    df = query_df(f"SELECT DISTINCT user_name AS name FROM PRACTICE_SESSIONS "
                  f"{where} ORDER BY user_name", {"s": str(start), "e": str(end)})
    return [] if df.empty else [str(n) for n in df["name"].dropna()]
```

- [ ] **Step 4: Wire options + first paint.** In `callbacks.py` `_on_filters` (lines 44-66), replace `names = P.all_player_names()` with `names = P.players_in_range(ds, de)`; rebuild `popts`. If the selected `player` is not in `names`, fall back to `names[0]` (or keep `player` when list empty) so the store/charts don't blank out. In `layout.py` `serve_layout` (lines 79-86), derive the initial names from `P.players_in_range(default_start, default_end)` matching the season default it already computes.

- [ ] **Step 5: Run** — `pytest tests/ -k "practice and (players or filters)" -v` → PASS. Manual note: verify dropdown shrinks under "Past Week".

- [ ] **Step 6: Commit** — `git commit -am "feat(hittrax): player dropdown limited to selected date range"`.

---

### Task 4: Bullpen pitcher dropdown limited to the date range

**Files:**
- Modify: `app/data/bullpen.py` (`lmu_bullpen_pitchers` gains optional start/end)
- Modify: `app/dashboards/bullpen/callbacks.py` (new options callback)
- Modify: `app/dashboards/bullpen/layout.py` (`serve_layout` first paint scope)
- Modify: `app/dashboards/bullpen/selectors.py` (`pitcher_options` accepts a df or range)
- Test: bullpen test module + callback test

**Interfaces:**
- Produces: `bullpen.lmu_bullpen_pitchers(start=None, end=None) -> DataFrame[pitcher_id, pitcher, sessions, last_date]`.

- [ ] **Step 1: Failing test.**

```python
def test_lmu_bullpen_pitchers_scopes_by_date():
    from app.data import bullpen as B
    everyone = set(B.lmu_bullpen_pitchers()["pitcher_id"])
    ranged = set(B.lmu_bullpen_pitchers(start="1900-01-01", end="1900-01-02")["pitcher_id"])
    assert ranged == set()          # no bullpens in 1900
    assert everyone                 # sanity: unscoped still returns pitchers
```

- [ ] **Step 2: Verify failure** — `TypeError: unexpected keyword`.

- [ ] **Step 3: Implement.** Add `start=None, end=None`; when both present append `AND DATE(Date) BETWEEN :start AND :end` to the WHERE and pass params. No args = unchanged.

- [ ] **Step 4: Wire.** Add a callback `Output("bp-pitcher-dd","options")` keyed on `Input("bp-daterange","start_date")` + `Input("bp-daterange","end_date")` (+ coach/own-id State) that calls `selectors.pitcher_options` backed by `lmu_bullpen_pitchers(start, end)` — mirror the existing session-dd refresh at `callbacks.py:40-51`. Update `selectors.pitcher_options` to accept an already-scoped df (or start/end). Scope `serve_layout`'s first-paint options with the season default range. Add selection fallback (reselect first available if current pitcher drops out).

- [ ] **Step 5: Run** — `pytest tests/ -k "bullpen and (pitcher or options)" -v` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat(bullpen): pitcher dropdown limited to selected date range"`.

---

### Task 5: Game-dashboard rosters (hit/pit/cat) limited to the date range

**Files:**
- Modify: `app/data/hitting_caps.py` (`lmu_hitters` optional start/end), `app/data/pitching_caps.py` (`lmu_pitchers`), `app/data/catching_caps.py` (`lmu_catchers`)
- Modify: `app/dashboards/{hitting,pitching,catching}/callbacks.py` (`_on_range` gains an options Output for the roster dd), `.../selectors.py`, `.../layout.py` (serve_layout first paint)
- Test: per-module caps test + callback wiring test

**Interfaces:**
- Produces: `lmu_hitters(season=None, start=None, end=None)`, `lmu_pitchers(...)`, `lmu_catchers(...)` — same columns as today, additionally scoped to `[start,end]` when given.

- [ ] **Step 1: Failing test (per module, hitting shown).**

```python
def test_lmu_hitters_scopes_by_date():
    from app.data import hitting_caps as H, seasons
    season = seasons.current_season(); s, e = seasons.season_bounds(season)
    full = set(H.lmu_hitters(season)["batter_id"])
    ranged = set(H.lmu_hitters(season, start=str(s), end=str(e))["batter_id"])
    assert ranged <= full
    empty = H.lmu_hitters(season, start="1900-01-01", end="1900-01-02")
    assert empty.empty
```

- [ ] **Step 2: Verify failure** — signature mismatch.

- [ ] **Step 3: Implement** the optional `start`/`end` scoping in all three `lmu_*` roster queries (add a `Date BETWEEN` clause; keep the existing season-bounds + numeric-GameID guards). No args → unchanged.

- [ ] **Step 4: Wire.** In each dashboard's `_on_range` callback (already fires on `*-daterange` start/end and rebuilds the game/outing dd), add `Output("{hitter|pitcher|catcher}-dd","options")` computed from `lmu_*(season, start, end)` via the module's `selectors.*_options`. Scope `serve_layout`'s first-paint roster options to the season default range. Add the out-of-range selection fallback (reselect first available). Preserve the player-role self-lock (access gate unchanged).

- [ ] **Step 5: Run** — `pytest tests/ -k "(hitters or pitchers or catchers) and scope" -v` and the existing dashboard callback tests → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat(dashboards): game rosters limited to selected date range"`.

---

### Task 6: Hittrax — all swing-decision zones selectable

**Files:**
- Modify: `app/dashboards/hitting_practice/tabs/swing_frequency.py` (`sds_zone_chip_row`)
- Modify: `app/dashboards/hitting_practice/callbacks.py` (`_sds_toggle`, `_sds_styles`)
- Test: a component/logic test

- [ ] **Step 1: Failing test** — building the chip row yields no disabled chips, and the toggle accepts a currently-empty zone.

```python
def test_sds_chips_all_enabled_even_when_zone_empty():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import swing_frequency as SF
    df = pd.DataFrame({"zone_section": [1, 2, 3]})   # zones 4-13 absent
    row = SF.sds_zone_chip_row(df)
    buttons = _collect_buttons(row)                  # helper: walk children
    assert all(getattr(b, "disabled", False) is False for b in buttons)
```

- [ ] **Step 2: Verify failure** — absent zones are `disabled=True` today.

- [ ] **Step 3: Implement.** In `sds_zone_chip_row`, set every chip `disabled=False` (drop the `z not in present` gate) and stop greying absent zones (pass `present=True` to `chip_style`, or treat the styling present-set as all `_ZONES`). Store `sds-present` = all `_ZONES` (so the style callback never greys). In `callbacks.py` `_sds_toggle`, remove the `if z not in present: return active` guard so empty-zone clicks toggle. `_sds_styles` then styles purely on active/inactive.

- [ ] **Step 4: Run** — `pytest tests/ -k "sds" -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(hittrax): allow selecting any swing-decision zone"`.

---

### Task 7: Hittrax — swing-decision trend hover text

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py` (`swing_decision_trend_fig`)
- Test: figure smoke test

- [ ] **Step 1: Failing test.**

```python
def test_swing_decision_trend_hover_and_no_stray_trace():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    tdf = pd.DataFrame({"play_date": pd.to_datetime(["2026-05-10"]),
                        "in_zone_pct": [40.0], "chase_pct": [60.0], "score": [-20.9]})
    fig = charts.swing_decision_trend_fig(tdf)
    main = [t for t in fig.data if getattr(t, "mode", "") and "markers" in t.mode][0]
    assert "Swing Decision" in main.hovertemplate
    # zero-line must not surface as a hover trace ("trace 5")
    assert all(getattr(t, "hoverinfo", None) == "skip"
               for t in fig.data if t is not main and getattr(t, "mode", None) == "lines"
               and t.name in (None, ""))
```

- [ ] **Step 2: Verify failure** — no hovertemplate today; hline surfaces.

- [ ] **Step 3: Implement.** On the main Scatter, add `customdata` (score) and `hovertemplate="%{x} — Swing Decision: %{customdata:.1f}%<extra></extra>"` (x is already the `"%b %d"` label). Replace the bare `fig.add_hline(y=0, ...)` with a line trace/shape that does not surface on hover (`hoverinfo="skip"`, or use `fig.add_shape` for a non-trace line). No averages.

- [ ] **Step 4: Run** — `pytest tests/ -k "swing_decision_trend" -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "fix(hittrax): clearer swing-decision trend hover, drop stray trace"`.

---

### Task 8: Hittrax — Session Tables freeze (investigate then fix)

**Files:**
- Modify (likely): `app/data/practice.py` (`load_player_stats` scoped to player), `app/dashboards/hitting_practice/tabs/session_tables.py`, `app/dashboards/hitting_practice/tables.py`, `app/dashboards/hitting_practice/callbacks.py` (`_render`)
- Test: whatever the confirmed fix needs

> **This task uses systematic-debugging. Do NOT patch before confirming the cause.**

- [ ] **Step 1: Reproduce & measure.** Run the app; open Hittrax → Session Tables for the demo player over "This Season". Capture: row counts returned by `load_player_stats` and `load_sessions` (add a temporary log or run the queries directly), and how many times `_render` fires per interaction. Record where the wall-clock goes (query time vs. payload size to the browser).

- [ ] **Step 2: Write a failing/guard test for the confirmed cause.** Examples depending on findings:
  - If `load_player_stats` is the cost: add `load_player_stats(player=None, ...)` and test it filters server-side (returns ≤ the one player's row) instead of loading all players.
  - If repeated `_render` is the cost: test that opening the tab does not re-query when only unrelated inputs change.

- [ ] **Step 3: Implement the minimal confirmed fix.** Most likely: scope `load_player_stats` by player (push the Python-side filter in `session_tables.render` into SQL), and/or trim what `df_table` ships (`sort_action`), and/or avoid redundant `_render` reloads. Keep `page_size=15`.

- [ ] **Step 4: Verify.** Re-open the tab; confirm it loads and repeated clicks stay responsive. Run `pytest tests/ -k "practice or session_tables" -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "perf(hittrax): fix Session Tables load/freeze (<root cause>)"`.

---

### Task 9: Pitching — "In Play" shows the actual outcome

**Files:**
- Modify: `app/data/pitching.py` (`pretty_result` → two-arg; `fig_location`; `fig_location_split` for consistency)
- Modify: `app/dashboards/pitching/tabs/location_movement.py` (table "Result" column + Result filter)
- Test: `tests/data/test_pitching.py` (pretty_result) + a chart/tab smoke

**Interfaces:**
- Produces: `pitching.pretty_result(pitch_call, play_result=None) -> str`.

- [ ] **Step 1: Failing test.**

```python
def test_pretty_result_prefers_real_outcome():
    from app.data.pitching import pretty_result
    assert pretty_result("InPlay", "Single") == "Single"
    assert pretty_result("InPlay", "HomeRun") == "Home Run"
    assert pretty_result("StrikeCalled", None) == "Called Strike"
    assert pretty_result("InPlay", "Undefined") == "In Play"   # falls back
    assert pretty_result("InPlay") == "In Play"                # single-arg back-compat
```

- [ ] **Step 2: Verify failure** — current `pretty_result` is single-arg.

- [ ] **Step 3: Implement.** Extend `pretty_result(pitch_call, play_result=None)`: if `play_result` is a real outcome (not None/NaN/"Undefined"/"None"/""), return it spaced ("HomeRun"→"Home Run") — reuse the logic in `app/data/video.py` `_result`/`_spaced` (import or replicate the tiny helper). Otherwise return the existing `_RESULT_LABELS` mapping of `pitch_call`. In `fig_location`, build `_res` from both columns: `d.apply(lambda r: pretty_result(r["pitch_call"], r["play_result"]), axis=1)` (ensure `play_result` is selected — it is, via `_PITCH_SELECT`). Update `fig_location_split` the same way.

- [ ] **Step 4: Wire the tab.** In `location_movement.py`, the "Result" column and the Result(s) filter/options must use the two-arg form (`df.apply(...)` over `pitch_call`+`play_result`). The filter option list then contains granular outcomes.

- [ ] **Step 5: Run** — `pytest tests/ -k "pretty_result or location_movement" -v` → PASS. Manual: hover an in-play pitch → shows Single/Double/Out/etc.

- [ ] **Step 6: Commit** — `git commit -am "feat(pitching): show actual outcome for in-play pitches"`.

---

### Task 10: Pitcher report generation speedup

**Files:**
- Modify: `app/reports/pdf.py` (`html_to_pdf` — persistent browser, `wait_until="load"`)
- Modify: `app/data/pitching_caps.py` (`game_pitches` → `@cached`)
- Test: existing report tests stay green; measure before/after

> Uses systematic-debugging for the measurement; the code change is the shared-browser refactor.

- [ ] **Step 1: Measure the miss path.** Clear `instance/report_cache`; time one `build_pitcher_postgame(game_id, pitcher_id)` cold. Record the split (Chromium launch vs matplotlib vs queries) with quick timestamps.

- [ ] **Step 2: Implement the shared browser.** Refactor `html_to_pdf` so Chromium/Playwright is launched **once** and reused across calls (module-level lazy singleton guarded by a `threading.Lock`; reuse a browser, create a fresh `page`/context per call, close the page not the browser). Switch `set_content(..., wait_until="load")` (all assets are inlined, so no network to idle-wait). Ensure a clean shutdown path (atexit or on app teardown) and that a crashed browser is relaunched.

- [ ] **Step 3: Cache the query.** Add `@cached` to `pitching_caps.game_pitches` (match `game_pitches_for`).

- [ ] **Step 4: Verify.** `pytest tests/ -k report -v` → PASS (PDF still valid bytes; LMU guard intact). Re-time cold build; confirm it dropped materially (target: well under 10s) and a cache hit is still ~0.4s. Record the numbers.

- [ ] **Step 5: Commit** — `git commit -am "perf(report): reuse Playwright browser + cache game_pitches"`.

---

### Task 11: Bullpen report layout restructure

**Files:**
- Modify: `app/reports/templates/bullpen_report.html`, `app/reports/static/report.css`
- Modify: `app/reports/bullpen_report.py` (charts dict order + freq→donut)
- Modify: `app/reports/bullpen_plots.py` (`movement_uri` reference circles)
- Modify/Use: `app/reports/plots.py` (`_donut`; add a `pitch_freq_donut_uri` or reuse)
- Test: report builds + returns valid data URIs; visual PDF check

**Target page-1 layout:** top row = **Stats by pitch type** (left, focal) + **Pitch frequency donut** (right); middle row = **Location** + **Avg velocity**; bottom row = **Movement** + **Release**.

- [ ] **Step 1: Failing test** — a donut builder exists and returns a data URI, and movement gets reference circles.

```python
def test_pitch_freq_donut_uri():
    from app.reports import plots
    uri = plots.pitch_freq_donut_uri([("Fastball", 5), ("Sinker", 5), ("Cutter", 4)])
    assert uri.startswith("data:image/")
```

- [ ] **Step 2: Verify failure** — no `pitch_freq_donut_uri`.

- [ ] **Step 3: Implement the donut** in `plots.py` reusing the existing `_donut(...)` helper (center label = total). In `bullpen_report.py`, replace `plots.pitch_freq_bar_uri(counts)` with the donut in the `charts` dict.

- [ ] **Step 4: Movement reference circles.** In `bullpen_plots.py` `movement_uri`, add faint per-pitch-type 1σ ellipses (port `_ellipse_xy` / the ellipse loop from `app/dashboards/bullpen/charts.py` `movement_fig`). Draw them under the scatter (`set_axisbelow`), low alpha.

- [ ] **Step 5: Restructure the template.** In `bullpen_report.html`, replace the full-width `.freq-bar` + `grid3`/`grid2` blocks with: a top flex row (stats-table panel left as focal + donut img right), a middle flex row (location + velo imgs), a bottom flex row (movement + release imgs). Adjust `report.css` (`.grid2`/`.grid3`/new classes) and drop `.freq-bar` full-width styling. Shrink chart figsizes if needed to fit the new two-up rows. Keep page 2 (per-pitch table) unchanged.

- [ ] **Step 6: Verify.** Build a bullpen report (e.g. `bullpen_report.build_*` for Bender 2026-05-12); confirm it renders to a valid PDF and eyeball the layout. `pytest tests/ -k bullpen_report -v` → PASS.

- [ ] **Step 7: Commit** — `git commit -am "feat(bullpen-report): restructure layout, donut freq, movement trend circles"`.

---

### Task 12: Bullpen dashboard — "Command" → "Strike %"

**Files:**
- Modify: `app/dashboards/bullpen/tabs/trends.py` (`_METRICS`, default)
- Modify: `app/dashboards/bullpen/charts.py` (`_METRIC_SERIES`, `_METRIC_YTITLE`)
- Modify: `app/data/bullpen.py` (`trend_by_session` adds per-session `strike_pct`)
- Test: bullpen data + trends test

- [ ] **Step 1: Failing test.**

```python
def test_trend_by_session_has_strike_pct():
    import pandas as pd
    from app.data import bullpen as B
    df = pd.DataFrame({
        "date": ["2026-05-12"] * 3, "tagged_pitch_type": ["Fastball"] * 3,
        "plate_loc_side": [0.0, 0.1, 2.0], "plate_loc_height": [2.5, 2.6, 2.5],
    })
    rows = B.trend_by_session(df)
    assert "strike_pct" in rows[0]
    assert isinstance(rows[0]["strike_pct"], (int, float))

def test_trends_metric_list_swaps_command_for_strikepct():
    from app.dashboards.bullpen.tabs import trends
    labels = [lbl for _, lbl in trends._METRICS]
    assert "Strike %" in labels and "Command" not in labels
```

- [ ] **Step 2: Verify failure** — no `strike_pct` in trend rows; "Command" still present.

- [ ] **Step 3: Implement data.** In `trend_by_session`, per `(date, pitch_type)` group compute strike% with the **existing zone-based rule** (reuse `strike_pct(sub)` or inline the `_SZ`/`_EDGE` `between` test on `plate_loc_side`/`plate_loc_height`); add `"strike_pct"` to `cols` and the emitted row dict.

- [ ] **Step 4: Implement UI.** `trends.py`: `_METRICS` → replace `("command","Command")` with `("strikepct","Strike %")`; fix the default `value` if it was `"command"`. `charts.py`: replace the `command` entries in `_METRIC_SERIES` with `"strikepct": [("strike_pct","Strike %", None, False)]` and `_METRIC_YTITLE["strikepct"] = "%"`; drop the `command` keys. `loc_spread` may remain computed but unused.

- [ ] **Step 5: Run** — `pytest tests/ -k "bullpen and (trend or strike or metric)" -v` → PASS. Manual: Development Trends radio shows Strike % and plots per-session values.

- [ ] **Step 6: Commit** — `git commit -am "feat(bullpen): replace Command metric with Strike %"`.

---

## Final verification (after all tasks)

- [ ] Full suite green: `PYTHONIOENCODING=utf-8 pytest tests/ -q` (foreground, `timeout=600000`; `test_precalc` validated per-module per the repo convention).
- [ ] Live smoke as a logged-in coach: all six dashboards render; date range shrinks each player dropdown and updates the sidebar KPIs; Session Tables loads; pitching in-play hovers show outcomes; bullpen report new layout; bullpen trends Strike %.
- [ ] Do NOT push/merge — hand back to the user for review.

## Self-review notes

- Spec coverage: Items 1–10 map to Tasks 1–12 (Item 1 → Tasks 1+2; Items 2/9 + "all six" → Tasks 3+4+5; Items 3,4,5 → Tasks 6,7,8; Item 6 → Task 9; Item 7 → Task 10; Item 8 → Task 11; Item 10 → Task 12).
- Player-list-by-date-range spans Tasks 3/4/5 (all six dashboards) per the user decision.
- Bullpen strike% is zone-based (Task 12, Global Constraints) — consistent with the report header/sidebar KPI.
- Swing hover carries no averages (Task 7) per the user decision.
