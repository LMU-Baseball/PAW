# Pitcher One-Pager Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current detailed pitcher report with a single-page report matching the coaches' preferred layout, generated natively from the warehouse, with matplotlib charts for speed.

**Architecture:** New pure metric transforms in `app/data/pitching.py` compute the report's tables from `fact_tm_game_pitch`. A goals config in `app/reports/report_goals.py` adds benchmark targets + conditional highlighting. `app/reports/plots.py` renders the three plots with matplotlib (in-process PNG data URIs, no headless browser). A new Jinja template `pitcher_onepager.html` + updated `report.css` lay it out on one Letter page. The existing assembler (`pitcher_postgame.py`), Playwright PDF engine, on-disk cache, download route, and picker are reused unchanged except that `_build_html` now renders the new template.

**Tech Stack:** Python, pandas, matplotlib (Agg), Pillow (one-time logo recolor), Jinja2, Playwright (existing). Warehouse: `fact_tm_game_pitch`.

## Global Constraints

- Report content is built from `fact_tm_game_pitch` (modern warehouse). LMU = team_id 78.
- Existing metric-call sets in `app/data/pitching.py` are reused: `_STRIKE_CALLS`, `pitch_type(df)`, `PITCH_TYPE_COL`. Do not redefine them.
- Percentages are NUMERIC (floats rounded to 1 dp), not "33.3%" strings. Counts are ints.
- Hits = `play_result` in {Single, Double, Triple, HomeRun}. Strikeout/Walk from `korbb`. batter_side ∈ {Left, Right}.
- Batters faced / PA-denominators use distinct (`inning`, `pa_of_inning`) pairs — NOT `batters_faced.max()` (that running counter can't be split by batter side).
- LMU-specific metrics (E&A%, Pre2K%, 2K Kill%, Barrel%, Spread) use the provisional definitions in this plan, each in its own function with a docstring stating it is a v1 assumption to be confirmed with coaches. Do not invent different formulas.
- Goal benchmarks (placeholders, confirm later): strike_pct 55, fps_pct 65, ea_pct 70, pre2k_pct 48, twok_kill_pct 55, k_pct 27, bb_pct 6, barrel_pct 7. Lower-is-better: bb_pct, barrel_pct.
- Charts: matplotlib only, `matplotlib.use("Agg")` before pyplot import, return base64 PNG `data:` URIs. Never launch a browser for charts.
- All new transforms must be empty-input safe (no divide-by-zero, no exception on 0 rows) and return the shapes specified here.
- The report must fit ONE US-Letter page. Reuse the existing `@page { size: Letter }` / print-CSS approach.
- Crimson `#9A0021`; Teko display font (inlined as data URIs by the existing assembler). Report cache + route + download delivery are unchanged.
- Revert point for the current report: git tag `report-detailed-v1`.

---

## File Structure

- `app/data/pitching.py` — MODIFY. Add PA helper + metric primitives + `header_stat_line` (Task 1) and the four table assemblers (Task 3). Existing transforms/Plotly builders stay (unused by the new report; kept for revert).
- `app/reports/report_goals.py` — CREATE. Goal benchmarks + `beats_goal` + `apply_goals` (Task 2).
- `app/reports/plots.py` — CREATE. matplotlib `zone_chart_uri`, `movement_map_uri` (Task 4).
- `app/static/reports/lion-white.png` — CREATE (generated from `lion.png`) (Task 5).
- `scripts/make_lion_white.py` — CREATE. One-time recolor script (Task 5).
- `app/reports/templates/pitcher_onepager.html` — CREATE. One-page layout (Task 6).
- `app/reports/static/report.css` — MODIFY. One-page styling (Task 6).
- `app/reports/pitcher_postgame.py` — MODIFY. `_build_html` renders the new template + matplotlib charts + both logos (Task 7).
- `requirements.txt` — MODIFY. Add matplotlib, Pillow (Task 7).
- Tests: `tests/test_report_metrics.py` (Tasks 1, 3), `tests/test_report_goals.py` (Task 2), `tests/test_report_plots.py` (Task 4), plus updates to `tests/test_report_engine.py` (Task 7).

---

### Task 1: Metric primitives + header stat line

**Files:**
- Modify: `app/data/pitching.py`
- Test: `tests/test_report_metrics.py` (create)

**Interfaces:**
- Consumes: existing `_STRIKE_CALLS`, `pitch_type` in the same module.
- Produces: `header_stat_line(df) -> dict` with keys bf, bf_r, bf_l, outs, h, r, bb, so, pitches (all ints). Metric primitives each `(df) -> tuple[float pct, int count]`: `strike_pct`, `fps_pct`, `ea_pct`, `pre2k_pct`, `twok_kill_pct`, `k_pct`, `bb_pct`, `barrel_pct`. Helper `_pa_count(df) -> int`. Task 3 consumes all of these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_metrics.py`:

```python
"""Transforms feeding the one-page pitcher report. Fixture: game 166, pitcher 1
(live warehouse). Value assertions check invariants/ranges; the LMU-specific
metrics (ea/pre2k/twok_kill/barrel) are provisional so they're only range-checked."""
import pandas as pd
from app.data import pitching as P

GAME_ID, PITCHER_ID = 166, 1


def _df():
    return P.game_pitches(GAME_ID, PITCHER_ID)


def test_pa_count_matches_distinct_inning_pa():
    df = _df()
    expected = df[["inning", "pa_of_inning"]].drop_duplicates().shape[0]
    assert P._pa_count(df) == expected
    assert P._pa_count(df.iloc[0:0]) == 0


def test_header_stat_line_shape_and_values():
    h = P.header_stat_line(_df())
    assert set(h) == {"bf", "bf_r", "bf_l", "outs", "h", "r", "bb", "so", "pitches"}
    df = _df()
    assert h["pitches"] == len(df)
    assert h["bf_r"] + h["bf_l"] == h["bf"]
    assert h["h"] == int(df["play_result"].isin(
        {"Single", "Double", "Triple", "HomeRun"}).sum())
    assert h["so"] == int((df["korbb"] == "Strikeout").sum())
    assert all(isinstance(v, int) for v in h.values())


def test_header_stat_line_empty_safe():
    h = P.header_stat_line(_df().iloc[0:0])
    assert h == {k: 0 for k in h}


def test_strike_and_fps_pct_consistent():
    df = _df()
    pct, cnt = P.strike_pct(df)
    assert cnt == int(df["pitch_call"].isin(P._STRIKE_CALLS).sum())
    assert 0 <= pct <= 100
    fpct, fcnt = P.fps_pct(df)
    assert 0 <= fpct <= 100 and fcnt >= 0


def test_k_bb_pct_use_pa_denominator():
    df = _df()
    pas = P._pa_count(df)
    kpct, kcnt = P.k_pct(df)
    assert kcnt == int((df["korbb"] == "Strikeout").sum())
    assert kpct == (round(100.0 * kcnt / pas, 1) if pas else 0.0)


def test_provisional_metrics_in_range_and_empty_safe():
    df = _df()
    for fn in (P.ea_pct, P.pre2k_pct, P.twok_kill_pct, P.barrel_pct):
        pct, cnt = fn(df)
        assert 0 <= pct <= 100 and cnt >= 0
        epct, ecnt = fn(df.iloc[0:0])
        assert epct == 0.0 and ecnt == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_report_metrics.py -v`
Expected: FAIL — `AttributeError: module 'app.data.pitching' has no attribute '_pa_count'` (etc.).

- [ ] **Step 3: Implement the primitives**

Add to `app/data/pitching.py` (after the existing `_IN_ZONE_CODES` block / near the other transforms). Keep `from __future__` and existing imports; `numpy as np` and `pandas as pd` are already imported.

```python
_HIT_RESULTS = {"Single", "Double", "Triple", "HomeRun"}


def _pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _pa_count(df: pd.DataFrame) -> int:
    """Plate appearances = distinct (inning, pa_of_inning) among the pitches.

    Split-safe (works on a batter-side subset), unlike batters_faced.max()
    which is a running counter over the whole outing.
    """
    if df.empty:
        return 0
    return int(df[["inning", "pa_of_inning"]].drop_duplicates().shape[0])


def strike_pct(df: pd.DataFrame) -> tuple[float, int]:
    s = int(df["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(df)), s


def fps_pct(df: pd.DataFrame) -> tuple[float, int]:
    fp = df[df["pitch_of_pa"] == 1]
    s = int(fp["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(fp)), s


def k_pct(df: pd.DataFrame) -> tuple[float, int]:
    k = int((df["korbb"] == "Strikeout").sum())
    return _pct(k, _pa_count(df)), k


def bb_pct(df: pd.DataFrame) -> tuple[float, int]:
    bb = int((df["korbb"] == "Walk").sum())
    return _pct(bb, _pa_count(df)), bb


def ea_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Early & Ahead %. PROVISIONAL v1 definition (confirm with coaches):
    share of PAs where the pitcher reached an ahead count (strikes-balls >= 1)
    at any point in the PA. balls/strikes are the recorded count on each pitch.
    """
    if df.empty:
        return 0.0, 0
    ahead = df.groupby(["inning", "pa_of_inning"]).apply(
        lambda p: bool(((p["strikes"] - p["balls"]).max()) >= 1))
    return _pct(int(ahead.sum()), int(ahead.shape[0])), int(ahead.sum())


def pre2k_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Pre-2K strike %. PROVISIONAL v1: strike% on pitches thrown in counts
    with fewer than 2 strikes."""
    sub = df[df["strikes"] < 2]
    s = int(sub["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(sub)), s


def twok_kill_pct(df: pd.DataFrame) -> tuple[float, int]:
    """2K Kill %. PROVISIONAL v1: strikeouts / PAs that reached a 2-strike count."""
    if df.empty:
        return 0.0, 0
    g = df.groupby(["inning", "pa_of_inning"])
    reached = g.apply(lambda p: bool((p["strikes"] >= 2).any()))
    ks = g.apply(lambda p: bool((p["korbb"] == "Strikeout").any()))
    kills = int((reached & ks).sum())
    return _pct(kills, int(reached.sum())), kills


def barrel_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Barrel %. PROVISIONAL v1 (no launch-angle column in the warehouse):
    barrels / balls in play, barrel ~ exit_speed >= 95 and tagged_hit_type in
    {LineDrive, FlyBall}."""
    bip = df[df["pitch_call"] == "InPlay"]
    barrels = int(((bip["exit_speed"] >= 95)
                   & (bip["tagged_hit_type"].isin({"LineDrive", "FlyBall"}))).sum())
    return _pct(barrels, len(bip)), barrels


def header_stat_line(df: pd.DataFrame) -> dict:
    """The header line: batters faced (R/L), outs, hits, runs, BB, SO, pitches."""
    return {
        "bf": _pa_count(df),
        "bf_r": _pa_count(df[df["batter_side"] == "Right"]),
        "bf_l": _pa_count(df[df["batter_side"] == "Left"]),
        "outs": int(df["outs_on_play"].sum()) if len(df) else 0,
        "h": int(df["play_result"].isin(_HIT_RESULTS).sum()) if len(df) else 0,
        "r": int(df["runs_scored"].sum()) if len(df) else 0,
        "bb": int((df["korbb"] == "Walk").sum()) if len(df) else 0,
        "so": int((df["korbb"] == "Strikeout").sum()) if len(df) else 0,
        "pitches": len(df),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_report_metrics.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_report_metrics.py
git commit -m "feat(reports): metric primitives + header stat line for one-pager"
```

---

### Task 2: Goals config + conditional highlight

**Files:**
- Create: `app/reports/report_goals.py`
- Test: `tests/test_report_goals.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `GOALS: dict[str, float]`, `LOWER_IS_BETTER: set[str]`, `beats_goal(key: str, value: float | None) -> bool | None`, `apply_goals(rows: list[dict]) -> list[dict]` (each row must have `key` and `value_pct`; adds `goal` and `beats`). Task 3/6/7 consume `apply_goals`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_goals.py`:

```python
from app.reports.report_goals import GOALS, beats_goal, apply_goals


def test_higher_is_better_beats():
    assert beats_goal("strike_pct", 60.0) is True      # 60 >= 55 goal
    assert beats_goal("strike_pct", 50.0) is False


def test_lower_is_better_beats():
    assert beats_goal("bb_pct", 4.0) is True            # 4 <= 6 goal
    assert beats_goal("bb_pct", 9.0) is False


def test_unknown_key_or_none_value_is_none():
    assert beats_goal("strike_pct", None) is None
    assert beats_goal("no_such_metric", 10.0) is None


def test_apply_goals_adds_goal_and_beats():
    rows = [{"key": "strike_pct", "value_pct": 60.0},
            {"key": "bb_pct", "value_pct": 9.0}]
    out = apply_goals(rows)
    assert out[0]["goal"] == GOALS["strike_pct"] and out[0]["beats"] is True
    assert out[1]["goal"] == GOALS["bb_pct"] and out[1]["beats"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_report_goals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.reports.report_goals'`.

- [ ] **Step 3: Implement**

Create `app/reports/report_goals.py`:

```python
"""Goal benchmarks for the pitcher report + conditional-highlight logic.

PLACEHOLDER numbers seeded from last year's sample report; confirm the real
targets with the coaching staff. Keys match the metric keys produced by
app.data.pitching.
"""
from __future__ import annotations

GOALS: dict[str, float] = {
    "strike_pct": 55.0,
    "fps_pct": 65.0,
    "ea_pct": 70.0,
    "pre2k_pct": 48.0,
    "twok_kill_pct": 55.0,
    "k_pct": 27.0,
    "bb_pct": 6.0,
    "barrel_pct": 7.0,
}

# Metrics where a LOWER value is better (green when value <= goal).
LOWER_IS_BETTER: set[str] = {"bb_pct", "barrel_pct"}


def beats_goal(key: str, value: float | None) -> bool | None:
    """True/False if the value meets its goal; None if no goal or no value."""
    goal = GOALS.get(key)
    if goal is None or value is None:
        return None
    return value <= goal if key in LOWER_IS_BETTER else value >= goal


def apply_goals(rows: list[dict]) -> list[dict]:
    """Add `goal` and `beats` to each metric row (rows have `key`,`value_pct`)."""
    for r in rows:
        r["goal"] = GOALS.get(r["key"])
        r["beats"] = beats_goal(r["key"], r.get("value_pct"))
    return rows
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_report_goals.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/report_goals.py tests/test_report_goals.py
git commit -m "feat(reports): goal benchmarks + conditional highlight for one-pager"
```

---

### Task 3: Table assemblers (process/outcome/usage/movement)

**Files:**
- Modify: `app/data/pitching.py`
- Test: `tests/test_report_metrics.py` (append)

**Interfaces:**
- Consumes: Task 1 primitives + `pitch_type`, `_STRIKE_CALLS`, `_pct`, `_pa_count`.
- Produces:
  - `process_metrics(df) -> list[dict]` rows for Strike%, FPS%, E&A%, Pre2K%, 2K Kill%; each `{metric, key, value_pct, value_count, vrhh, vlhh}`.
  - `outcome_metrics(df) -> list[dict]` rows for K%, BB%, Barrel%; same shape.
  - `pitch_usage_table(df) -> list[dict]` per type `{pitch, strike_pct, usage_pct, twok_usage_pct, vrhh, vlhh}` (usage desc).
  - `movement_summary(df) -> list[dict]` per type `{pitch, velo_avg, velo_max, ivb_avg, ivb_rhh, ivb_lhh, hb_avg, hb_rhh, hb_lhh, spread}` (usage desc). Numeric cells are floats or None.
  Tasks 6/7 consume all four.

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_report_metrics.py`:

```python
def test_process_and_outcome_metric_rows():
    df = _df()
    proc = P.process_metrics(df)
    assert [r["key"] for r in proc] == [
        "strike_pct", "fps_pct", "ea_pct", "pre2k_pct", "twok_kill_pct"]
    for r in proc:
        assert set(r) >= {"metric", "key", "value_pct", "value_count", "vrhh", "vlhh"}
        assert 0 <= r["value_pct"] <= 100
    out = P.outcome_metrics(df)
    assert [r["key"] for r in out] == ["k_pct", "bb_pct", "barrel_pct"]


def test_pitch_usage_table_usage_sums_to_100():
    rows = P.pitch_usage_table(_df())
    assert len(rows) >= 1
    assert abs(sum(r["usage_pct"] for r in rows) - 100.0) < 0.5
    assert rows == sorted(rows, key=lambda r: r["usage_pct"], reverse=True)
    for r in rows:
        assert set(r) >= {"pitch", "strike_pct", "usage_pct", "twok_usage_pct",
                          "vrhh", "vlhh"}


def test_movement_summary_shape():
    rows = P.movement_summary(_df())
    assert len(rows) >= 1
    for r in rows:
        assert set(r) >= {"pitch", "velo_avg", "velo_max", "ivb_avg", "ivb_rhh",
                          "ivb_lhh", "hb_avg", "hb_rhh", "hb_lhh", "spread"}
        assert r["velo_max"] is None or r["velo_avg"] is None or \
            r["velo_max"] >= r["velo_avg"]


def test_table_assemblers_empty_safe():
    empty = _df().iloc[0:0]
    assert P.process_metrics(empty) and P.outcome_metrics(empty)  # rows still present
    assert P.pitch_usage_table(empty) == []
    assert P.movement_summary(empty) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_report_metrics.py -k "process or usage or movement" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'process_metrics'`.

- [ ] **Step 3: Implement**

Add to `app/data/pitching.py` (after Task 1's functions):

```python
def _r1(x) -> float | None:
    """Round to 1 dp, or None if NaN/empty."""
    return None if x is None or pd.isna(x) else round(float(x), 1)


def _metric_rows(df: pd.DataFrame, specs: list[tuple]) -> list[dict]:
    rhh = df[df["batter_side"] == "Right"]
    lhh = df[df["batter_side"] == "Left"]
    rows = []
    for label, key, fn in specs:
        pct, cnt = fn(df)
        rows.append({
            "metric": label, "key": key,
            "value_pct": pct, "value_count": cnt,
            "vrhh": fn(rhh)[0], "vlhh": fn(lhh)[0],
        })
    return rows


def process_metrics(df: pd.DataFrame) -> list[dict]:
    return _metric_rows(df, [
        ("Strike%", "strike_pct", strike_pct),
        ("FPS%", "fps_pct", fps_pct),
        ("E&A%", "ea_pct", ea_pct),
        ("Pre2K%", "pre2k_pct", pre2k_pct),
        ("2K Kill%", "twok_kill_pct", twok_kill_pct),
    ])


def outcome_metrics(df: pd.DataFrame) -> list[dict]:
    return _metric_rows(df, [
        ("K%", "k_pct", k_pct),
        ("BB%", "bb_pct", bb_pct),
        ("Barrel%", "barrel_pct", barrel_pct),
    ])


def pitch_usage_table(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    n_r = len(d[d["batter_side"] == "Right"]) or 1
    n_l = len(d[d["batter_side"] == "Left"]) or 1
    n_2k = len(d[d["strikes"] == 2]) or 1
    rows = []
    for pt, sub in d.groupby("_pt"):
        rows.append({
            "pitch": pt,
            "strike_pct": _pct(int(sub["pitch_call"].isin(_STRIKE_CALLS).sum()), len(sub)),
            "usage_pct": _pct(len(sub), n),
            # PROVISIONAL: share of the pitcher's 2-strike-count pitches that
            # were this pitch type.
            "twok_usage_pct": _pct(len(sub[sub["strikes"] == 2]), n_2k),
            "vrhh": _pct(len(sub[sub["batter_side"] == "Right"]), n_r),
            "vlhh": _pct(len(sub[sub["batter_side"] == "Left"]), n_l),
            "_count": len(sub),
        })
    rows.sort(key=lambda r: r["_count"], reverse=True)
    for r in rows:
        del r["_count"]
    return rows


def movement_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    d = df.assign(_pt=pitch_type(df))
    rows = []
    for pt, sub in d.groupby("_pt"):
        rhh = sub[sub["batter_side"] == "Right"]
        lhh = sub[sub["batter_side"] == "Left"]
        # PROVISIONAL "Spread": std dev of total break magnitude (movement
        # consistency), in inches.
        mag = np.sqrt(sub["induced_vert_break"] ** 2 + sub["horz_break"] ** 2)
        spread = float(mag.std(ddof=0)) if len(sub) > 1 else 0.0
        rows.append({
            "pitch": pt,
            "velo_avg": _r1(sub["rel_speed"].mean()),
            "velo_max": _r1(sub["rel_speed"].max()),
            "ivb_avg": _r1(sub["induced_vert_break"].mean()),
            "ivb_rhh": _r1(rhh["induced_vert_break"].mean()) if len(rhh) else None,
            "ivb_lhh": _r1(lhh["induced_vert_break"].mean()) if len(lhh) else None,
            "hb_avg": _r1(sub["horz_break"].mean()),
            "hb_rhh": _r1(rhh["horz_break"].mean()) if len(rhh) else None,
            "hb_lhh": _r1(lhh["horz_break"].mean()) if len(lhh) else None,
            "spread": _r1(spread),
            "_count": len(sub),
        })
    rows.sort(key=lambda r: r["_count"], reverse=True)
    for r in rows:
        del r["_count"]
    return rows
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_report_metrics.py -v`
Expected: PASS (all, including the appended tests).

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_report_metrics.py
git commit -m "feat(reports): process/outcome/usage/movement table transforms"
```

---

### Task 4: matplotlib plots

**Files:**
- Create: `app/reports/plots.py`
- Test: `tests/test_report_plots.py` (create)

**Interfaces:**
- Consumes: `app.data.pitching.pitch_type`.
- Produces: `zone_chart_uri(df, batter_side: str, title: str) -> str` and `movement_map_uri(df, title: str = "Movement Map") -> str`, each a `data:image/png;base64,...` string. Both empty-input safe. Task 7 consumes them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_plots.py`:

```python
import base64
from app.data import pitching as P
from app.reports import plots


def _df():
    return P.game_pitches(166, 1)


def _is_png_uri(uri):
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_zone_chart_returns_png():
    _is_png_uri(plots.zone_chart_uri(_df(), "Right", "vRHH Zone"))


def test_movement_map_returns_png():
    _is_png_uri(plots.movement_map_uri(_df()))


def test_plots_empty_input_safe():
    empty = _df().iloc[0:0]
    _is_png_uri(plots.zone_chart_uri(empty, "Left", "vLHH Zone"))
    _is_png_uri(plots.movement_map_uri(empty))
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_report_plots.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.reports.plots'`.

- [ ] **Step 3: Implement**

Create `app/reports/plots.py`:

```python
"""matplotlib plot builders for the pitcher one-pager (static PNG data URIs).

In-process rendering (Agg) — no headless browser, unlike the Plotly/kaleido
path. Each builder returns a self-contained base64 PNG data: URI.
"""
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse

from app.data.pitching import pitch_type

# Strike zone (approx, feet)
_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)
_PALETTE = ["#9A0021", "#2864a8", "#2e8b57", "#e08a1e", "#6a4c93",
            "#00897b", "#c2185b", "#555555"]


def _color_map(pitch_types) -> dict:
    uniq = sorted(set(pitch_types))
    return {pt: _PALETTE[i % len(_PALETTE)] for i, pt in enumerate(uniq)}


def _fig_to_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _draw_zone(ax) -> None:
    x0, x1, y0, y1 = _SZ["x0"], _SZ["x1"], _SZ["y0"], _SZ["y1"]
    ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                               edgecolor="black", lw=1.5))
    for i in (1, 2):  # 3x3 grid
        ax.plot([x0 + (x1 - x0) * i / 3] * 2, [y0, y1], color="#bbb", lw=0.8)
        ax.plot([x0, x1], [y0 + (y1 - y0) * i / 3] * 2, color="#bbb", lw=0.8)
    # home plate outline below the zone
    ax.plot([-0.7, 0.7, 0.7, 0, -0.7, -0.7],
            [0.2, 0.2, 0.5, 0.75, 0.5, 0.2], color="#888", lw=1)


def zone_chart_uri(df, batter_side: str, title: str) -> str:
    d = df[df["batter_side"] == batter_side].dropna(
        subset=["plate_loc_side", "plate_loc_height"]).copy()
    fig, ax = plt.subplots(figsize=(3.1, 3.5))
    _draw_zone(ax)
    if not d.empty:
        d["_pt"] = pitch_type(d)
        cmap = _color_map(d["_pt"])
        for pt, sub in d.groupby("_pt"):
            ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"],
                       s=28, color=cmap[pt], edgecolor="white", linewidth=0.4,
                       label=pt, zorder=3)
        ax.legend(fontsize=6, loc="upper right", framealpha=0.7)
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def _add_ellipse(ax, xs, ys, color) -> None:
    if len(xs) < 3:
        return
    cov = np.cov(xs, ys)
    if not np.all(np.isfinite(cov)):
        return
    vals, vecs = np.linalg.eigh(cov)
    order = vals.argsort()[::-1]
    vals, vecs = vals[order], vecs[:, order]
    angle = np.degrees(np.arctan2(*vecs[:, 0][::-1]))
    w, h = 2 * np.sqrt(np.maximum(vals, 0))  # 1 sigma
    e = Ellipse((np.mean(xs), np.mean(ys)), width=w, height=h, angle=angle,
                facecolor=color, alpha=0.15, edgecolor=color, lw=1)
    ax.add_patch(e)


def movement_map_uri(df, title: str = "Movement Map") -> str:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    ax.axhline(0, color="#ccc", lw=0.8)
    ax.axvline(0, color="#ccc", lw=0.8)
    if not d.empty:
        d["_pt"] = pitch_type(d)
        cmap = _color_map(d["_pt"])
        for pt, sub in d.groupby("_pt"):
            ax.scatter(sub["horz_break"], sub["induced_vert_break"],
                       s=24, color=cmap[pt], edgecolor="white", linewidth=0.3,
                       label=pt, zorder=3)
            _add_ellipse(ax, sub["horz_break"].to_numpy(),
                         sub["induced_vert_break"].to_numpy(), cmap[pt])
        ax.legend(fontsize=6, loc="upper right", framealpha=0.7)
    ax.set_xlim(-25, 25)
    ax.set_ylim(-25, 25)
    ax.set_aspect("equal")
    ax.set_xlabel("HB (in)", fontsize=8)
    ax.set_ylabel("IVB (in)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_report_plots.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/plots.py tests/test_report_plots.py
git commit -m "feat(reports): matplotlib zone + movement-map plots"
```

---

### Task 5: Lion logo — white on transparent

**Files:**
- Create: `scripts/make_lion_white.py`
- Create: `app/static/reports/lion-white.png` (generated, committed)

**Interfaces:**
- Consumes: `app/static/reports/lion.png` (crimson-on-white source, 1000×1000 RGBA, already in repo).
- Produces: `app/static/reports/lion-white.png` — the lion silhouette in white with a transparent background, for the crimson header. Task 7 references it.

- [ ] **Step 1: Write the generation script**

Create `scripts/make_lion_white.py`:

```python
"""Recolor the crimson-on-white lion into white-on-transparent for the crimson
header band. Run once: python scripts/make_lion_white.py"""
from pathlib import Path

from PIL import Image

SRC = Path("app/static/reports/lion.png")
DST = Path("app/static/reports/lion-white.png")


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            # Near-white background -> transparent; everything else -> white,
            # keeping the original alpha as the shape mask.
            if r > 235 and g > 235 and b > 235:
                px[x, y] = (255, 255, 255, 0)
            else:
                px[x, y] = (255, 255, 255, a)
    im.save(DST)
    print(f"wrote {DST} ({im.size})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

Run: `python scripts/make_lion_white.py`
Expected: prints `wrote app/static/reports/lion-white.png (1000, 1000)`.

- [ ] **Step 3: Verify the output**

Run:
```bash
python -c "from PIL import Image; im=Image.open('app/static/reports/lion-white.png').convert('RGBA'); px=im.load(); print('mode', im.mode, 'size', im.size); print('corner alpha', px[0,0][3]); import numpy as np; a=np.array(im); opaque=a[a[:,:,3]>0]; print('opaque px are white:', bool((opaque[:,:3]>240).all()))"
```
Expected: `corner alpha 0` (transparent background) and `opaque px are white: True`.

- [ ] **Step 4: Commit**

```bash
git add scripts/make_lion_white.py app/static/reports/lion-white.png app/static/reports/lion.png
git commit -m "feat(reports): white-on-transparent lion logo for report header"
```

Note: `*.png` is gitignored globally, so `git add` these paths explicitly (they are intentional committed assets, like the existing `app/static/reports/lmu.png`). If the add is refused, use `git add -f`.

---

### Task 6: One-page template + CSS

**Files:**
- Create: `app/reports/templates/pitcher_onepager.html`
- Modify: `app/reports/static/report.css`
- Test: covered by Task 7's render test (the template needs the assembled context; no standalone test here).

**Interfaces:**
- Consumes (Jinja context, provided by Task 7): `pitcher` (str), `hand` (str "RHP"/"LHP"), `context` (dict: game_date, away_team, home_team, game_type, lmu_is_home), `line` (header_stat_line dict), `process` (rows w/ goal+beats), `outcome` (rows w/ goal+beats), `usage` (pitch_usage_table rows), `movement` (movement_summary rows), `charts` (dict: zone_rhh, movement, zone_lhh — data URIs), `css` (str), `assets` (dict: lmu_png, lion_png — data URIs).
- Produces: a one-page HTML document string.

- [ ] **Step 1: Create the template**

Create `app/reports/templates/pitcher_onepager.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><style>{{ css }}</style></head>
<body>
<div class="pg">

  <div class="hdr">
    <img class="hdr-lmu" src="{{ assets.lmu_png }}" alt="LMU">
    <div class="hdr-id">
      <div class="hdr-name">{{ pitcher }} ({{ hand }})</div>
      <div class="hdr-game">
        {{ context.game_date }} &nbsp;|&nbsp; vs {{ context.away_team if context.lmu_is_home else context.home_team }}
        {% if context.game_type %} &nbsp;|&nbsp; {{ context.game_type }}{% endif %}
      </div>
    </div>
    <div class="hdr-line">
      <span><b>{{ line.bf }}</b> ({{ line.bf_r }}/{{ line.bf_l }})<i>BF (R/L)</i></span>
      <span><b>{{ line.outs }}</b><i>OUTS</i></span>
      <span><b>{{ line.h }}</b><i>H</i></span>
      <span><b>{{ line.r }}</b><i>R</i></span>
      <span><b>{{ line.bb }}</b><i>BB</i></span>
      <span><b>{{ line.so }}</b><i>SO</i></span>
      <span><b>{{ line.pitches }}</b><i>PITCHES</i></span>
    </div>
    <img class="hdr-lion" src="{{ assets.lion_png }}" alt="">
  </div>

  <div class="grid2">
    {% macro metric_table(title, rows) %}
    <div class="panel">
      <div class="panel-t">{{ title }}</div>
      <table>
        <tr><th>Metric</th><th>Value</th><th>Goal</th><th>vRHH</th><th>vLHH</th></tr>
        {% for r in rows %}
        <tr>
          <td class="l">{{ r.metric }}</td>
          <td><span class="chip {{ 'good' if r.beats else ('bad' if r.beats is false else '') }}">{{ r.value_pct }}% ({{ r.value_count }})</span></td>
          <td>{{ (r.goal|round(0)|int ~ '%') if r.goal is not none else '—' }}</td>
          <td>{{ r.vrhh }}%</td><td>{{ r.vlhh }}%</td>
        </tr>
        {% endfor %}
      </table>
    </div>
    {% endmacro %}
    {{ metric_table("Process Metrics", process) }}
    {{ metric_table("Outcome Metrics", outcome) }}
  </div>

  <div class="grid2">
    <div class="panel">
      <div class="panel-t">Pitch Usage</div>
      <table>
        <tr><th class="l">Pitch Type</th><th>Strike%</th><th>Usage</th><th>2K Usage</th><th>vRHH</th><th>vLHH</th></tr>
        {% for r in usage %}
        <tr><td class="l">{{ r.pitch }}</td><td>{{ r.strike_pct }}%</td><td>{{ r.usage_pct }}%</td>
            <td>{{ r.twok_usage_pct }}%</td><td>{{ r.vrhh }}%</td><td>{{ r.vlhh }}%</td></tr>
        {% endfor %}
      </table>
    </div>
    <div class="panel">
      <div class="panel-t">Movement Summary</div>
      <table>
        <tr><th class="l">Pitch</th><th>Velo</th><th>Vert Break</th><th>Horiz Break</th><th>Spread</th></tr>
        {% for r in movement %}
        <tr><td class="l">{{ r.pitch }}</td>
            <td>{{ r.velo_avg if r.velo_avg is not none else '—' }} ({{ r.velo_max if r.velo_max is not none else '—' }})</td>
            <td>{{ r.ivb_avg if r.ivb_avg is not none else '—' }} ({{ r.ivb_rhh if r.ivb_rhh is not none else '—' }}/{{ r.ivb_lhh if r.ivb_lhh is not none else '—' }})</td>
            <td>{{ r.hb_avg if r.hb_avg is not none else '—' }} ({{ r.hb_rhh if r.hb_rhh is not none else '—' }}/{{ r.hb_lhh if r.hb_lhh is not none else '—' }})</td>
            <td>{{ r.spread if r.spread is not none else '—' }}</td></tr>
        {% endfor %}
      </table>
    </div>
  </div>

  <div class="grid3">
    <div class="panel plot"><img src="{{ charts.zone_rhh }}" alt="vRHH Zone"></div>
    <div class="panel plot"><img src="{{ charts.movement }}" alt="Movement Map"></div>
    <div class="panel plot"><img src="{{ charts.zone_lhh }}" alt="vLHH Zone"></div>
  </div>

</div>
</body></html>
```

- [ ] **Step 2: Replace `app/reports/static/report.css`**

Replace the entire contents of `app/reports/static/report.css` with:

```css
@font-face { font-family: 'Teko'; src: url('Teko-Regular.ttf'); font-weight: 400; }
@font-face { font-family: 'Teko'; src: url('Teko-Bold.ttf'); font-weight: 700; }
@page { size: Letter; margin: 0.4in; }
* { box-sizing: border-box; }
body { font-family: 'Teko', Arial, sans-serif; color: #111; margin: 0; }
.pg { width: 100%; }

.hdr { display: flex; align-items: center; gap: 14px; background: #9A0021;
       color: #fff; border-radius: 8px; padding: 10px 16px; }
.hdr-lmu { height: 54px; }
.hdr-lion { height: 54px; margin-left: 8px; }
.hdr-id { min-width: 190px; }
.hdr-name { font-size: 26px; font-weight: 700; line-height: 1; }
.hdr-game { font-size: 14px; opacity: .9; margin-top: 2px; }
.hdr-line { display: flex; gap: 16px; margin-left: auto; }
.hdr-line span { display: flex; flex-direction: column; align-items: center; line-height: 1.1; }
.hdr-line b { font-size: 22px; }
.hdr-line i { font-size: 10px; font-style: normal; opacity: .85; letter-spacing: .5px; }

.grid2 { display: flex; gap: 12px; margin-top: 12px; }
.grid2 > .panel { flex: 1; }
.grid3 { display: flex; gap: 12px; margin-top: 12px; }
.grid3 > .panel { flex: 1; }

.panel { border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }
.panel-t { background: #f2f2f2; color: #9A0021; font-weight: 700; font-size: 16px;
           padding: 5px 10px; border-bottom: 1px solid #ddd; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #eee; padding: 4px 8px; text-align: center; }
th { background: #fafafa; color: #444; font-weight: 700; font-size: 11px;
     letter-spacing: .3px; }
td.l, th.l { text-align: left; }
.chip { display: inline-block; padding: 1px 7px; border-radius: 10px;
        background: #eef2f7; font-weight: 700; }
.chip.good { background: #d8f0dd; color: #1b7a34; }
.chip.bad { background: #fbe3e3; color: #a3271f; }
.plot { display: flex; align-items: center; justify-content: center; padding: 4px; }
.plot img { width: 100%; height: auto; }
```

- [ ] **Step 3: Verify template parses (no render yet)**

Run:
```bash
python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/reports/templates')).get_template('pitcher_onepager.html'); print('template parses OK')"
```
Expected: `template parses OK` (a syntax error would raise here).

- [ ] **Step 4: Commit**

```bash
git add app/reports/templates/pitcher_onepager.html app/reports/static/report.css
git commit -m "feat(reports): one-page report template + CSS"
```

---

### Task 7: Assembler wiring + requirements + smoke tests

**Files:**
- Modify: `app/reports/pitcher_postgame.py`
- Modify: `requirements.txt`
- Modify: `tests/test_report_engine.py`

**Interfaces:**
- Consumes: Tasks 1–6 (`P.header_stat_line`, `P.process_metrics`, `P.outcome_metrics`, `P.pitch_usage_table`, `P.movement_summary`; `report_goals.apply_goals`; `plots.zone_chart_uri`/`movement_map_uri`; `pitcher_onepager.html`; `lion-white.png`).
- Produces: `_build_html(game_id, pitcher_id)` renders the one-pager; `build_pitcher_postgame` unchanged (still cached). Determines handedness and the vs-opponent label.

- [ ] **Step 1: Update the smoke/regression tests**

In `tests/test_report_engine.py`, replace the body of `test_build_html_splits_usage_renders_records` (the old report's DataFrame-iteration guard is obsolete) with a one-pager content check, and keep `test_build_pitcher_postgame_smoke` / `test_build_raises_on_empty` as-is. Replace that one test function with:

```python
def test_build_html_renders_onepager_sections():
    from app.reports.pitcher_postgame import _build_html
    html = _build_html(166, 1)
    for token in ("Process Metrics", "Outcome Metrics", "Pitch Usage",
                  "Movement Summary", "vRHH Zone", "vLHH Zone",
                  "data:image/png;base64,"):
        assert token in html
    # both logos embedded as data URIs, no built-in-method leakage
    assert html.count("data:image/png;base64,") >= 3  # 3 charts (+ logos)
    assert "built-in method" not in html
```

If other tests in that file (e.g. `_render_template`, `test_template_renders_with_empty_sections`) reference the OLD template/sections and now fail, update them to target the new template context or remove the obsolete ones — the new template is the source of truth. Report any such removals in your task report.

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_report_engine.py::test_build_html_renders_onepager_sections -v`
Expected: FAIL — `_build_html` still renders the old template (tokens like "vRHH Zone" absent).

- [ ] **Step 3: Rewrite `_build_html` and `build_pitcher_postgame` context**

In `app/reports/pitcher_postgame.py`, update imports and `_build_html`. Change the imports block:

```python
from app.data import pitching as P
from app.reports.charts import fig_to_data_uri, rendering_session  # still used? see note
from app.reports.pdf import html_to_pdf
from app.reports import plots
from app.reports.report_goals import apply_goals
```

Note: the one-pager no longer uses Plotly/kaleido, so `fig_to_data_uri`/`rendering_session` are no longer needed by `_build_html`. Remove those two names from the import (leave `charts.py` in place for revert). Final import line:

```python
from app.data import pitching as P
from app.reports.pdf import html_to_pdf
from app.reports import plots
from app.reports.report_goals import apply_goals
```

Replace the whole `_build_html` function with:

```python
def _build_html(game_id: int, pitcher_id: int) -> str:
    """Render the one-page pitcher report to an HTML string (no PDF step)."""
    df = P.game_pitches(game_id, pitcher_id)
    if df.empty:
        raise ReportDataError(f"No pitches for game_id={game_id}, pitcher_id={pitcher_id}")

    context = P.game_context(game_id)
    # Handedness from the pitcher's throwing side; fall back to RHP.
    hand = "RHP"
    if "pitcher_throws" in df.columns:
        side = str(df["pitcher_throws"].dropna().iloc[0]) if df["pitcher_throws"].notna().any() else ""
        hand = "LHP" if side.lower().startswith("l") else "RHP"

    charts = {
        "zone_rhh": plots.zone_chart_uri(df, "Right", "vRHH Zone"),
        "movement": plots.movement_map_uri(df, "Movement Map"),
        "zone_lhh": plots.zone_chart_uri(df, "Left", "vLHH Zone"),
    }

    css = _inline_fonts((_STATIC / "report.css").read_text(encoding="utf-8"))
    assets = {
        "lmu_png": _data_uri(_ASSETS_DIR / "lmu.png", "image/png"),
        "lion_png": _data_uri(_ASSETS_DIR / "lion-white.png", "image/png"),
    }

    return _env.get_template("pitcher_onepager.html").render(
        pitcher=P.pitcher_name(pitcher_id),
        hand=hand,
        context=context,
        line=P.header_stat_line(df),
        process=apply_goals(P.process_metrics(df)),
        outcome=apply_goals(P.outcome_metrics(df)),
        usage=P.pitch_usage_table(df),
        movement=P.movement_summary(df),
        charts=charts,
        css=css,
        assets=assets,
    )
```

Note: `pitcher_throws` may not exist in the warehouse; the `if "pitcher_throws" in df.columns` guard keeps it safe (defaults RHP). `build_pitcher_postgame` is unchanged.

- [ ] **Step 4: Add matplotlib + Pillow to requirements**

In `requirements.txt`, add (alphabetical or at the end):

```
matplotlib
Pillow
```

- [ ] **Step 5: Run the report-engine tests**

Run: `python -m pytest tests/test_report_engine.py -v`
Expected: PASS — the new one-pager render test passes; `test_build_pitcher_postgame_smoke` builds a real PDF (now matplotlib-based) and `test_build_raises_on_empty` still raises. Note: `test_build_pitcher_postgame_smoke` reads from the report cache if a prior build cached game 166/1 — if it does not exercise a fresh build, that's expected (cache behavior is covered by `tests/test_report_cache.py`).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. New tests added across tasks; no regressions. Report the final count.

- [ ] **Step 7: Verify live**

Run `python run.py` (use `PYTHONIOENCODING=utf-8 python run.py` if the console errors on the arrow char). Log in as coach (`coach@lmu.edu`/`paw2026`), open `/reports/pitching`, pick a game, download a report. Confirm: one page; crimson header with LMU wordmark (left) + lion (right) + stat line; Process/Outcome/Usage/Movement tables; three plots (vRHH Zone, Movement Map, vLHH Zone); build in a few seconds; instant on re-download.

- [ ] **Step 8: Commit**

```bash
git add app/reports/pitcher_postgame.py requirements.txt tests/test_report_engine.py
git commit -m "feat(reports): assemble one-page report (matplotlib charts, both logos)"
```

---

## Self-Review

**1. Spec coverage:**
- One-page layout (header + 4 tables + 3 plots) → Task 6 template + Task 7 wiring. ✓
- Header stat line (BF R/L, OUTS, H, R, BB, SO, PITCHES) → Task 1 `header_stat_line`. ✓
- Process/Outcome metrics w/ Value(count)/Goal/vRHH/vLHH + conditional highlight → Tasks 1,2,3,6. ✓
- Pitch Usage (Strike%/Usage/2K Usage/vRHH/vLHH) + Movement Summary (Velo/Vert/Horiz/Spread) → Task 3, Task 6. ✓
- LMU-specific provisional metrics flagged in docstrings → Task 1 (ea/pre2k/twok_kill/barrel), Task 3 (twok_usage, spread). ✓
- Goals seeded from sample, editable, lower-is-better handled → Task 2. ✓
- matplotlib charts (zone ×2, movement map w/ ellipses), no browser → Task 4. ✓
- Lion logo white-on-transparent → Task 5. ✓
- Replace current report, keep engine/cache/route → Task 7 (`_build_html` only). ✓
- matplotlib dependency → Task 7 requirements. ✓
- Revert point (tag report-detailed-v1) → noted in constraints. ✓

**2. Placeholder scan:** No TBD/TODO. Provisional metric formulas are complete, deterministic code with docstrings (intended per spec's build-now-refine-later). ✓

**3. Type consistency:** Metric primitives return `(float, int)`; `_metric_rows` reads `fn(df)` → matches. Row dict keys used in Task 6 template (`metric,key,value_pct,value_count,goal,beats,vrhh,vlhh`; usage `pitch,strike_pct,usage_pct,twok_usage_pct,vrhh,vlhh`; movement `pitch,velo_avg,velo_max,ivb_avg,ivb_rhh,ivb_lhh,hb_avg,hb_rhh,hb_lhh,spread`) match Task 1/3 outputs and Task 2 `apply_goals` additions. Chart keys `zone_rhh/movement/zone_lhh` match Task 6/7. Asset keys `lmu_png/lion_png` match. ✓
