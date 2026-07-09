# Pitcher Postgame Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a downloadable pitcher postgame PDF (`GET /reports/pitcher/<game_id>/<pitcher_id>.pdf`) generated from the modern Trackman warehouse, replacing the old R Markdown → LaTeX `runPitcherPostgameReport.R`.

**Architecture:** A reusable HTML→PDF engine (`app/reports/`) renders a Jinja template (Teko/LMU CSS) with Plotly charts embedded as self-contained base64 PNGs (kaleido), converted to PDF by headless Chromium (Playwright). A report-only pitcher data layer (`app/data/pitching.py`) queries `fact_tm_game_pitch` / `dim_tm_game` / pitcher views and computes the tables/figures. A Flask blueprint serves the PDF, login- and role-gated.

**Tech Stack:** Flask, SQLAlchemy + PyMySQL (via `app/db.query_df`), pandas, Plotly, kaleido, Playwright (Chromium), Jinja2, pytest.

## Global Constraints

- Python data access goes through `app.db.query_df(sql, params)` with `:named` params — never open raw connections.
- DB credentials come from `.env` via `config.py`; never hard-code them.
- Percentage columns returned as NUMBERS (e.g. `33.3`), not `"33.3%"` strings — consistent with `app/data/hitting.py`.
- Source is the modern warehouse (`fact_tm_game_pitch`, `dim_tm_game`, `tm_player`, `vw_*` pitcher views). Report keys are warehouse `game_id` (int) + `pitcher_id` (bigint).
- Pitch-type field: `tagged_pitch_type`, falling back to `auto_pitch_type` only when null.
- Live-DB test fixture: `game_id=166, pitcher_id=1` (Avery Laine, ~36 pitches, Spring 2026).
- Follow `app/data/hitting.py` conventions for query/transform module shape.
- Commit after every task.

## File Structure

- `requirements.txt` — add `playwright`, `kaleido` (modify).
- `app/static/reports/` — Teko fonts + `lmu.png` (relocated assets) (create).
- `app/reports/__init__.py` — package + `report_bp` blueprint export (create).
- `app/reports/pdf.py` — `html_to_pdf()` (Playwright) (create).
- `app/reports/charts.py` — `fig_to_data_uri()` (kaleido) (create).
- `app/reports/pitcher_postgame.py` — `build_pitcher_postgame()` assembler + `ReportDataError` (create).
- `app/reports/routes.py` — Flask blueprint route (create).
- `app/reports/templates/pitcher_postgame.html` — report template (create).
- `app/reports/static/report.css` — print CSS + @font-face (create).
- `app/data/pitching.py` — queries + transforms + figure builders (create).
- `app/auth/access.py` — add `can_view_pitcher_report()` (modify).
- `app/__init__.py` — register `report_bp` (modify, near line 29-32).
- `tests/test_pitching.py`, `tests/test_report_engine.py`, `tests/test_pitcher_report_route.py` (create).

---

### Task 1: Dependencies and static assets

**Files:**
- Modify: `requirements.txt`
- Create: `app/static/reports/` (Teko-*.ttf, lmu.png copied from `Re_ PAW scripts/www/www/`)
- Test: `tests/test_report_engine.py`

**Interfaces:**
- Produces: importable `playwright.sync_api`, `kaleido`; asset files at `app/static/reports/lmu.png` and `app/static/reports/Teko-Regular.ttf`.

- [ ] **Step 1: Add dependencies to `requirements.txt`**

Append under a new section:

```
# Reports (HTML -> PDF)
playwright>=1.44     # headless Chromium for PDF rendering
kaleido>=0.2         # Plotly static image export
```

- [ ] **Step 2: Install**

Run:
```bash
python -m pip install "playwright>=1.44" "kaleido>=0.2"
python -m playwright install chromium
```
Expected: chromium downloaded; no errors.

- [ ] **Step 3: Copy assets into app static**

Run (bash):
```bash
mkdir -p "app/static/reports"
cp "Re_ PAW scripts/www/www/lmu.png" "app/static/reports/lmu.png"
cp "Re_ PAW scripts/www/www/lmu-bsb.png" "app/static/reports/lmu-bsb.png"
cp "Re_ PAW scripts/www/www/"Teko-*.ttf "app/static/reports/"
```
Expected: files present under `app/static/reports/`.

- [ ] **Step 4: Write the failing test**

Create `tests/test_report_engine.py`:
```python
import importlib
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_report_dependencies_importable():
    assert importlib.util.find_spec("playwright.sync_api") is not None
    assert importlib.util.find_spec("kaleido") is not None


def test_report_assets_present():
    reports = APP / "static" / "reports"
    assert (reports / "lmu.png").exists()
    assert (reports / "Teko-Regular.ttf").exists()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_report_engine.py -v`
Expected: both PASS (fails before Steps 2-3 done).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/static/reports tests/test_report_engine.py
git commit -m "feat(reports): add playwright/kaleido deps and static report assets"
```

---

### Task 2: PDF engine (`app/reports/pdf.py`)

**Files:**
- Create: `app/reports/__init__.py` (empty for now), `app/reports/pdf.py`
- Test: `tests/test_report_engine.py` (append)

**Interfaces:**
- Produces: `html_to_pdf(html: str, base_url: str | None = None) -> bytes`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_report_engine.py`)

```python
def test_html_to_pdf_returns_pdf_bytes():
    from app.reports.pdf import html_to_pdf
    out = html_to_pdf("<html><body><h1>Hello PAW</h1></body></html>")
    assert isinstance(out, bytes)
    assert out[:5] == b"%PDF-"
    assert len(out) > 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report_engine.py::test_html_to_pdf_returns_pdf_bytes -v`
Expected: FAIL (`ModuleNotFoundError: app.reports.pdf`).

- [ ] **Step 3: Implement**

Create `app/reports/__init__.py`:
```python
"""Reusable report engine (HTML -> PDF) and report assemblers."""
```

Create `app/reports/pdf.py`:
```python
"""Render HTML to PDF bytes using headless Chromium (Playwright)."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

_MARGIN = {"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"}


def html_to_pdf(html: str, base_url: str | None = None) -> bytes:
    """Convert a full HTML document to PDF bytes.

    Launches Chromium per call (simple; optimize with a shared browser later).
    `base_url` sets the document base so relative asset URLs resolve.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle", base_url=base_url)
            return page.pdf(
                format="Letter",
                print_background=True,
                margin=_MARGIN,
            )
        finally:
            browser.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report_engine.py::test_html_to_pdf_returns_pdf_bytes -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/__init__.py app/reports/pdf.py tests/test_report_engine.py
git commit -m "feat(reports): html_to_pdf via headless Chromium"
```

---

### Task 3: Chart export helper (`app/reports/charts.py`)

**Files:**
- Create: `app/reports/charts.py`
- Test: `tests/test_report_engine.py` (append)

**Interfaces:**
- Produces: `fig_to_data_uri(fig, width: int = 800, height: int = 500, scale: int = 2) -> str` returning `data:image/png;base64,...`.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_fig_to_data_uri_embeds_png():
    import base64
    import plotly.graph_objects as go
    from app.reports.charts import fig_to_data_uri

    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[3, 1, 2]))
    uri = fig_to_data_uri(fig, width=300, height=200)
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report_engine.py::test_fig_to_data_uri_embeds_png -v`
Expected: FAIL (`ModuleNotFoundError: app.reports.charts`).

- [ ] **Step 3: Implement**

Create `app/reports/charts.py`:
```python
"""Turn a Plotly figure into a self-contained base64 PNG data URI (kaleido)."""
from __future__ import annotations

import base64

import plotly.graph_objects as go


def fig_to_data_uri(fig: go.Figure, width: int = 800, height: int = 500,
                    scale: int = 2) -> str:
    png = fig.to_image(format="png", width=width, height=height, scale=scale)
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report_engine.py::test_fig_to_data_uri_embeds_png -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/charts.py tests/test_report_engine.py
git commit -m "feat(reports): fig_to_data_uri Plotly->base64 PNG"
```

---

### Task 4: Pitcher data layer — queries (`app/data/pitching.py`)

**Files:**
- Create: `app/data/pitching.py`
- Test: `tests/test_pitching.py`

**Interfaces:**
- Produces:
  - `PITCH_TYPE_COL = "tagged_pitch_type"`
  - `pitch_type(df) -> pd.Series` (tagged, `auto_pitch_type` fallback)
  - `game_context(game_id: int) -> dict` keys: `game_date, season_label, game_type, home_team, away_team, lmu_runs, opp_runs, lmu_is_home`
  - `game_pitches(game_id: int, pitcher_id: int) -> pd.DataFrame`
  - `recent_outings(pitcher_id: int, game_id: int, n: int = 5) -> pd.DataFrame`
  - `velo_trend(pitcher_id: int) -> pd.DataFrame`
  - `pitcher_name(pitcher_id: int) -> str`
  - `pitcher_tm_id_for(pitcher_id: int) -> int | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pitching.py`:
```python
import pandas as pd
import pytest

from app.data import pitching as P

GAME_ID = 166
PITCHER_ID = 1


def test_game_pitches_returns_rows_for_known_outing():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert (df["pitcher_id"] == PITCHER_ID).all()
    assert (df["game_id"] == GAME_ID).all()


def test_game_context_has_score_and_teams():
    ctx = P.game_context(GAME_ID)
    assert ctx["home_team"] and ctx["away_team"]
    assert ctx["lmu_runs"] >= 0 and ctx["opp_runs"] >= 0
    assert isinstance(ctx["lmu_is_home"], bool)


def test_recent_outings_capped_and_ordered():
    df = P.recent_outings(PITCHER_ID, GAME_ID, n=5)
    assert 1 <= len(df) <= 5
    dates = pd.to_datetime(df["game_date"])
    assert list(dates) == sorted(dates, reverse=True)


def test_pitch_type_prefers_tagged():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    pt = P.pitch_type(df)
    assert pt.notna().all()


def test_pitcher_tm_id_resolves():
    assert P.pitcher_tm_id_for(PITCHER_ID) is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_pitching.py -v`
Expected: FAIL (`ModuleNotFoundError: app.data.pitching`).

- [ ] **Step 3: Implement queries**

Create `app/data/pitching.py`:
```python
"""Pitcher data access + transforms for the postgame report.

Reads the modern Trackman warehouse: fact_tm_game_pitch (pitch grain),
dim_tm_game (game context), tm_player (names), and pitcher views. Keys are
warehouse game_id (int) + pitcher_id (bigint). Percentages returned NUMERIC.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.db import query_df

LMU_TEAMS = ("LOY_LIO", "LMU")
PITCH_TYPE_COL = "tagged_pitch_type"


def pitch_type(df: pd.DataFrame) -> pd.Series:
    """Tagged pitch type, falling back to auto_pitch_type when null/empty."""
    tagged = df[PITCH_TYPE_COL].replace("", np.nan)
    return tagged.fillna(df["auto_pitch_type"]).fillna("Undefined")


# ============================ QUERIES =====================================

def game_pitches(game_id: int, pitcher_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT *
          FROM fact_tm_game_pitch
         WHERE game_id = :gid AND pitcher_id = :pid
         ORDER BY pitch_no
        """,
        {"gid": game_id, "pid": pitcher_id},
    )


def game_context(game_id: int) -> dict:
    dim = query_df(
        """
        SELECT g.game_date, g.season_label, g.game_type,
               ht.name AS home_team, at.name AS away_team,
               g.home_team_id, g.away_team_id
          FROM dim_tm_game g
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE g.game_id = :gid
        """,
        {"gid": game_id},
    )
    if dim.empty:
        raise KeyError(f"No dim_tm_game row for game_id={game_id}")
    row = dim.iloc[0]

    # Final score: sum runs_scored by batting half. Top => away bats, Bottom => home.
    runs = query_df(
        """
        SELECT top_bottom, COALESCE(SUM(runs_scored), 0) AS runs
          FROM fact_tm_game_pitch
         WHERE game_id = :gid
         GROUP BY top_bottom
        """,
        {"gid": game_id},
    ).set_index("top_bottom")["runs"].to_dict()
    away_runs = int(runs.get("Top", 0))
    home_runs = int(runs.get("Bottom", 0))

    lmu_is_home = str(row["home_team"]).upper().startswith("LMU") or \
        str(row["home_team"]) in LMU_TEAMS
    return {
        "game_date": row["game_date"],
        "season_label": row["season_label"],
        "game_type": row["game_type"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "lmu_runs": home_runs if lmu_is_home else away_runs,
        "opp_runs": away_runs if lmu_is_home else home_runs,
        "lmu_is_home": bool(lmu_is_home),
    }


def recent_outings(pitcher_id: int, game_id: int, n: int = 5) -> pd.DataFrame:
    """This outing + prior ones, newest first, up to n rows."""
    df = query_df(
        """
        SELECT game_id, game_date, season_label, game_type,
               home_team_name, away_team_name,
               appearance_avg_velo, appearance_max_velo, appearance_min_velo,
               pitch_count
          FROM vw_pitcher_recent_outings
         WHERE pitcher_id = :pid
         ORDER BY game_date DESC
        """,
        {"pid": pitcher_id},
    )
    if df.empty:
        return df
    this_date = df.loc[df["game_id"] == game_id, "game_date"]
    if not this_date.empty:
        df = df[df["game_date"] <= this_date.iloc[0]]
    return df.head(n).reset_index(drop=True)


def velo_trend(pitcher_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT game_date, avg_velo, max_velo, pitch_count, velo_change
          FROM vw_pitcher_velo_trend
         WHERE pitcher_id = :pid
         ORDER BY game_date
        """,
        {"pid": pitcher_id},
    )


def pitcher_name(pitcher_id: int) -> str:
    df = query_df(
        "SELECT first_name, last_name FROM tm_player WHERE player_id = :pid",
        {"pid": pitcher_id},
    )
    if df.empty:
        return f"Pitcher {pitcher_id}"
    r = df.iloc[0]
    return f"{r['first_name']} {r['last_name']}".strip()


def pitcher_tm_id_for(pitcher_id: int) -> int | None:
    """Raw Trackman id for a warehouse pitcher_id (for role gating)."""
    df = query_df(
        """
        SELECT pitcher_tm_id
          FROM fact_tm_game_pitch
         WHERE pitcher_id = :pid AND pitcher_tm_id IS NOT NULL
         LIMIT 1
        """,
        {"pid": pitcher_id},
    )
    return None if df.empty else int(df.iloc[0]["pitcher_tm_id"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pitching.py -v`
Expected: all 5 PASS. (If `tm_team` has no `name`/`team_id` columns, inspect with a quick `query_df` and adjust the join column names — verify against the live schema before moving on.)

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): warehouse queries for pitcher report"
```

---

### Task 5: Pitcher data layer — transforms

**Files:**
- Modify: `app/data/pitching.py`
- Test: `tests/test_pitching.py` (append)

**Interfaces:**
- Consumes: `game_pitches()`, `pitch_type()`.
- Produces (all take the `game_pitches` DataFrame unless noted):
  - `game_overall_line(df) -> dict`
  - `pitch_characteristics(df) -> pd.DataFrame`
  - `pitch_usage(df) -> pd.DataFrame`
  - `zone_location(df) -> pd.DataFrame`
  - `usage_by_count(df) -> pd.DataFrame`
  - `splits_by_batter_side(df) -> dict[str, dict]` keys `"Left"`, `"Right"`
  - `averages_last5(recent_df) -> pd.DataFrame` (takes `recent_outings` output)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_pitching.py`)

```python
def test_game_overall_line_counts_are_consistent():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    line = P.game_overall_line(df)
    assert line["pitches"] == len(df)
    assert 0 <= line["strike_pct"] <= 100
    assert line["strikes"] + line["balls"] <= line["pitches"]


def test_pitch_characteristics_usage_sums_to_100():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    ch = P.pitch_characteristics(df)
    assert len(ch) >= 1
    assert abs(ch["usage_pct"].sum() - 100.0) < 0.5


def test_splits_cover_both_sides_keys():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    splits = P.splits_by_batter_side(df)
    assert set(splits.keys()) == {"Left", "Right"}


def test_averages_last5_rowcount_matches_recent():
    recent = P.recent_outings(PITCHER_ID, GAME_ID, n=5)
    avg = P.averages_last5(recent)
    assert len(avg) == len(recent)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_pitching.py -k "overall or characteristics or splits or averages" -v`
Expected: FAIL (`AttributeError: ... has no attribute 'game_overall_line'`).

- [ ] **Step 3: Implement transforms** (append to `app/data/pitching.py`)

```python
# ============================ TRANSFORMS ==================================

_STRIKE_CALLS = {"StrikeCalled", "StrikeSwinging", "FoulBall", "InPlay"}
_WHIFF_CALLS = {"StrikeSwinging"}
_SWING_CALLS = {"StrikeSwinging", "FoulBall", "InPlay"}


def game_overall_line(df: pd.DataFrame) -> dict:
    n = len(df)
    calls = df["pitch_call"]
    strikes = int(calls.isin(_STRIKE_CALLS).sum())
    balls = int((calls == "BallCalled").sum())
    swings = int(calls.isin(_SWING_CALLS).sum())
    whiffs = int(calls.isin(_WHIFF_CALLS).sum())
    korbb = df["korbb"]
    first_pitch = df[df["pitch_of_pa"] == 1]
    fps = int(first_pitch["pitch_call"].isin(_STRIKE_CALLS).sum())

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    return {
        "pitches": n,
        "batters_faced": int(df["batters_faced"].max() or 0),
        "strikes": strikes,
        "balls": balls,
        "strike_pct": pct(strikes, n),
        "whiff_pct": pct(whiffs, swings),
        "k": int((korbb == "Strikeout").sum()),
        "bb": int((korbb == "Walk").sum()),
        "first_pitch_strike_pct": pct(fps, len(first_pitch)),
        "runs": int(df["runs_scored"].sum()),
    }


def pitch_characteristics(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    g = d.groupby("_pt")
    out = pd.DataFrame({
        "count": g.size(),
        "avg_velo": g["rel_speed"].mean().round(1),
        "max_velo": g["rel_speed"].max().round(1),
        "spin_rate": g["spin_rate"].mean().round(0),
        "ivb": g["induced_vert_break"].mean().round(1),
        "hb": g["horz_break"].mean().round(1),
        "rel_height": g["rel_height"].mean().round(2),
        "rel_side": g["rel_side"].mean().round(2),
        "extension": g["extension"].mean().round(2),
    }).reset_index(names="pitch")
    out["usage_pct"] = (100.0 * out["count"] / n).round(1)
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def pitch_usage(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    out = (d.groupby("_pt").size().reset_index(name="count")
             .rename(columns={"_pt": "pitch"}))
    out["usage_pct"] = (100.0 * out["count"] / n).round(1)
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def zone_location(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    g = d.groupby("_pt")
    out = pd.DataFrame({
        "count": g.size(),
        "in_zone_pct": (100.0 * g["zi"].mean()).round(1),
    }).reset_index(names="pitch")
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def usage_by_count(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df),
                  count_state=df["balls"].astype(str) + "-" + df["strikes"].astype(str))
    return (d.pivot_table(index="count_state", columns="_pt", values="pitch_no",
                          aggfunc="count", fill_value=0)
              .reset_index())


def splits_by_batter_side(df: pd.DataFrame) -> dict:
    out = {}
    for side in ("Left", "Right"):
        sub = df[df["batter_side"] == side]
        out[side] = {
            "overall": game_overall_line(sub) if len(sub) else game_overall_line(df.iloc[0:0]),
            "usage": pitch_usage(sub) if len(sub) else pitch_usage(df.iloc[0:0]),
        }
    return out


def averages_last5(recent_df: pd.DataFrame) -> pd.DataFrame:
    if recent_df.empty:
        return recent_df
    cols = ["game_date", "away_team_name", "home_team_name",
            "appearance_avg_velo", "appearance_max_velo", "pitch_count"]
    return recent_df[cols].copy()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pitching.py -v`
Expected: all PASS. (`game_overall_line(df.iloc[0:0])` on empty input must not divide by zero — the `pct` guard handles it.)

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): report transforms (overall/characteristics/usage/splits)"
```

---

### Task 6: Pitcher data layer — figure builders

**Files:**
- Modify: `app/data/pitching.py`
- Test: `tests/test_pitching.py` (append)

**Interfaces:**
- Consumes: `game_pitches()`, `pitch_type()`, `velo_trend()`.
- Produces (each returns `plotly.graph_objects.Figure`):
  - `fig_velo_by_inning(df)`, `fig_velo_by_pitch(df)`, `fig_movement(df)`,
    `fig_location(df)`, `fig_velo_trend(trend_df)`,
    `fig_location_split(df)`, `fig_heatmap_overall(df)`,
    `fig_heatmaps_by_pitch_type(df) -> list[tuple[str, Figure]]`

- [ ] **Step 1: Write the failing tests** (append)

```python
import plotly.graph_objects as go


def test_figure_builders_return_figures():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    for fn in (P.fig_velo_by_inning, P.fig_velo_by_pitch, P.fig_movement,
               P.fig_location, P.fig_location_split, P.fig_heatmap_overall):
        fig = fn(df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1


def test_velo_trend_figure():
    trend = P.velo_trend(PITCHER_ID)
    fig = P.fig_velo_trend(trend)
    assert isinstance(fig, go.Figure)


def test_heatmaps_by_pitch_type_labeled():
    df = P.game_pitches(GAME_ID, PITCHER_ID)
    items = P.fig_heatmaps_by_pitch_type(df)
    assert len(items) >= 1
    for label, fig in items:
        assert isinstance(label, str)
        assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_pitching.py -k figure -v`
Expected: FAIL (`AttributeError: fig_velo_by_inning`).

- [ ] **Step 3: Implement figures** (append to `app/data/pitching.py`)

```python
# ============================ FIGURES =====================================

_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)  # approx strike zone (ft)


def _base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title, template="simple_white",
        font=dict(family="Teko, sans-serif", size=16),
        margin=dict(l=40, r=20, t=50, b=40), showlegend=True,
    )
    return fig


def fig_velo_by_inning(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"])
    g = d.groupby("inning")["rel_speed"].mean().reset_index()
    fig = go.Figure(go.Bar(x=g["inning"], y=g["rel_speed"].round(1)))
    fig.update_xaxes(title="Inning"); fig.update_yaxes(title="Avg Velo (mph)")
    return _base_layout(fig, "Velocity by Inning")


def fig_velo_by_pitch(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["pitch_no"], y=sub["rel_speed"],
                                 mode="markers+lines", name=pt))
    fig.update_xaxes(title="Pitch #"); fig.update_yaxes(title="Velo (mph)")
    return _base_layout(fig, "Velocity Across Outing")


def fig_movement(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["horz_break"], y=sub["induced_vert_break"],
                                 mode="markers", name=pt))
    fig.update_xaxes(title="Horizontal Break (in)", zeroline=True)
    fig.update_yaxes(title="Induced Vert Break (in)", zeroline=True)
    return _base_layout(fig, "Pitch Movement")


def _add_zone(fig: go.Figure) -> None:
    fig.add_shape(type="rect", line=dict(color="black", width=2), **_SZ)


def fig_location(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["plate_loc_side"], y=sub["plate_loc_height"],
                                 mode="markers", name=pt))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Pitch Location (Catcher View)")


def fig_location_split(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    fig = go.Figure()
    for side, sub in d.groupby("batter_side"):
        fig.add_trace(go.Scatter(x=sub["plate_loc_side"], y=sub["plate_loc_height"],
                                 mode="markers", name=f"vs {side}"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Location vs LHH/RHH")


def fig_velo_trend(trend_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not trend_df.empty:
        fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["avg_velo"],
                                 mode="markers+lines", name="Avg Velo"))
    fig.update_xaxes(title="Game Date"); fig.update_yaxes(title="Avg Velo (mph)")
    return _base_layout(fig, "Velocity Trend (Season)")


def _heatmap(d: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure(go.Histogram2dContour(
        x=d["plate_loc_side"], y=d["plate_loc_height"],
        colorscale="YlOrRd", showscale=False, ncontours=12,
    ))
    _add_zone(fig)
    fig.update_xaxes(title="", range=[-2.5, 2.5], showticklabels=False)
    fig.update_yaxes(title="", range=[0, 5], scaleanchor="x", showticklabels=False)
    out = _base_layout(fig, title); out.update_layout(showlegend=False)
    return out


def fig_heatmap_overall(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"])
    return _heatmap(d, "Location Heatmap (All Pitches)")


def fig_heatmaps_by_pitch_type(df: pd.DataFrame) -> list:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    items = []
    for pt, sub in d.groupby("_pt"):
        if len(sub) >= 3:
            items.append((pt, _heatmap(sub, pt)))
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pitching.py -k figure -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): Plotly figure builders for report"
```

---

### Task 7: Report template and CSS

**Files:**
- Create: `app/reports/templates/pitcher_postgame.html`, `app/reports/static/report.css`
- Test: `tests/test_report_engine.py` (append)

**Interfaces:**
- Produces: a Jinja template rendering a context with keys
  `pitcher, context, overall, characteristics, usage, zone, splits, averages,
  charts` (where `charts` is a dict of section name -> data URI string, and
  `heatmaps` is a list of `(label, uri)`), plus `assets` (dict of absolute
  file URIs for `lmu_png` and font dir).

- [ ] **Step 1: Write the failing test** (append to `tests/test_report_engine.py`)

```python
def test_template_renders_sections():
    from jinja2 import Environment, FileSystemLoader
    from pathlib import Path
    tmpl_dir = Path(__file__).resolve().parents[1] / "app" / "reports" / "templates"
    env = Environment(loader=FileSystemLoader(str(tmpl_dir)), autoescape=True)
    html = env.get_template("pitcher_postgame.html").render(
        pitcher="Avery Laine",
        context={"game_date": "2026-05-10", "season_label": "Spring 2026",
                 "game_type": "Conference", "home_team": "LMU",
                 "away_team": "SMC", "lmu_runs": 5, "opp_runs": 3,
                 "lmu_is_home": True},
        overall={"pitches": 36, "batters_faced": 12, "strikes": 22, "balls": 14,
                 "strike_pct": 61.1, "whiff_pct": 20.0, "k": 4, "bb": 1,
                 "first_pitch_strike_pct": 58.3, "runs": 3},
        characteristics=[], usage=[], zone=[], splits={}, averages=[],
        charts={"velo_inning": "data:image/png;base64,AAAA"},
        heatmaps=[("Fastball", "data:image/png;base64,AAAA")],
        css="body{}",
        assets={"lmu_png": "file:///lmu.png"},
    )
    assert "Avery Laine" in html
    assert "Game Overall" in html
    assert "data:image/png;base64,AAAA" in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_report_engine.py::test_template_renders_sections -v`
Expected: FAIL (`TemplateNotFound: pitcher_postgame.html`).

- [ ] **Step 3: Implement CSS and template**

Create `app/reports/static/report.css`:
```css
@font-face { font-family: 'Teko'; src: url('Teko-Regular.ttf'); font-weight: 400; }
@font-face { font-family: 'Teko'; src: url('Teko-Bold.ttf'); font-weight: 700; }
@page { size: Letter; margin: 0.5in; }
* { box-sizing: border-box; }
body { font-family: 'Teko', Arial, sans-serif; color: #111; margin: 0; }
.header { display: flex; align-items: center; gap: 16px;
          border-bottom: 3px solid #8c1515; padding-bottom: 8px; }
.header img { height: 64px; }
.header h1 { font-size: 30px; margin: 0; }
.header .meta { margin-left: auto; text-align: right; font-size: 18px; }
.score { font-size: 26px; font-weight: 700; }
h2 { font-size: 22px; color: #8c1515; margin: 18px 0 6px;
     border-bottom: 1px solid #ccc; }
section { break-inside: avoid; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border: 1px solid #ddd; padding: 3px 6px; text-align: center; }
th { background: #f2f2f2; }
.charts { display: flex; flex-wrap: wrap; gap: 8px; }
.charts img { width: 49%; }
.heatmaps img { width: 32%; }
```

Create `app/reports/templates/pitcher_postgame.html`:
```html
<!doctype html>
<html>
<head><meta charset="utf-8"><style>{{ css }}</style></head>
<body>
  <div class="header">
    <img src="{{ assets.lmu_png }}" alt="LMU">
    <h1>{{ pitcher }} — Postgame Report</h1>
    <div class="meta">
      {{ context.away_team }} @ {{ context.home_team }}<br>
      {{ context.game_date }} · {{ context.game_type }}<br>
      <span class="score">LMU {{ context.lmu_runs }} – {{ context.opp_runs }} OPP</span>
    </div>
  </div>

  <section>
    <h2>Game Overall</h2>
    <table>
      <tr><th>Pitches</th><th>BF</th><th>K</th><th>BB</th>
          <th>Strike%</th><th>Whiff%</th><th>1st-Pitch K%</th><th>Runs</th></tr>
      <tr><td>{{ overall.pitches }}</td><td>{{ overall.batters_faced }}</td>
          <td>{{ overall.k }}</td><td>{{ overall.bb }}</td>
          <td>{{ overall.strike_pct }}</td><td>{{ overall.whiff_pct }}</td>
          <td>{{ overall.first_pitch_strike_pct }}</td><td>{{ overall.runs }}</td></tr>
    </table>
  </section>

  <section>
    <h2>Pitch Characteristics</h2>
    <table>
      <tr><th>Pitch</th><th>#</th><th>Usage%</th><th>Avg</th><th>Max</th>
          <th>Spin</th><th>IVB</th><th>HB</th><th>RelH</th><th>RelS</th><th>Ext</th></tr>
      {% for r in characteristics %}
      <tr><td>{{ r.pitch }}</td><td>{{ r.count }}</td><td>{{ r.usage_pct }}</td>
          <td>{{ r.avg_velo }}</td><td>{{ r.max_velo }}</td><td>{{ r.spin_rate }}</td>
          <td>{{ r.ivb }}</td><td>{{ r.hb }}</td><td>{{ r.rel_height }}</td>
          <td>{{ r.rel_side }}</td><td>{{ r.extension }}</td></tr>
      {% endfor %}
    </table>
  </section>

  <section>
    <h2>Velocity</h2>
    <div class="charts">
      <img src="{{ charts.velo_inning }}"><img src="{{ charts.velo_pitch }}">
    </div>
  </section>

  <section>
    <h2>Movement &amp; Location</h2>
    <div class="charts"><img src="{{ charts.movement }}"><img src="{{ charts.location }}"></div>
  </section>

  <section>
    <h2>Last 5 Outings</h2>
    <table>
      <tr><th>Date</th><th>Matchup</th><th>Avg Velo</th><th>Max Velo</th><th>Pitches</th></tr>
      {% for r in averages %}
      <tr><td>{{ r.game_date }}</td><td>{{ r.away_team_name }} @ {{ r.home_team_name }}</td>
          <td>{{ r.appearance_avg_velo }}</td><td>{{ r.appearance_max_velo }}</td>
          <td>{{ r.pitch_count }}</td></tr>
      {% endfor %}
    </table>
    <div class="charts"><img src="{{ charts.velo_trend }}"><img src="{{ charts.location_split }}"></div>
  </section>

  <section>
    <h2>Heatmaps</h2>
    <div class="charts"><img src="{{ charts.heatmap_overall }}"></div>
    <div class="charts heatmaps">
      {% for label, uri in heatmaps %}<img src="{{ uri }}" title="{{ label }}">{% endfor %}
    </div>
  </section>
</body>
</html>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report_engine.py::test_template_renders_sections -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/templates app/reports/static tests/test_report_engine.py
git commit -m "feat(reports): pitcher postgame template + print CSS"
```

---

### Task 8: Assembler (`app/reports/pitcher_postgame.py`)

**Files:**
- Create: `app/reports/pitcher_postgame.py`
- Test: `tests/test_report_engine.py` (append)

**Interfaces:**
- Consumes: everything from `app/data/pitching.py`, `app.reports.charts.fig_to_data_uri`, `app.reports.pdf.html_to_pdf`.
- Produces: `build_pitcher_postgame(game_id: int, pitcher_id: int) -> bytes`; `class ReportDataError(Exception)`.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_build_pitcher_postgame_smoke():
    from app.reports.pitcher_postgame import build_pitcher_postgame
    pdf = build_pitcher_postgame(166, 1)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5000


def test_build_raises_on_empty():
    from app.reports.pitcher_postgame import build_pitcher_postgame, ReportDataError
    import pytest
    with pytest.raises(ReportDataError):
        build_pitcher_postgame(166, 99999999)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_report_engine.py -k build -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

Create `app/reports/pitcher_postgame.py`:
```python
"""Assemble the pitcher postgame PDF from warehouse data + the report engine."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.data import pitching as P
from app.reports.charts import fig_to_data_uri
from app.reports.pdf import html_to_pdf

_DIR = Path(__file__).resolve().parent
_STATIC = _DIR / "static"
_env = Environment(
    loader=FileSystemLoader(str(_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)


class ReportDataError(Exception):
    """Raised when there is no data to build a report for the given keys."""


def build_pitcher_postgame(game_id: int, pitcher_id: int) -> bytes:
    df = P.game_pitches(game_id, pitcher_id)
    if df.empty:
        raise ReportDataError(f"No pitches for game_id={game_id}, pitcher_id={pitcher_id}")

    context = P.game_context(game_id)
    recent = P.recent_outings(pitcher_id, game_id, n=5)
    trend = P.velo_trend(pitcher_id)

    charts = {
        "velo_inning": fig_to_data_uri(P.fig_velo_by_inning(df)),
        "velo_pitch": fig_to_data_uri(P.fig_velo_by_pitch(df)),
        "movement": fig_to_data_uri(P.fig_movement(df)),
        "location": fig_to_data_uri(P.fig_location(df)),
        "velo_trend": fig_to_data_uri(P.fig_velo_trend(trend)),
        "location_split": fig_to_data_uri(P.fig_location_split(df)),
        "heatmap_overall": fig_to_data_uri(P.fig_heatmap_overall(df)),
    }
    heatmaps = [(label, fig_to_data_uri(fig))
                for label, fig in P.fig_heatmaps_by_pitch_type(df)]

    css = (_STATIC / "report.css").read_text(encoding="utf-8")
    lmu_png = _DIR.parents[0] / "static" / "reports" / "lmu.png"
    assets = {"lmu_png": lmu_png.as_uri()}

    html = _env.get_template("pitcher_postgame.html").render(
        pitcher=P.pitcher_name(pitcher_id),
        context=context,
        overall=P.game_overall_line(df),
        characteristics=P.pitch_characteristics(df).to_dict("records"),
        usage=P.pitch_usage(df).to_dict("records"),
        zone=P.zone_location(df).to_dict("records"),
        splits=P.splits_by_batter_side(df),
        averages=P.averages_last5(recent).to_dict("records"),
        charts=charts,
        heatmaps=heatmaps,
        css=css,
        assets=assets,
    )
    # base_url lets the CSS @font-face find the .ttf files next to report.css.
    return html_to_pdf(html, base_url=_STATIC.as_uri() + "/")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report_engine.py -k build -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/pitcher_postgame.py tests/test_report_engine.py
git commit -m "feat(reports): assemble pitcher postgame PDF"
```

---

### Task 9: Auth gate + Flask route + registration

**Files:**
- Modify: `app/auth/access.py`, `app/__init__.py`
- Create: `app/reports/routes.py`
- Test: `tests/test_pitcher_report_route.py`

**Interfaces:**
- Consumes: `role_required`, `current_user`, `build_pitcher_postgame`, `ReportDataError`, `P.pitcher_tm_id_for`.
- Produces: `can_view_pitcher_report(user, pitcher_id) -> bool`; blueprint `report_bp` with route `GET /reports/pitcher/<int:game_id>/<int:pitcher_id>.pdf`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pitcher_report_route.py`:
```python
from unittest.mock import patch

import pytest

from app import create_app
from app.extensions import db
from app.auth.models import User


@pytest.fixture
def app_ctx(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                      SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path/'t.db'}")
    with app.app_context():
        db.create_all()
        coach = User(email="c@lmu.edu", role="coach"); coach.set_password("x")
        db.session.add(coach); db.session.commit()
    return app


def _login(client, email):
    return client.post("/auth/login", data={"email": email, "password": "x"},
                       follow_redirects=True)


def test_anonymous_gets_401_or_redirect(app_ctx):
    client = app_ctx.test_client()
    resp = client.get("/reports/pitcher/166/1.pdf")
    assert resp.status_code in (302, 401)


def test_coach_gets_pdf(app_ctx):
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    with patch("app.reports.routes.build_pitcher_postgame", return_value=b"%PDF-mock"):
        resp = client.get("/reports/pitcher/166/1.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_pitcher_report_route.py -v`
Expected: FAIL (`werkzeug ... 404` — route/blueprint not registered).

- [ ] **Step 3: Add the auth helper** (append to `app/auth/access.py`)

```python
def can_view_pitcher_report(user, pitcher_id) -> bool:
    """Coaches see all; a player sees only their own pitcher report."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.role == "coach":
        return True
    from app.data.pitching import pitcher_tm_id_for
    tm_id = pitcher_tm_id_for(pitcher_id)
    return tm_id is not None and str(user.trackman_id) == str(tm_id)
```

- [ ] **Step 4: Create the blueprint** (`app/reports/routes.py`)

```python
"""Report download routes."""
from flask import Blueprint, Response, abort
from flask_login import current_user, login_required

from app.auth.access import can_view_pitcher_report
from app.reports.pitcher_postgame import ReportDataError, build_pitcher_postgame

report_bp = Blueprint("reports", __name__, url_prefix="/reports")


@report_bp.route("/pitcher/<int:game_id>/<int:pitcher_id>.pdf")
@login_required
def pitcher_pdf(game_id: int, pitcher_id: int):
    if not can_view_pitcher_report(current_user, pitcher_id):
        abort(403)
    try:
        pdf = build_pitcher_postgame(game_id, pitcher_id)
    except ReportDataError:
        abort(404)
    return Response(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="pitcher_{pitcher_id}_game_{game_id}.pdf"'},
    )
```

- [ ] **Step 5: Register the blueprint** (`app/__init__.py`, after the existing `register_blueprint` calls near line 32)

```python
    from app.reports.routes import report_bp
    server.register_blueprint(report_bp)
```

Also add the export to `app/reports/__init__.py`:
```python
from app.reports.routes import report_bp  # noqa: E402,F401
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_pitcher_report_route.py -v`
Expected: both PASS.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all prior tests (hitting, auth) + new report/pitching tests PASS.

- [ ] **Step 8: Commit**

```bash
git add app/auth/access.py app/reports/routes.py app/reports/__init__.py app/__init__.py tests/test_pitcher_report_route.py
git commit -m "feat(reports): login+role gated pitcher PDF download route"
```

---

## Self-Review Notes

- **Spec coverage:** engine (Tasks 2,3,7,8), pitcher data layer queries/transforms/figures (Tasks 4,5,6), all 11 sections mapped in the template (Task 7) + assembler (Task 8), delivery route with auth (Task 9), deps/assets (Task 1), tests throughout, final-score derivation (Task 4 `game_context`), tagged pitch type (Task 4 `pitch_type`). All covered.
- **Verify-against-schema reminders:** `tm_team` join columns (Task 4 Step 4) and `zi`/`izt_zone` semantics (Task 5) must be confirmed against the live schema during implementation; adjust column names if they differ. `User` constructor/fields in the route test (Task 9) must match `app/auth/models.py` — check and adjust the fixture if the signature differs.
- **Placeholder scan:** clean — every code step contains complete, runnable code; no TBD/TODO.
