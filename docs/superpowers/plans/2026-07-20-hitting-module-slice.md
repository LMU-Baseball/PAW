# Hitting Module — Slice 1 (Shell + Tabs 1–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable Hitting page in Dash — a role-aware shell (sidebar + hitter/game selector + tab frame) plus the three unblocked tabs (Game Level, Plate Appearances, Zone Location) — on top of the existing `app/data/hitting.py` transforms.

**Architecture:** Convert the placeholder `app/dashboards/hitting.py` into a focused package. A NEW **warehouse** data layer `app/data/hitting_wh.py` queries `fact_tm_game_pitch` + `dim_tm_game` + `tm_team` and returns DataFrames whose columns are **aliased to the legacy names** the existing transforms in `app/data/hitting.py` already expect, so those already-tested transforms are reused unchanged. Only `selectors.py`/`callbacks.py` call the data layer and only `layout.py`/`callbacks.py` read `current_user`. `charts.py`, `tables.py`, and `tabs/*` are pure functions of pandas DataFrames returning Plotly figures / Dash components, unit-testable in isolation.

**Tech Stack:** Flask + Dash 2.x (`dcc`, `html`, `dash_table.DataTable`, `dcc.Store`), Plotly (`plotly.graph_objects`, `plotly.subplots`), pandas, numpy, SQLAlchemy (via `app.db.query_df`), pytest.

## Global Constraints

- **DATA SOURCE = the modern Trackman warehouse** (`fact_tm_game_pitch`, `dim_tm_game`, `tm_team`), NOT legacy `GAMES`/`PLAYERS`/`STANDINGS` (which stop at May 2025). See spec §8. Legacy `app/data/hitting.py` transforms are REUSED via column aliasing; the legacy query functions are NOT used.
- **Canonical id = `batter_tm_id`** (raw Trackman id). A player's `current_user.trackman_id` IS their `batter_tm_id` (same convention as the pitcher report's `pitcher_tm_id`). Coaches have `trackman_id = None`. **LMU = `team_id 78`**; batter filter is `batter_team = 'LOY_LIO'`.
- **Column-alias contract** — `wh_game_pitches` aliases warehouse→legacy names: `plate_loc_side→PlateLocSide`, `plate_loc_height→PlateLocHeight`, `pitch_call→PitchCall`, `play_result→PlayResult`, `korbb→KorBB`, `tagged_hit_type→TaggedHitType`, `tagged_pitch_type→TaggedPitchType`, `exit_speed→ExitSpeed`, `distance→Distance`, `bearing→Bearing`, `hang_time→HangTime`, `inning→Inning`, `pa_of_inning→PAofInning`, `pitch_of_pa→PitchofPA`, `pitch_no→PitchNo`, `balls→Balls`, `strikes→Strikes`, `runs_scored→RunsScored`, `outs_on_play→OutsOnPlay`, `batter_side→BatterSide`, `pitcher_name→Pitcher`, `game_id→GameID`. Plus a computed `Zone` and `QC`/`PathQ`/`Angle` set to `NaN` (columns the warehouse lacks; keeps reused transforms from KeyError-ing).
- **Zone is COMPUTED from plate coordinates** (warehouse `izt_zone` uses a different scheme). `attack_zone(side_ft, height_ft)` in inches with `x=|side*12|`, `y=|height*12-30|`: Heart `x≤7.25 & y≤8.75`, Shadow `≤13.5/15.125`, Chase `≤20.5/25.5`, else Waste.
- **Python edits require a manual server restart; templates/CSS auto-reload.** Restart by killing the **port owner**, not the process name: `Get-NetTCPConnection -LocalPort 8050 -State Listen | %{ Stop-Process -Id $_.OwningProcess -Force }`, confirm the port is free, then run ONE `python run.py`. (memory §3b GOTCHA)
- **Brand tokens (hardcoded in the Dash `index_string`, cannot use base.html CSS vars):** crimson `#9A0021`, blue `#0076A5`, bg `#f5f5f5`, palms `/static/brand/palms-grey.png`, favicon `/static/reports/lion.png`. Keep identical to the site. (memory §3c)
- **Percentages from the transforms are numeric** (e.g. `33.3`), not `"33.3%"` strings — append `%` only at display time.
- **Live-DB tests are unguarded**, matching the existing `test_hitting.py` convention (no skip-if-no-DB). Run the full suite with `python -m pytest -q`. Baseline is **118 passing**.
- **Subagent discipline (memory §3c PROCESS LESSON):** implementers may only `git add <named files>` + commit. Never `git stash/reset/checkout/clean`.
- **Strike-zone geometry (drawn in the scatter, units = inches):** convert `x = PlateLocSide * -12`, `y = PlateLocHeight * 12 - 30`. Zone rectangles: waste `x[-20.5,20.5] y[-25.5,25.5]`, shadow `x[-13.5,13.5] y[-15.125,15.125]`, heart `x[-7.25,7.25] y[-8.75,8.75]`; strike-zone border `x[-10,10] y[-13,13]` with 3×3 gridlines at `x=±3.33`, `y=±4.33`. Axis range `x[-50,50] y[-35,35]`, axes hidden.

---

### Task 1: Warehouse hitting data layer

New module `app/data/hitting_wh.py`: warehouse loaders that alias columns to the
legacy names the existing transforms expect, compute the attack `Zone`, and add the
missing `QC`/`PathQ`/`Angle` columns as `NaN`. Reuses the transforms from
`app/data/hitting.py` (imported) — this task adds NO new transform logic.

**Files:**
- Create: `app/data/hitting_wh.py`
- Test: `tests/test_hitting_wh.py` (new)

**Interfaces:**
- Consumes: `app.db.query_df`; `app.data.hitting._add_pitch_category`, `qab_frame`.
- Produces:
  - `LMU_TEAM_ID = 78`; `attack_zone(side_ft, height_ft) -> str`.
  - `wh_lmu_hitters() -> pd.DataFrame` — columns `Batter, BatterId` (BatterId = `batter_tm_id`), distinct current LMU hitters ordered by name.
  - `wh_games_for_batter(batter_tm_id) -> pd.DataFrame` — columns `game_id, game_date, GameLabel` newest first (`GameLabel` = `"MM/DD/YY vs OPP"` / `"@ OPP"`).
  - `wh_game_pitches(game_id, batter_tm_id) -> pd.DataFrame` — aliased pitch rows for one game + `Zone` + NaN `QC`/`PathQ`/`Angle`, ordered by pitch.
  - `wh_season_pitches(batter_tm_id) -> pd.DataFrame` — same shape, all of a batter's games.
  - `wh_season_qab_rate(batter_tm_id) -> float | None`.
  - `wh_player_profile(batter_tm_id) -> dict` — keys `name, bats, class_year, position, photo, jersey` (name = "Last, First"; photo/jersey `""`; class_year/position best-effort).
  - `wh_scoreboard(game_id) -> dict` — keys `date, loc, opp, game_type` (loc = "vs"/"@").

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hitting_wh.py`:

```python
"""Tests for the warehouse hitting data layer (live DB, unguarded)."""
import numpy as np
import pandas as pd
import pytest

from app.data import hitting_wh as wh
from app.db import query_df


@pytest.fixture(scope="module")
def top_batter():
    df = query_df(
        """
        SELECT batter_tm_id FROM fact_tm_game_pitch
         WHERE batter_team='LOY_LIO' AND batter_tm_id IS NOT NULL
         GROUP BY batter_tm_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "batter_tm_id"])


@pytest.fixture(scope="module")
def top_game(top_batter):
    df = query_df(
        """
        SELECT game_id FROM fact_tm_game_pitch WHERE batter_tm_id=:b
         GROUP BY game_id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        {"b": top_batter},
    )
    return int(df.loc[0, "game_id"])


def test_attack_zone_boundaries():
    assert wh.attack_zone(0.0, 2.5) == "Heart"       # dead center
    assert wh.attack_zone(1.0, 2.5) == "Shadow"      # ~12in side
    assert wh.attack_zone(1.6, 2.5) == "Chase"       # ~19in side
    assert wh.attack_zone(3.0, 2.5) == "Waste"       # far outside


def test_wh_lmu_hitters(top_batter):
    df = wh.wh_lmu_hitters()
    assert list(df.columns) == ["Batter", "BatterId"]
    assert df["BatterId"].is_unique
    assert top_batter in set(df["BatterId"])


def test_wh_games_for_batter(top_batter):
    df = wh.wh_games_for_batter(top_batter)
    assert {"game_id", "game_date", "GameLabel"} <= set(df.columns)
    assert len(df) >= 1
    # newest first
    assert list(df["game_date"]) == sorted(df["game_date"], reverse=True)


def test_wh_game_pitches_has_aliased_and_computed_cols(top_game, top_batter):
    df = wh.wh_game_pitches(top_game, top_batter)
    assert len(df) > 0
    for c in ("PlateLocSide", "PitchCall", "PlayResult", "KorBB", "TaggedHitType",
              "TaggedPitchType", "ExitSpeed", "Inning", "PAofInning", "PitchofPA",
              "PitchNo", "Balls", "Strikes", "RunsScored", "BatterSide", "Pitcher",
              "GameID", "Zone", "QC", "PathQ", "Angle", "PitchCat"):
        assert c in df.columns
    assert set(df["Zone"]).issubset({"Heart", "Shadow", "Chase", "Waste"})
    assert df["QC"].isna().all()


def test_wh_game_pitches_feeds_reused_transforms(top_game, top_batter):
    from app.data import hitting
    df = wh.wh_game_pitches(top_game, top_batter)
    line = hitting.game_batting_line(df)          # must not raise
    assert set(line) >= {"PA", "H", "SO", "BB", "QAB"}
    pd_zone = hitting.plate_discipline(df, by="zone")
    assert list(pd_zone["Zone"]) == ["Heart", "Shadow", "Chase", "Waste"]


def test_wh_player_profile_and_scoreboard(top_batter, top_game):
    prof = wh.wh_player_profile(top_batter)
    assert set(prof) == {"name", "bats", "class_year", "position", "photo", "jersey"}
    assert prof["name"]                # non-empty for a real batter
    assert prof["photo"] == "" and prof["jersey"] == ""
    sb = wh.wh_scoreboard(top_game)
    assert set(sb) == {"date", "loc", "opp", "game_type"}
    assert sb["loc"] in ("vs", "@")


def test_wh_season_qab_rate(top_batter):
    r = wh.wh_season_qab_rate(top_batter)
    assert r is None or 0.0 <= r <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hitting_wh.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.hitting_wh'`.

- [ ] **Step 3: Implement the warehouse loaders**

Create `app/data/hitting_wh.py`:

```python
"""Warehouse hitting data layer.

Queries the modern Trackman warehouse (fact_tm_game_pitch / dim_tm_game / tm_team)
and returns DataFrames whose columns are aliased to the LEGACY names the transforms
in app/data/hitting.py expect, so those transforms are reused unchanged. Adds a
computed attack `Zone` and NaN `QC`/`PathQ`/`Angle` (columns the warehouse lacks).
Canonical id = batter_tm_id (== a player's current_user.trackman_id). LMU = team 78.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import query_df
from app.data.hitting import _add_pitch_category, qab_frame

LMU_TEAM_ID = 78
LMU_BATTER_TEAM = "LOY_LIO"

# fact -> legacy alias list, shared by game + season loaders.
_PITCH_SELECT = """
    plate_loc_side AS PlateLocSide, plate_loc_height AS PlateLocHeight,
    pitch_call AS PitchCall, play_result AS PlayResult, korbb AS KorBB,
    tagged_hit_type AS TaggedHitType, tagged_pitch_type AS TaggedPitchType,
    exit_speed AS ExitSpeed, distance AS Distance, bearing AS Bearing,
    hang_time AS HangTime, inning AS Inning, pa_of_inning AS PAofInning,
    pitch_of_pa AS PitchofPA, pitch_no AS PitchNo, balls AS Balls,
    strikes AS Strikes, runs_scored AS RunsScored, outs_on_play AS OutsOnPlay,
    batter_side AS BatterSide, pitcher_name AS Pitcher, game_id AS GameID
"""


def attack_zone(side_ft, height_ft) -> str:
    """Heart/Shadow/Chase/Waste from plate coords (inches; zone-box boundaries)."""
    if side_ft is None or height_ft is None or pd.isna(side_ft) or pd.isna(height_ft):
        return "Waste"
    x = abs(float(side_ft) * 12)
    y = abs(float(height_ft) * 12 - 30)
    if x <= 7.25 and y <= 8.75:
        return "Heart"
    if x <= 13.5 and y <= 15.125:
        return "Shadow"
    if x <= 20.5 and y <= 25.5:
        return "Chase"
    return "Waste"


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["Zone"] = [attack_zone(s, h)
                  for s, h in zip(df["PlateLocSide"], df["PlateLocHeight"])]
    for c in ("QC", "PathQ", "Angle"):
        df[c] = np.nan
    return _add_pitch_category(df)


def wh_lmu_hitters() -> pd.DataFrame:
    return query_df(
        """
        SELECT DISTINCT batter_name AS Batter, batter_tm_id AS BatterId
          FROM fact_tm_game_pitch
         WHERE batter_team = :team AND batter_tm_id IS NOT NULL
         ORDER BY batter_name
        """,
        {"team": LMU_BATTER_TEAM},
    )


def wh_games_for_batter(batter_tm_id) -> pd.DataFrame:
    df = query_df(
        """
        SELECT g.game_id, g.game_date, g.home_team_id,
               CASE WHEN g.home_team_id = :lmu THEN 'vs' ELSE '@' END AS loc,
               t.team_name AS opp
          FROM (SELECT DISTINCT game_id FROM fact_tm_game_pitch
                 WHERE batter_tm_id = :b) bg
          JOIN dim_tm_game g ON g.game_id = bg.game_id
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         ORDER BY g.game_date DESC
        """,
        {"b": int(batter_tm_id), "lmu": LMU_TEAM_ID},
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]


def wh_game_pitches(game_id, batter_tm_id) -> pd.DataFrame:
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch
         WHERE game_id = :g AND batter_tm_id = :b
         ORDER BY pitch_no
        """,
        {"g": int(game_id), "b": int(batter_tm_id)},
    )
    return _finish(df)


def wh_season_pitches(batter_tm_id) -> pd.DataFrame:
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch
         WHERE batter_tm_id = :b
         ORDER BY game_id, pitch_no
        """,
        {"b": int(batter_tm_id)},
    )
    return _finish(df)


def wh_season_qab_rate(batter_tm_id) -> float | None:
    df = wh_season_pitches(batter_tm_id)
    if df.empty:
        return None
    q = qab_frame(df)
    total = len(q)
    return round(q["QAB"].sum() / total, 3) if total else None


def _roster_lookup(name_last_first: str) -> tuple[str, str]:
    """Best-effort class_year/position from roster_players (name is 'First Last')."""
    if "," not in name_last_first:
        return "", ""
    last, first = (p.strip() for p in name_last_first.split(",", 1))
    df = query_df(
        """
        SELECT class_year, position FROM roster_players
         WHERE season LIKE '2025%' AND player_name = :n LIMIT 1
        """,
        {"n": f"{first} {last}"},
    )
    if df.empty:
        return "", ""
    r = df.iloc[0]
    cy = "" if pd.isna(r["class_year"]) else str(r["class_year"])
    pos = "" if pd.isna(r["position"]) else str(r["position"])
    return cy, pos


def wh_player_profile(batter_tm_id) -> dict:
    blank = {"name": "", "bats": "", "class_year": "", "position": "",
             "photo": "", "jersey": ""}
    df = query_df(
        """
        SELECT batter_name, batter_side FROM fact_tm_game_pitch
         WHERE batter_tm_id = :b ORDER BY game_id DESC LIMIT 1
        """,
        {"b": int(batter_tm_id)},
    )
    if df.empty:
        return blank
    name = "" if pd.isna(df.iloc[0]["batter_name"]) else str(df.iloc[0]["batter_name"])
    bats = "" if pd.isna(df.iloc[0]["batter_side"]) else str(df.iloc[0]["batter_side"])
    cy, pos = _roster_lookup(name)
    return {"name": name, "bats": bats, "class_year": cy, "position": pos,
            "photo": "", "jersey": ""}


def wh_scoreboard(game_id) -> dict:
    df = query_df(
        """
        SELECT g.game_date, g.game_type, g.home_team_id, t.team_name AS opp
          FROM dim_tm_game g
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         WHERE g.game_id = :g
        """,
        {"g": int(game_id), "lmu": LMU_TEAM_ID},
    )
    if df.empty:
        return {"date": "", "loc": "", "opp": "", "game_type": ""}
    r = df.iloc[0]
    return {"date": pd.to_datetime(r["game_date"]).strftime("%m/%d/%y"),
            "loc": "vs" if r["home_team_id"] == LMU_TEAM_ID else "@",
            "opp": "" if pd.isna(r["opp"]) else str(r["opp"]),
            "game_type": "" if pd.isna(r["game_type"]) else str(r["game_type"])}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_wh.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add app/data/hitting_wh.py tests/test_hitting_wh.py
git commit -m "feat(hitting): warehouse data layer (aliased to reuse transforms)"
```

---

### Task 2: Convert the Dash placeholder into a package scaffold

Turn `app/dashboards/hitting.py` into a package so the tabs/charts/tables can live in focused files. Preserve the working placeholder behavior; the shell comes in later tasks. `app/dashboards/__init__.py` imports `from app.dashboards.hitting import build_hitting_dash`, which keeps working when `hitting/__init__.py` re-exports it — no change needed there.

**Files:**
- Delete: `app/dashboards/hitting.py`
- Create: `app/dashboards/hitting/__init__.py`
- Create: `app/dashboards/hitting/index.py`
- Create: `app/dashboards/hitting/tabs/__init__.py` (empty package marker)
- Test: `tests/test_hitting_dash.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `index.INDEX_STRING: str` — the Dash HTML shell (grey+palms bg + lion favicon).
  - `build_hitting_dash(server) -> Dash` — unchanged public signature; mounts at `/dash/hitting/`, sets `index_string = INDEX_STRING`, layout = `serve_layout` (temporary placeholder until Task 9).

- [ ] **Step 1: Write the failing test**

Create `tests/test_hitting_dash.py`:

```python
"""Tests for the Dash hitting dashboard (shell, selectors, tabs)."""
import pandas as pd
import pytest

from app import create_app
from config import Config


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    return create_app(TestConfig)


def test_build_hitting_dash_mounts(server):
    from app.dashboards.hitting import build_hitting_dash, INDEX_STRING
    # create_app already mounted one; building again against the same server is fine
    dash_app = build_hitting_dash(server)
    assert dash_app.config.url_base_pathname == "/dash/hitting/"
    assert "palms-grey.png" in INDEX_STRING
    assert "/static/reports/lion.png" in INDEX_STRING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py -v`
Expected: FAIL with `ImportError: cannot import name 'INDEX_STRING'`

- [ ] **Step 3: Create the package**

Create `app/dashboards/hitting/index.py`:

```python
"""The Dash HTML shell. The Dash page does not extend base.html, so the site's
grey+palms background and lion favicon are set here (hardcoded — cannot use
base.html CSS tokens; keep in sync with the site brand). See memory §3c."""

INDEX_STRING = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
<link rel="icon" type="image/png" href="/static/reports/lion.png">
{%css%}
<style>
  body {
    margin: 0; min-height: 100vh;
    background-color: #f5f5f5;
    background-image: url('/static/brand/palms-grey.png');
    background-repeat: no-repeat; background-position: center bottom;
    background-size: cover; background-attachment: fixed;
    font-family: 'Teko', sans-serif;
  }
</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""
```

Create `app/dashboards/hitting/tabs/__init__.py` (empty file).

Create `app/dashboards/hitting/__init__.py` (delete the old `app/dashboards/hitting.py` first):

```python
"""Login-protected Hitting dashboard (Flask + Dash).

Package layout:
  index.py       the Dash HTML shell (background + favicon)
  selectors.py   role-aware hitter/game options + batter resolution
  charts.py      Plotly figures (strike-zone scatter, all-PAs facet)
  tables.py      Dash DataTable builders
  tabs/          per-tab render() functions (pure: df -> components)
  callbacks.py   selection -> data stores -> tab content
"""
from dash import Dash, html
from flask_login import current_user

from app.dashboards.hitting.index import INDEX_STRING

__all__ = ["build_hitting_dash", "INDEX_STRING"]


def build_hitting_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/hitting/",
        suppress_callback_exceptions=True,
        title="Hitting — The PAW",
    )
    dash_app.index_string = INDEX_STRING

    def serve_layout():
        # Placeholder until Task 9 wires the real shell.
        if not current_user.is_authenticated:
            return html.Div("Please log in.")
        return html.Div(
            style={"padding": "24px"},
            children=[html.H2("Hitting Dashboard"),
                      html.A("← Back to home", href="/")],
        )

    dash_app.layout = serve_layout
    return dash_app
```

- [ ] **Step 4: Run test + full suite to verify green**

Run: `python -m pytest tests/test_hitting_dash.py -v && python -m pytest -q`
Expected: new test PASSES; full suite still **118 passing**.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting tests/test_hitting_dash.py
git rm app/dashboards/hitting.py
git commit -m "refactor(hitting): convert Dash placeholder to a package scaffold"
```

---

### Task 3: Role-aware selectors (pure functions)

Selection logic and role enforcement, as pure functions that take explicit role/id params (never read `current_user`) so they are unit-testable. The layout/callbacks pass `current_user` values in.

**Files:**
- Create: `app/dashboards/hitting/selectors.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `app.data.hitting_wh.wh_lmu_hitters`, `wh_games_for_batter`, `wh_player_profile`.
- Produces:
  - `resolve_batter(requested_id, *, is_coach: bool, own_trackman_id) -> int | None` — coach: returns `int(requested_id)` if given else None; player: ALWAYS returns `int(own_trackman_id)` ignoring `requested_id` (server-side self-only guard). `own_trackman_id`/`requested_id` are `batter_tm_id`s.
  - `hitter_options(*, is_coach: bool, own_trackman_id) -> list[dict]` — coach: `[{"label","value"}]` for every current LMU hitter (label "Last, First", value `batter_tm_id`); player: single option for themselves (from `wh_player_profile` name if available, else the id).
  - `game_options(batter_tm_id) -> list[dict]` — `[{"label": GameLabel, "value": game_id}]` newest first for that batter.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_dash.py`:

```python
def test_resolve_batter_player_is_self_only():
    from app.dashboards.hitting import selectors
    # a player cannot resolve someone else's id
    assert selectors.resolve_batter(999, is_coach=False, own_trackman_id=806253) == 806253
    assert selectors.resolve_batter(None, is_coach=False, own_trackman_id=806253) == 806253


def test_resolve_batter_coach_passes_through():
    from app.dashboards.hitting import selectors
    assert selectors.resolve_batter(123, is_coach=True, own_trackman_id=None) == 123
    assert selectors.resolve_batter(None, is_coach=True, own_trackman_id=None) is None


def test_hitter_options_coach_lists_all(monkeypatch):
    from app.dashboards.hitting import selectors
    monkeypatch.setattr("app.data.hitting_wh.wh_lmu_hitters",
                        lambda: pd.DataFrame(
                            [{"Batter": "Doe, John", "BatterId": 1},
                             {"Batter": "Roe, Jane", "BatterId": 2}]))
    opts = selectors.hitter_options(is_coach=True, own_trackman_id=None)
    assert {o["value"] for o in opts} == {1, 2}


def test_hitter_options_player_is_single_self(monkeypatch):
    from app.dashboards.hitting import selectors
    monkeypatch.setattr("app.data.hitting_wh.wh_player_profile",
                        lambda b: {"name": "Wadas, Zach", "bats": "Right",
                                   "class_year": "", "position": "", "photo": "",
                                   "jersey": ""})
    opts = selectors.hitter_options(is_coach=False, own_trackman_id=806253)
    assert len(opts) == 1
    assert opts[0]["value"] == 806253
    assert opts[0]["label"] == "Wadas, Zach"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hitting_dash.py -k "resolve_batter or hitter_options" -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError`.

- [ ] **Step 3: Implement selectors**

Create `app/dashboards/hitting/selectors.py`:

```python
"""Role-aware selection helpers (pure functions of explicit role/id params).

A player is locked to their own data server-side; these functions never trust a
client-supplied hitter id for a player. `current_user` is read by layout/callbacks
and passed in, keeping this module testable in isolation. Ids are batter_tm_id.
"""
from __future__ import annotations

from app.data import hitting_wh


def resolve_batter(requested_id, *, is_coach: bool, own_trackman_id):
    """The batter id a request is allowed to view. Players are self-only."""
    if not is_coach:
        return int(own_trackman_id) if own_trackman_id is not None else None
    return int(requested_id) if requested_id not in (None, "") else None


def hitter_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    """Dropdown options for the hitter selector (value = batter_tm_id)."""
    if is_coach:
        df = hitting_wh.wh_lmu_hitters()
        return [{"label": str(r.Batter), "value": int(r.BatterId)}
                for r in df.itertuples()]
    if own_trackman_id is None:
        return []
    prof = hitting_wh.wh_player_profile(int(own_trackman_id))
    return [{"label": prof["name"] or str(own_trackman_id),
             "value": int(own_trackman_id)}]


def game_options(batter_tm_id) -> list[dict]:
    """Dropdown options (newest first) for a batter's games (value = game_id)."""
    if batter_tm_id is None:
        return []
    df = hitting_wh.wh_games_for_batter(int(batter_tm_id))
    return [{"label": str(r.GameLabel), "value": int(r.game_id)}
            for r in df.itertuples()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py -k "resolve_batter or hitter_options" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/selectors.py tests/test_hitting_dash.py
git commit -m "feat(hitting): role-aware selector helpers"
```

---

### Task 4: Strike-zone charts (Plotly)

The strike-zone scatter (shared by Plate Appearances and Zone Location) and the all-PAs facet. Pure functions of a pitch DataFrame.

**Files:**
- Create: `app/dashboards/hitting/charts.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: pitch DataFrame columns `PlateLocSide, PlateLocHeight, TaggedPitchType, PitchCall, PlayResult, TaggedHitType, Balls, Strikes, Inning, PAofInning, PitchofPA, Pitcher`.
- Produces:
  - `PITCH_COLORS: dict[str, str]` and `color_for(pitch_type: str) -> str`.
  - `zone_scatter(df: pd.DataFrame, title: str = "") -> plotly.graph_objects.Figure`.
  - `all_pas_figure(df: pd.DataFrame) -> plotly.graph_objects.Figure` — one strike-zone subplot per PA (grouped by `Inning, PAofInning`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_dash.py`:

```python
def _fake_pitches():
    return pd.DataFrame([
        {"PlateLocSide": 0.2, "PlateLocHeight": 2.5, "TaggedPitchType": "Fastball",
         "PitchCall": "StrikeSwinging", "PlayResult": "Undefined", "TaggedHitType": None,
         "Balls": 0, "Strikes": 1, "Inning": 1, "PAofInning": 1, "PitchofPA": 1,
         "Pitcher": "Smith, Joe"},
        {"PlateLocSide": -0.5, "PlateLocHeight": 1.8, "TaggedPitchType": "Slider",
         "PitchCall": "InPlay", "PlayResult": "Single", "TaggedHitType": "LineDrive",
         "Balls": 1, "Strikes": 1, "Inning": 3, "PAofInning": 2, "PitchofPA": 2,
         "Pitcher": "Smith, Joe"},
    ])


def test_zone_scatter_returns_figure_with_points():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.zone_scatter(_fake_pitches(), title="Test")
    assert isinstance(fig, go.Figure)
    # at least one scatter trace carrying the 2 pitch markers
    xs = [x for tr in fig.data for x in (tr.x or [])]
    assert len(xs) >= 2


def test_zone_scatter_empty_df_is_safe():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.zone_scatter(pd.DataFrame(), title="Empty")
    assert isinstance(fig, go.Figure)


def test_all_pas_figure_one_cell_per_pa():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.all_pas_figure(_fake_pitches())
    assert isinstance(fig, go.Figure)  # 2 distinct PAs -> renders without error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hitting_dash.py -k "zone_scatter or all_pas" -v`
Expected: FAIL with `ModuleNotFoundError: app.dashboards.hitting.charts`.

- [ ] **Step 3: Implement charts**

Create `app/dashboards/hitting/charts.py`:

```python
"""Plotly strike-zone visualizations (pure functions of a pitch DataFrame).

Geometry ported from the R `zones_location` renderer (units = inches):
  x = PlateLocSide * -12 ; y = PlateLocHeight * 12 - 30
Zone rectangles and 3x3 gridlines match the R plot. Axes are hidden.
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data.hitting import PITCH_ABBR

# Stable per-pitch-type colors (PAW palette; crimson fastball, blue slider).
PITCH_COLORS = {
    "Fastball": "#9A0021", "Sinker": "#7a5230", "Cutter": "#e07b39",
    "Slider": "#0076A5", "Curveball": "#2b4c7e", "ChangeUp": "#e08a1e",
    "Splitter": "#5a5a5a", "Other": "#9aa0a6",
}
_DEFAULT_COLOR = "#9aa0a6"

# Zone rectangles as (x0, y0, x1, y1, fillcolor).
_ZONE_RECTS = [
    (-20.5, -25.5, 20.5, 25.5, "rgba(0,0,0,0.06)"),   # waste
    (-13.5, -15.125, 13.5, 15.125, "rgba(0,0,0,0.10)"),  # shadow
    (-7.25, -8.75, 7.25, 8.75, "rgba(0,0,0,0.16)"),   # heart
]
_SZ = (-10, -13, 10, 13)          # strike-zone border box
_VLINES = (-3.33, 3.33)           # vertical 3x3 gridlines
_HLINES = (-4.33, 4.33)           # horizontal 3x3 gridlines
_XRANGE = (-50, 50)
_YRANGE = (-35, 35)


def color_for(pitch_type: str) -> str:
    return PITCH_COLORS.get(pitch_type, _DEFAULT_COLOR)


def _to_xy(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["PlateLocSide"].notna() & df["PlateLocHeight"].notna()].copy()
    d["_x"] = d["PlateLocSide"] * -12
    d["_y"] = d["PlateLocHeight"] * 12 - 30
    return d


def _result_text(r) -> str:
    if r["PlayResult"] in (None, "Undefined"):
        return str(r["PitchCall"])
    return f"{r.get('TaggedHitType') or ''} - {r['PlayResult']}".strip(" -")


def _add_zone_shapes(fig, *, row=None, col=None):
    kw = {}
    if row is not None:
        kw = {"row": row, "col": col}
    for x0, y0, x1, y1, fill in _ZONE_RECTS:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(width=0), fillcolor=fill, layer="below", **kw)
    x0, y0, x1, y1 = _SZ
    fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                  line=dict(color="#888", width=1.5), fillcolor="rgba(0,0,0,0)", **kw)
    for vx in _VLINES:
        fig.add_shape(type="line", x0=vx, y0=y0, x1=vx, y1=y1,
                      line=dict(color="#bbb", width=1), **kw)
    for hy in _HLINES:
        fig.add_shape(type="line", x0=x0, y0=hy, x1=x1, y1=hy,
                      line=dict(color="#bbb", width=1), **kw)


def _style_axes(fig, *, row=None, col=None):
    kw = {"row": row, "col": col} if row is not None else {}
    fig.update_xaxes(range=list(_XRANGE), showgrid=False, zeroline=False,
                     visible=False, **kw)
    fig.update_yaxes(range=list(_YRANGE), showgrid=False, zeroline=False,
                     visible=False, scaleanchor=None, **kw)


def zone_scatter(df: pd.DataFrame, title: str = "") -> go.Figure:
    """Strike-zone scatter, one marker per pitch, colored by pitch type."""
    fig = go.Figure()
    _add_zone_shapes(fig)
    if df is not None and not df.empty:
        d = _to_xy(df)
        for ptype, g in d.groupby("TaggedPitchType"):
            fig.add_trace(go.Scatter(
                x=g["_x"], y=g["_y"], mode="markers",
                name=PITCH_ABBR.get(ptype, ptype),
                marker=dict(size=13, color=color_for(ptype),
                            line=dict(color="white", width=1), opacity=0.85),
                customdata=[[r["Balls"], r["Strikes"], r.get("Pitcher", ""),
                             _result_text(r)] for _, r in g.iterrows()],
                hovertemplate=("<b>%{text}</b><br>Count %{customdata[0]}-%{customdata[1]}"
                               "<br>Pitcher %{customdata[2]}<br>%{customdata[3]}"
                               "<extra></extra>"),
                text=[PITCH_ABBR.get(ptype, ptype)] * len(g),
            ))
    _style_axes(fig)
    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=16)),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.05), height=460,
    )
    return fig


def all_pas_figure(df: pd.DataFrame) -> go.Figure:
    """One strike-zone subplot per plate appearance (grouped Inning, PAofInning)."""
    if df is None or df.empty:
        fig = go.Figure()
        _add_zone_shapes(fig)
        _style_axes(fig)
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10),
                          paper_bgcolor="rgba(0,0,0,0)")
        return fig

    pa_keys = list(df.groupby(["Inning", "PAofInning"]).groups.keys())
    n = len(pa_keys)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    titles = [f"Inn {int(i)} · PA {int(p)}" for (i, p) in pa_keys]
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=titles,
                        horizontal_spacing=0.03, vertical_spacing=0.08)
    for idx, key in enumerate(pa_keys):
        row = idx // ncols + 1
        col = idx % ncols + 1
        _add_zone_shapes(fig, row=row, col=col)
        g = _to_xy(df[(df["Inning"] == key[0]) & (df["PAofInning"] == key[1])])
        for ptype, gg in g.groupby("TaggedPitchType"):
            fig.add_trace(go.Scatter(
                x=gg["_x"], y=gg["_y"], mode="markers+text",
                text=[str(int(v)) for v in gg["PitchofPA"]],
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=11, color=color_for(ptype),
                            line=dict(color="white", width=1)),
                showlegend=False,
            ), row=row, col=col)
        _style_axes(fig, row=row, col=col)
    fig.update_layout(height=300 * nrows, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py -k "zone_scatter or all_pas" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/charts.py tests/test_hitting_dash.py
git commit -m "feat(hitting): strike-zone Plotly charts"
```

---

### Task 5: DataTable builders

Reusable Dash `DataTable` builder for the stat tables, plus a helper that appends `%` to the numeric percent columns at display time.

**Files:**
- Create: `app/dashboards/hitting/tables.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: a pandas DataFrame.
- Produces:
  - `PCT_COLS: set[str]` — the columns that display with a trailing `%`.
  - `stat_table(df: pd.DataFrame, *, id: str | None = None) -> dash_table.DataTable` — brand-styled; formats `PCT_COLS` values as `"NN.N%"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_dash.py`:

```python
def test_stat_table_builds_and_formats_pct():
    from app.dashboards.hitting import tables
    from dash import dash_table
    df = pd.DataFrame([{"Zone": "Heart", "Total": 10, "Swing %": 40.0}])
    tbl = tables.stat_table(df, id="t")
    assert isinstance(tbl, dash_table.DataTable)
    # percent column rendered with a trailing %
    assert tbl.data[0]["Swing %"] == "40.0%"
    assert tbl.data[0]["Total"] == 10


def test_stat_table_empty_df_is_safe():
    from app.dashboards.hitting import tables
    tbl = tables.stat_table(pd.DataFrame())
    assert tbl.data == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hitting_dash.py -k "stat_table" -v`
Expected: FAIL with `ModuleNotFoundError: app.dashboards.hitting.tables`.

- [ ] **Step 3: Implement tables**

Create `app/dashboards/hitting/tables.py`:

```python
"""Dash DataTable builders for the hitting stat tables."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

# Numeric-percent columns produced by app/data/hitting.py, shown with a % suffix.
PCT_COLS = {"Swing %", "Whiff %", "Take %", "Contact %"}


def _format(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    for c in d.columns:
        if c in PCT_COLS:
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{float(v):.1f}%")
    return d


def stat_table(df: pd.DataFrame, *, id: str | None = None) -> dash_table.DataTable:
    d = _format(df)
    cols = [{"name": c, "id": c} for c in d.columns]
    return dash_table.DataTable(
        id=id or "stat-table",
        columns=cols,
        data=d.to_dict("records"),
        style_as_list_view=True,
        style_header={"backgroundColor": "#9A0021", "color": "white",
                      "fontWeight": "bold", "textAlign": "center"},
        style_cell={"textAlign": "center", "padding": "6px 10px",
                    "fontFamily": "Teko, sans-serif", "fontSize": "16px"},
        style_data={"backgroundColor": "rgba(255,255,255,0.85)"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py -k "stat_table" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/tables.py tests/test_hitting_dash.py
git commit -m "feat(hitting): DataTable builder for stat tables"
```

---

### Task 6: Game Level tab

First tab: coach note + batting line + batted-ball profile (overall and by pitch type).

**Files:**
- Create: `app/dashboards/hitting/tabs/game_level.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `app.data.hitting.game_batting_line`, `batted_ball_profile`; `tables.stat_table`. Receives `game_df` and a `note` string.
- Produces: `render(game_df: pd.DataFrame, note: str = "") -> dash.html.Div`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_dash.py`:

```python
def test_game_level_renders_for_real_and_empty(game_df):
    from app.dashboards.hitting.tabs import game_level
    from dash import html
    out = game_level.render(game_df, note="Great AB battle.")
    assert isinstance(out, html.Div)
    # empty df must not crash
    assert isinstance(game_level.render(pd.DataFrame(), note=""), html.Div)
```

Add the shared `game_df` fixture at the top of `tests/test_hitting_dash.py` (live warehouse):

```python
from app.data import hitting_wh
from app.db import query_df


@pytest.fixture(scope="module")
def real_batter():
    cand = query_df(
        """
        SELECT batter_tm_id FROM fact_tm_game_pitch
         WHERE batter_team = 'LOY_LIO' AND batter_tm_id IS NOT NULL
         GROUP BY batter_tm_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(cand.loc[0, "batter_tm_id"])


@pytest.fixture(scope="module")
def game_df(real_batter):
    games = hitting_wh.wh_games_for_batter(real_batter)
    gid = int(games.iloc[0]["game_id"])
    return hitting_wh.wh_game_pitches(gid, real_batter)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py -k "game_level" -v`
Expected: FAIL with `ModuleNotFoundError: app.dashboards.hitting.tabs.game_level`.

- [ ] **Step 3: Implement the tab**

Create `app/dashboards/hitting/tabs/game_level.py`:

```python
"""Game Level tab: note + batting line + batted-ball profile."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.data import hitting
from app.dashboards.hitting import tables


def _section(title, child):
    return html.Div([
        html.H3(title, style={"color": "#9A0021", "margin": "16px 0 6px"}),
        child,
    ])


def render(game_df: pd.DataFrame, note: str = "") -> html.Div:
    line = hitting.game_batting_line(game_df)
    line_df = pd.DataFrame([line])
    # QC+/PathQ+ are LMU-custom columns absent from the warehouse (NaN) — drop them.
    _drop = ["Avg QC+", "Avg PathQ+"]
    bb_overall = hitting.batted_ball_profile(game_df).drop(columns=_drop, errors="ignore")
    bb_pt = hitting.batted_ball_profile(game_df, by_pitch_type=True).drop(
        columns=_drop, errors="ignore")

    note_block = html.Div(
        note or "No note for this game.",
        style={"fontStyle": "italic", "padding": "10px 12px",
               "backgroundColor": "rgba(255,255,255,0.75)", "borderRadius": "8px"},
    )
    return html.Div([
        _section("Coach Note", note_block),
        _section("Batting Line", tables.stat_table(line_df, id="tbl-line")),
        _section("Batted Ball Profile", tables.stat_table(bb_overall, id="tbl-bb")),
        _section("Batted Ball by Pitch Type", tables.stat_table(bb_pt, id="tbl-bb-pt")),
    ], style={"padding": "10px 4px"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hitting_dash.py -k "game_level" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/tabs/game_level.py tests/test_hitting_dash.py
git commit -m "feat(hitting): Game Level tab"
```

---

### Task 7: Plate Appearances tab

Per-appearance strike-zone scatter + that PA's pitch table, plus the all-PAs facet.

**Files:**
- Create: `app/dashboards/hitting/tabs/plate_appearances.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `charts.zone_scatter`, `charts.all_pas_figure`, `tables.stat_table`; `app.data.hitting.number_plate_appearances`.
- Produces:
  - `pa_choices(game_df) -> list[dict]` — `[{"label": "Inn i · PA p", "value": "i-p"}]` for each PA (value encodes Inning-PAofInning).
  - `render_breakdown(game_df, pa_value: str | None) -> dash.html.Div` — zone scatter + pitch table for the selected PA (first PA if None).
  - `render_all_pas(game_df) -> dash.dcc.Graph` — facet figure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_dash.py`:

```python
def test_plate_appearances_choices_and_render(game_df):
    from app.dashboards.hitting.tabs import plate_appearances as pa
    from dash import html, dcc
    choices = pa.pa_choices(game_df)
    assert len(choices) >= 1
    out = pa.render_breakdown(game_df, choices[0]["value"])
    assert isinstance(out, html.Div)
    assert isinstance(pa.render_all_pas(game_df), dcc.Graph)


def test_plate_appearances_empty_is_safe():
    from app.dashboards.hitting.tabs import plate_appearances as pa
    from dash import html, dcc
    assert pa.pa_choices(pd.DataFrame()) == []
    assert isinstance(pa.render_breakdown(pd.DataFrame(), None), html.Div)
    assert isinstance(pa.render_all_pas(pd.DataFrame()), dcc.Graph)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hitting_dash.py -k "plate_appearances" -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the tab**

Create `app/dashboards/hitting/tabs/plate_appearances.py`:

```python
"""Plate Appearances tab: per-PA zone scatter + pitch table; all-PAs facet."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.hitting import charts, tables

_PA_TABLE_COLS = ["PitchofPA", "TaggedPitchType", "PitchCall", "PlayResult",
                  "Balls", "Strikes", "ExitSpeed", "Pitcher"]


def pa_choices(game_df: pd.DataFrame) -> list[dict]:
    if game_df is None or game_df.empty:
        return []
    keys = sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())
    return [{"label": f"Inn {int(i)} · PA {int(p)}", "value": f"{int(i)}-{int(p)}"}
            for (i, p) in keys]


def _pa_slice(game_df, pa_value):
    keys = sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())
    if not keys:
        return game_df.iloc[0:0]
    if pa_value:
        inn, pa = (int(x) for x in pa_value.split("-"))
    else:
        inn, pa = keys[0]
    return game_df[(game_df["Inning"] == inn) & (game_df["PAofInning"] == pa)]


def render_breakdown(game_df: pd.DataFrame, pa_value: str | None) -> html.Div:
    sub = _pa_slice(game_df, pa_value) if game_df is not None and not game_df.empty \
        else pd.DataFrame()
    fig = charts.zone_scatter(sub, title="Pitch Locations")
    cols = [c for c in _PA_TABLE_COLS if c in sub.columns]
    tbl = tables.stat_table(sub[cols] if not sub.empty else pd.DataFrame(),
                            id="tbl-pa")
    return html.Div([
        html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                 style={"maxWidth": "560px"}),
        tbl,
    ])


def render_all_pas(game_df: pd.DataFrame) -> dcc.Graph:
    return dcc.Graph(figure=charts.all_pas_figure(game_df),
                     config={"displayModeBar": False})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py -k "plate_appearances" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/tabs/plate_appearances.py tests/test_hitting_dash.py
git commit -m "feat(hitting): Plate Appearances tab"
```

---

### Task 8: Zone Location tab

Zone-area-filtered scatter + swing/take-by-zone + plate-discipline tables.

**Files:**
- Create: `app/dashboards/hitting/tabs/zone_location.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `charts.zone_scatter`, `tables.stat_table`; `app.data.hitting.swing_decisions_by_zone`, `plate_discipline`, `SWING_CALLS`, `TAKE_CALLS`, `ZONE_LEVELS`.
- Produces:
  - `ZONE_FILTER_OPTIONS: list[dict]` — All Swings / All Takes / Heart / Shadow / Chase / Waste.
  - `render(game_df, zone_choice: str = "All Swings") -> dash.html.Div`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_dash.py`:

```python
def test_zone_location_renders_and_filters(game_df):
    from app.dashboards.hitting.tabs import zone_location as zl
    from dash import html
    assert {o["value"] for o in zl.ZONE_FILTER_OPTIONS} >= {"All Swings", "Heart"}
    assert isinstance(zl.render(game_df, "All Swings"), html.Div)
    assert isinstance(zl.render(game_df, "Heart"), html.Div)


def test_zone_location_empty_is_safe():
    from app.dashboards.hitting.tabs import zone_location as zl
    from dash import html
    assert isinstance(zl.render(pd.DataFrame(), "All Swings"), html.Div)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hitting_dash.py -k "zone_location" -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the tab**

Create `app/dashboards/hitting/tabs/zone_location.py`:

```python
"""Zone Location tab: filtered scatter + swing-decision + plate-discipline tables."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import hitting
from app.dashboards.hitting import charts, tables

ZONE_FILTER_OPTIONS = [{"label": v, "value": v} for v in
                       ["All Swings", "All Takes", "Heart", "Shadow", "Chase", "Waste"]]


def _filter(game_df: pd.DataFrame, zone_choice: str) -> pd.DataFrame:
    if game_df is None or game_df.empty:
        return pd.DataFrame(columns=getattr(game_df, "columns", None))
    if zone_choice == "All Swings":
        return game_df[game_df["PitchCall"].isin(hitting.SWING_CALLS)]
    if zone_choice == "All Takes":
        return game_df[game_df["PitchCall"].isin(hitting.TAKE_CALLS)]
    return game_df[game_df["Zone"] == zone_choice]


def render(game_df: pd.DataFrame, zone_choice: str = "All Swings") -> html.Div:
    sub = _filter(game_df, zone_choice)
    fig = charts.zone_scatter(sub, title=f"Zone Location — {zone_choice}")
    swing_dec = hitting.swing_decisions_by_zone(game_df) if game_df is not None \
        and not game_df.empty else pd.DataFrame()
    pd_zone = hitting.plate_discipline(game_df, by="zone") if game_df is not None \
        and not game_df.empty else pd.DataFrame()
    pd_pt = hitting.plate_discipline(game_df, by="pitch_type") if game_df is not None \
        and not game_df.empty else pd.DataFrame()

    def sec(title, child):
        return html.Div([html.H3(title, style={"color": "#9A0021",
                                                "margin": "16px 0 6px"}), child])

    return html.Div([
        html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                 style={"maxWidth": "560px"}),
        sec("Swing / Take by Zone", tables.stat_table(swing_dec, id="tbl-swdec")),
        sec("Plate Discipline — Area of Zone",
            tables.stat_table(pd_zone, id="tbl-pd-zone")),
        sec("Plate Discipline — Pitch Type",
            tables.stat_table(pd_pt, id="tbl-pd-pt")),
    ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py -k "zone_location" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/tabs/zone_location.py tests/test_hitting_dash.py
git commit -m "feat(hitting): Zone Location tab"
```

---

### Task 9: Layout shell (sidebar + selector + tab frame)

Assemble the static shell with all component ids and `dcc.Store`s. Reads `current_user` to scope options; passes plain values to the pure selector helpers. Replaces the placeholder `serve_layout` from Task 2.

**Files:**
- Create: `app/dashboards/hitting/layout.py`
- Modify: `app/dashboards/hitting/__init__.py` (use `layout.serve_layout`)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `selectors.hitter_options`, `selectors.game_options`, `selectors.resolve_batter`; `app.data.hitting_wh.wh_player_profile`, `wh_scoreboard`, `wh_season_qab_rate`; `flask_login.current_user`.
- Produces:
  - `sidebar(batter_id) -> html.Div` — photo placeholder + name/bats/class-year + QAB%/BA/SLG/OBP tiles (no jersey chip; photo = lion placeholder; BA/SLG/OBP = `—`).
  - `scoreboard(game_id) -> html.Div` — matchup header (date · vs/@ OPP · game type); no logo/score.
  - `serve_layout() -> html.Div` — full shell. Component ids: `hitter-dd`, `game-dd`, `tabs`, `sidebar`, `scoreboard`, and Stores `selection`, `game-data`.

Component id contract (consumed by Task 10 callbacks):
```
Dropdown  id="hitter-dd"        value = batter_id (int) | None
Dropdown  id="game-dd"          value = trackman_game_id (str) | None
dcc.Tabs  id="tabs"             value in {"game","pa","zone"}
Dropdown  id="pa-dd"            (inside PA tab content) value = "i-p"
Dropdown  id="zone-dd"          (inside Zone tab content) value = zone label
Div       id="sidebar"          (children replaced on selection)
Div       id="scoreboard"
Div       id="tab-content"      (children replaced on tab/selection change)
Store     id="selection"        data = {"batter_id": int|None, "game_id": str|None}
Store     id="game-data"        data = game_df as JSON (orient="split") | None
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_dash.py`. Layout reads `current_user`, so exercise it inside a request context with a logged-in user:

```python
def test_serve_layout_renders_for_logged_in_coach(server, monkeypatch):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    monkeypatch.setattr("app.data.hitting_wh.wh_lmu_hitters",
                        lambda: pd.DataFrame([{"Batter": "Doe, John", "BatterId": 1}]))
    monkeypatch.setattr("app.data.hitting_wh.wh_games_for_batter",
                        lambda b: pd.DataFrame(columns=["game_id", "game_date", "GameLabel"]))
    monkeypatch.setattr("app.data.hitting_wh.wh_player_profile",
                        lambda b: {"name": "Doe, John", "bats": "Right",
                                   "class_year": "Jr.", "position": "OF",
                                   "photo": "", "jersey": ""})
    monkeypatch.setattr("app.data.hitting_wh.wh_season_qab_rate", lambda b: 0.42)
    with server.app_context():
        coach = User(email="c2@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/hitting/"):
            login_user(coach)
            from app.dashboards.hitting import layout
            out = layout.serve_layout()
    # smoke: it built a component tree, not the login placeholder
    assert out is not None
    assert "Please log in" not in str(out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py -k "serve_layout" -v`
Expected: FAIL with `ModuleNotFoundError: app.dashboards.hitting.layout`.

- [ ] **Step 3: Implement the layout**

Create `app/dashboards/hitting/layout.py`:

```python
"""The hitting dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from dash import dcc, html
from flask_login import current_user

from app.data import hitting_wh
from app.dashboards.hitting import selectors

_CRIMSON = "#9A0021"
_PHOTO_PLACEHOLDER = "/static/reports/lion.png"  # until the roster-photo scrape lands


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold",
                               "color": _CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(batter_id) -> html.Div:
    if batter_id is None:
        return html.Div("Select a hitter.", style={"padding": "12px"})
    prof = hitting_wh.wh_player_profile(int(batter_id))
    qab = hitting_wh.wh_season_qab_rate(int(batter_id))
    qab_txt = f"{round(qab * 100, 1)}%" if qab is not None else "—"
    photo = prof["photo"] or _PHOTO_PLACEHOLDER
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Bats {prof['bats']}" if prof["bats"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(prof["name"] or "—",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("QAB%", qab_txt), _tile("BA", "—"),
                  _tile("SLG", "—"), _tile("OBP", "—")],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Photo/jersey + BA/SLG/OBP pending a roster/stats source.",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id) -> html.Div:
    if not game_id:
        return html.Div()
    sb = hitting_wh.wh_scoreboard(int(game_id))
    parts = [p for p in (sb["date"], f"{sb['loc']} {sb['opp']}".strip(),
                         sb["game_type"]) if p]
    return html.Div(" · ".join(parts),
                    style={"color": "white", "fontWeight": "bold",
                           "fontSize": "20px", "alignSelf": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    hitters = selectors.hitter_options(is_coach=is_coach, own_trackman_id=own)
    default_batter = selectors.resolve_batter(
        hitters[0]["value"] if hitters else None,
        is_coach=is_coach, own_trackman_id=own)
    games = selectors.game_options(default_batter)
    default_game = games[0]["value"] if games else None

    selector_row = html.Div([
        html.Div([
            html.Label("Hitter", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="hitter-dd", options=hitters, value=default_batter,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Game", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="game-dd", options=games, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": "rgba(154,0,33,0.82)"})

    tabs = dcc.Tabs(id="tabs", value="game", children=[
        dcc.Tab(label="Game Level", value="game"),
        dcc.Tab(label="Plate Appearances", value="pa"),
        dcc.Tab(label="Zone Location", value="zone"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"batter_id": default_batter,
                                        "game_id": default_game}),
        dcc.Store(id="game-data"),
        html.Div([
            html.Div(id="sidebar", children=sidebar(default_batter),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
        html.Div(html.A("← Back to home", href="/"),
                 style={"padding": "0 16px 16px"}),
    ])
```

Modify `app/dashboards/hitting/__init__.py` — replace the placeholder `serve_layout` with the real one:

```python
from dash import Dash

from app.dashboards.hitting.index import INDEX_STRING
from app.dashboards.hitting import layout

__all__ = ["build_hitting_dash", "INDEX_STRING"]


def build_hitting_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/hitting/",
        suppress_callback_exceptions=True,
        title="Hitting — The PAW",
    )
    dash_app.index_string = INDEX_STRING
    dash_app.layout = layout.serve_layout
    return dash_app
```

- [ ] **Step 4: Run test + full suite**

Run: `python -m pytest tests/test_hitting_dash.py -k "serve_layout" -v && python -m pytest -q`
Expected: new test PASSES; full suite green.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/layout.py app/dashboards/hitting/__init__.py tests/test_hitting_dash.py
git commit -m "feat(hitting): dashboard shell (sidebar + selector + tabs)"
```

---

### Task 10: Callbacks (wire selection → data → tabs)

Register the Dash callbacks that make the shell reactive. Selection updates the stores and sidebar/scoreboard/game-dd; tab + control changes render tab content from the `game-data` store.

**Files:**
- Create: `app/dashboards/hitting/callbacks.py`
- Modify: `app/dashboards/hitting/__init__.py` (call `register_callbacks(dash_app)`)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: component ids from Task 9; `selectors.resolve_batter`, `selectors.game_options`; `app.data.hitting_wh.wh_game_pitches`; `layout.sidebar`, `layout.scoreboard`; the three tab renderers. (Coach notes are legacy-keyed and not wired to warehouse games yet — pass `note=""` for now; see Deferred.)
- Produces: `register_callbacks(dash_app) -> None`. Serializes the game df to the `game-data` store via `df.to_json(orient="split")`; reads back with `pd.read_json(..., orient="split")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_dash.py`:

```python
def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.hitting import layout, callbacks, index
    app = Dash(__name__, server=server, url_base_pathname="/dash/htest/",
               suppress_callback_exceptions=True)
    app.index_string = index.INDEX_STRING
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py -k "register_callbacks" -v`
Expected: FAIL with `ModuleNotFoundError: app.dashboards.hitting.callbacks`.

- [ ] **Step 3: Implement callbacks**

Create `app/dashboards/hitting/callbacks.py`:

```python
"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import pandas as pd
from dash import Input, Output, State, dcc, html
from flask_login import current_user

from app.data import hitting_wh
from app.dashboards.hitting import layout, selectors
from app.dashboards.hitting.tabs import game_level, plate_appearances as pa, zone_location as zl


def _load_game_df(store) -> pd.DataFrame:
    if not store or store.get("game_id") is None or store.get("batter_id") is None:
        return pd.DataFrame()
    return hitting_wh.wh_game_pitches(int(store["game_id"]), int(store["batter_id"]))


def register_callbacks(dash_app) -> None:

    # Coach picks a hitter -> refresh that hitter's game options (players locked).
    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("hitter-dd", "value"),
    )
    def _on_hitter(batter_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        opts = selectors.game_options(bid)
        return opts, (opts[0]["value"] if opts else None)

    # Selection -> selection store + sidebar + scoreboard.
    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("hitter-dd", "value"), Input("game-dd", "value"),
    )
    def _on_selection(batter_id, game_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        return ({"batter_id": bid, "game_id": game_id},
                layout.sidebar(bid), layout.scoreboard(game_id))

    # Selection -> load the game pitch df into the game-data store.
    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        df = _load_game_df(sel)
        return None if df.empty else df.to_json(orient="split")

    # Tab or data change -> render the active tab.
    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        df = pd.read_json(data_json, orient="split") if data_json else pd.DataFrame()
        if tab == "game":
            # Coach notes are legacy-keyed (NOTES.GAME_ID) and don't match warehouse
            # game_ids yet; wiring notes to warehouse games is a deferred follow-up.
            return game_level.render(df, note="")
        if tab == "pa":
            choices = pa.pa_choices(df)
            return html.Div([
                dcc.Dropdown(id="pa-dd", options=choices,
                             value=(choices[0]["value"] if choices else None),
                             clearable=False, style={"maxWidth": "260px"}),
                html.Div(id="pa-breakdown"),
                html.H3("All Plate Appearances", style={"color": "#9A0021"}),
                pa.render_all_pas(df),
            ])
        if tab == "zone":
            return html.Div([
                dcc.Dropdown(id="zone-dd", options=zl.ZONE_FILTER_OPTIONS,
                             value="All Swings", clearable=False,
                             style={"maxWidth": "220px"}),
                html.Div(id="zone-body"),
            ])
        return html.Div()

    # PA dropdown -> per-PA breakdown.
    @dash_app.callback(
        Output("pa-breakdown", "children"),
        Input("pa-dd", "value"), State("game-data", "data"),
    )
    def _pa_breakdown(pa_value, data_json):
        df = pd.read_json(data_json, orient="split") if data_json else pd.DataFrame()
        return pa.render_breakdown(df, pa_value)

    # Zone dropdown -> filtered zone body.
    @dash_app.callback(
        Output("zone-body", "children"),
        Input("zone-dd", "value"), State("game-data", "data"),
    )
    def _zone_body(zone_choice, data_json):
        df = pd.read_json(data_json, orient="split") if data_json else pd.DataFrame()
        return zl.render(df, zone_choice or "All Swings")
```

Modify `app/dashboards/hitting/__init__.py` — call `register_callbacks` in `build_hitting_dash` (add import + call before `return dash_app`):

```python
    dash_app.layout = layout.serve_layout

    from app.dashboards.hitting import callbacks
    callbacks.register_callbacks(dash_app)

    return dash_app
```

- [ ] **Step 4: Run test + full suite**

Run: `python -m pytest tests/test_hitting_dash.py -k "register_callbacks" -v && python -m pytest -q`
Expected: new test PASSES; full suite green.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/callbacks.py app/dashboards/hitting/__init__.py tests/test_hitting_dash.py
git commit -m "feat(hitting): wire selection -> data -> tab callbacks"
```

---

### Task 11: Live end-to-end verification

Confirm the real page works in the browser for both roles, and the full suite passes. No new production code unless verification surfaces a defect.

**Files:**
- Modify (only if a defect is found): the relevant module above.

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: all prior tests + the new `test_hitting_dash.py` pass (baseline was 118; expect 118 + the new tests).

- [ ] **Step 2: Launch the app**

Ensure the port is free, then launch a single instance:
```bash
Get-NetTCPConnection -LocalPort 8050 -State Listen | %{ Stop-Process -Id $_.OwningProcess -Force }
```
Then in the project dir: `python run.py` (or `PYTHONIOENCODING=utf-8 python run.py` for a background/headless launch — memory §5).

- [ ] **Step 3: Verify as coach**

Log in as `coach@lmu.edu` / `paw2026`, open `http://127.0.0.1:8050/dash/hitting/`. Confirm:
- Hitter dropdown lists current LMU hitters; picking one loads that hitter's games (newest = a Spring 2026 game, default selected).
- Sidebar shows the lion photo placeholder + name + class-year/position/bats + QAB% (BA/SLG/OBP show `—`; no jersey chip).
- Scoreboard header shows date · vs/@ OPP · game type (no logo/score).
- Game Level tab: batting-line + batted-ball tables populate (no QC+/PathQ+ columns); note area shows "No note for this game."
- Plate Appearances tab: PA dropdown filters the zone scatter + pitch table; All-PAs facet renders.
- Zone Location tab: zone-area dropdown filters the scatter; swing-decision + plate-discipline tables populate (Zone rows = Heart/Shadow/Chase/Waste).

- [ ] **Step 4: Create a current demo player, then verify self-only**

The existing player demo (`ornelas@lmu.edu`, trackman 694990) is a legacy 2025 player likely absent from the warehouse. Pick a real current hitter's `batter_tm_id` and create a demo player bound to it:
```bash
python -c "from app.db import query_df; print(query_df(\"SELECT batter_tm_id, batter_name FROM fact_tm_game_pitch WHERE batter_team='LOY_LIO' GROUP BY batter_tm_id, batter_name ORDER BY COUNT(*) DESC LIMIT 1\").to_string())"
```
Create the account (substitute the id printed above):
```bash
flask --app run create-user --email hitter@lmu.edu --name "Demo Hitter" --role player --trackman-id <BATTER_TM_ID> --password paw2026
```
Log in as `hitter@lmu.edu` / `paw2026`. Confirm the hitter dropdown is disabled/locked to that player, only their games appear, and the tabs render their data. (Server-side `resolve_batter` guard is already unit-tested in Task 3.) Verify the CLI flag names against `app/cli.py` first; adjust if they differ.

- [ ] **Step 5: Commit any fixes + update memory**

If Steps 3–4 surfaced defects, fix the owning module (with a regression test where practical) and commit:
```bash
git add <fixed files>
git commit -m "fix(hitting): <what> found in live verification"
```
Update `memory/MEMORY.md`: mark the hitting slice built (shell + tabs 1–3) **on the warehouse** (`app/data/hitting_wh.py` aliases warehouse→legacy names to reuse transforms; Zone computed from coords); note the new `app/dashboards/hitting/` package structure and the new current demo player; and record the deferred items — remaining tabs (4–7), spray-assets, slash-line source, warehouse-keyed coach notes, and the **roster-photo/jersey scrape** follow-up.

---

## Self-Review

**Spec coverage:**
- §1 Architecture (package, boundaries) → Task 2 (scaffold) + module split across Tasks 3–10. ✓
- §8 Warehouse data source (aliased loaders, computed Zone, NaN QC/PathQ/Angle, batter_tm_id) → Task 1 (`hitting_wh.py`), consumed by Tasks 3/6/9/10. ✓
- §2/§8 Sidebar (photo placeholder/name/class-year/bats/QAB%/BA-SLG-OBP `—`, no jersey) + scoreboard (matchup, no logo/score) → Task 9 `sidebar`/`scoreboard`. ✓
- §2 Selector row (role-aware, batter_tm_id) → Task 3 (options/resolve) + Task 9 (controls) + Task 10 (reactivity). ✓
- §3 Game Level (QC+/PathQ+ dropped) → Task 6. ✓  Plate Appearances → Task 7 + Task 10 dropdown wiring. ✓  Zone Location (computed Zone) → Task 8 + Task 10. ✓
- §4/§8 Data flow (stores, resolve_batter self-only guard) → Task 10 + Task 3. ✓
- §5 Visual style (index_string bg/favicon, pitch colors, DataTable) → Task 2 (`index.py`), Task 4 (`PITCH_COLORS`), Task 5. ✓
- §6/§8 Testing (warehouse fixtures, role scoping, per-tab real+empty, chart/table shape) → tests in Tasks 1–10; live E2E in Task 11. ✓
- §7/§8 Deferred (tabs 4–7, spray assets, slash-line, warehouse-keyed notes, roster-photo scrape) not implemented (correct). ✓

**Placeholder scan:** No "TBD/TODO/handle edge cases" in steps; every code step shows complete code. BA/SLG/OBP `—` tiles, `note=""`, and photo/jersey placeholders are intentional deferrals (spec §8), not gaps.

**Type consistency:** `resolve_batter(requested_id, *, is_coach, own_trackman_id)` used identically in Tasks 3/9/10. `hitter_options`/`game_options` return `{"label","value"}` (value = `batter_tm_id` / `game_id` int) consistently. Task 1 produces `wh_lmu_hitters`/`wh_games_for_batter`/`wh_game_pitches`/`wh_player_profile`/`wh_scoreboard`/`wh_season_qab_rate`, consumed with matching names/args in Tasks 3/6/9/10. `wh_game_pitches` returns the aliased legacy column names the reused transforms + `charts.zone_scatter`/`all_pas_figure` (Task 4) and `tables.stat_table` (Task 5) expect. `game_level.render(df, note=...)`, `zl.render(df, zone_choice)`, `pa_choices`/`render_breakdown`/`render_all_pas` match their Task 10 callers. Store keys `batter_id` (= batter_tm_id) / `game_id` and component ids match the Task 9 id contract. df serialization uses `to_json(orient="split")` / `read_json(orient="split")` on both ends.
