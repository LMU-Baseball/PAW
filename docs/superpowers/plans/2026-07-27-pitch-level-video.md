# Pitch-Level Video Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared pitch-level Video tab (clickable pitch table + single video player with an angle toggle) to the hitting, pitching, and catching dashboards, backed by the warehouse `vw_pitch_video` view.

**Architecture:** One data helper (`app/data/video.py`) returns one row per pitch with the four camera-angle S3 URLs pivoted into columns. One shared Dash component (`app/dashboards/video/`) renders the table + player and registers its callbacks under a per-dashboard id prefix (`hit`/`pit`/`cat`), mirroring the existing `notes_ui.register_note_callbacks(dash_app, module, key)` pattern. Each dashboard adds a tab, a render branch, and one `register_callbacks` call.

**Tech Stack:** Python, Flask, Dash (`dash_table.DataTable`, `html.Video`, pattern-matching callbacks), pandas, SQLAlchemy (`app.db.query_df`), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-27-pitch-level-video-design.md`. Branch: `feat/pitch-level-video`.
- Data source: `vw_pitch_video v` JOIN `fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid`. Four angles: `HomeBehind`, `HomeRight`, `HomeLeft`, `Broadcast`.
- Subject id columns differ per module: hitting filters `f.batter_tm_id` (siblings via `hitting_wh._sibling_ids`); pitching filters `f.pitcher_id` (siblings via `pitching._sibling_pitcher_ids`); catching filters `f.catcher_id` (siblings via `catching._sibling_catcher_ids`).
- All three Dash apps set `suppress_callback_exceptions=True` (dynamic tab components are OK).
- Selection store keys: hitting `batter_id`, pitching `pitcher_id`, catching `catcher_id`; every store also has `game_id`, `start`, `end`; the "all games in range" sentinel is `app.dashboards.date_range.ALL_IN_RANGE`.
- Colors: crimson `#9A0021`. Fonts: `Teko, sans-serif`. Match existing table styling (`app/dashboards/pitching/tables.py`).
- Tests run against the live warehouse (repo convention; matches `tests/test_pitching_dash.py`). Full suite must stay green (currently 314). Run: `python -m pytest -q`.
- Video exists only for Spring-2026 games (37 games). Non-video games/seasons must degrade to a clean empty state, never an exception.

---

### Task 1: Data helper `app/data/video.py`

**Files:**
- Create: `app/data/video.py`
- Test: `tests/test_video.py`

**Interfaces:**
- Consumes: `app.db.query_df`; `app.data.hitting_wh._sibling_ids`, `app.data.pitching._sibling_pitcher_ids`, `app.data.catching._sibling_catcher_ids` (imported lazily inside the function to avoid import cycles).
- Produces:
  - `ANGLES: list[tuple[str,str]]` = `[("HomeBehind","Behind"),("HomeRight","Home R"),("HomeLeft","Home L"),("Broadcast","Broadcast")]`
  - `URL_COL: dict[str,str]` mapping each angle key → its url column (`"HomeBehind"→"url_homebehind"`, etc.)
  - `DISPLAY_COLS: list[str]` = `["Pitch","Inn","Count","Type","Velo","Result","Zone","Date"]`
  - `pitch_video_df(game_id, *, batter_id=None, pitcher_id=None, catcher_id=None) -> pd.DataFrame` — `game_id` is an int or a list of ints; exactly one subject kwarg is given. Returns one row per pitch with columns: the 8 `DISPLAY_COLS` (strings; NaN → "—"), the 4 url columns (`url_homebehind/right/left/broadcast`; None where missing), plus `batter_side` and `pitch_uid`. Empty (but full-column) frame when no video.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video.py
"""Live-DB tests for the pitch-video data helper."""
import pandas as pd
import pytest

from app.data import video
from app.db import query_df


@pytest.fixture(scope="module")
def sample():
    """A (game_id, pitcher_id, batter_id, catcher_id) that has video."""
    row = query_df(
        """
        SELECT f.game_id, f.pitcher_id, f.batter_tm_id, f.catcher_id
          FROM vw_pitch_video v
          JOIN fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid
         WHERE f.catcher_id IS NOT NULL AND f.batter_tm_id IS NOT NULL
         LIMIT 1
        """
    ).iloc[0]
    return dict(game_id=int(row["game_id"]), pitcher_id=int(row["pitcher_id"]),
                batter_tm_id=int(row["batter_tm_id"]), catcher_id=int(row["catcher_id"]))


def test_constants_shape():
    assert [a for a, _ in video.ANGLES] == ["HomeBehind", "HomeRight", "HomeLeft", "Broadcast"]
    assert video.URL_COL["HomeBehind"] == "url_homebehind"
    assert video.DISPLAY_COLS[0] == "Pitch"


def test_pitcher_filter_one_row_per_pitch(sample):
    df = video.pitch_video_df(sample["game_id"], pitcher_id=sample["pitcher_id"])
    assert not df.empty
    # one row per pitch (pivoted), not one per (pitch, angle)
    assert df["pitch_uid"].is_unique
    for col in video.DISPLAY_COLS:
        assert col in df.columns
    for a in video.URL_COL.values():
        assert a in df.columns
    # at least one angle url present somewhere
    assert df[list(video.URL_COL.values())].notna().any().any()


def test_batter_and_catcher_filters(sample):
    b = video.pitch_video_df(sample["game_id"], batter_id=sample["batter_tm_id"])
    c = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_id"])
    assert not b.empty and b["pitch_uid"].is_unique
    assert not c.empty and c["pitch_uid"].is_unique


def test_game_id_list_unions(sample):
    one = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_id"])
    many = video.pitch_video_df([sample["game_id"]], catcher_id=sample["catcher_id"])
    assert len(one) == len(many)


def test_empty_game_returns_full_columns(sample):
    df = video.pitch_video_df(-1, pitcher_id=sample["pitcher_id"])
    assert df.empty
    assert list(df.columns)  # full column set present
    assert "Pitch" in df.columns and "url_homebehind" in df.columns


def test_requires_exactly_one_subject(sample):
    with pytest.raises(ValueError):
        video.pitch_video_df(sample["game_id"])
    with pytest.raises(ValueError):
        video.pitch_video_df(sample["game_id"], pitcher_id=1, batter_id=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video.py -q`
Expected: FAIL (`ModuleNotFoundError: app.data.video`).

- [ ] **Step 3: Write the implementation**

```python
# app/data/video.py
"""Pitch-level video: one row per pitch with the four camera-angle S3 URLs.

Source = vw_pitch_video (public S3 .mp4 urls, Spring 2026 onward) joined to
fact_tm_game_pitch on pitch_uid for the surrogate game_id, catcher_id, velo,
plate zone, and batter_side that the video view does not carry.
"""
from __future__ import annotations

import re

import pandas as pd

from app.db import query_df

ANGLES: list[tuple[str, str]] = [
    ("HomeBehind", "Behind"), ("HomeRight", "Home R"),
    ("HomeLeft", "Home L"), ("Broadcast", "Broadcast"),
]
URL_COL: dict[str, str] = {a: f"url_{a.lower()}" for a, _ in ANGLES}
DISPLAY_COLS: list[str] = ["Pitch", "Inn", "Count", "Type", "Velo", "Result", "Zone", "Date"]

_ALL_COLS = DISPLAY_COLS + list(URL_COL.values()) + ["batter_side", "pitch_uid"]

_RESULT_MAP = {
    "StrikeCalled": "Called Strike", "StrikeSwinging": "Swing & Miss",
    "BallCalled": "Ball", "BallinDirt": "Ball (dirt)", "BallIntentional": "IBB",
    "AutomaticBall": "Auto Ball", "AutomaticStrike": "Auto Strike",
    "FoulBallNotFieldable": "Foul", "FoulBallFieldable": "Foul", "HitByPitch": "HBP",
    "InPlay": "In Play",
}


def _spaced(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s))


def _result(pitch_call, play_result) -> str:
    pr = None if play_result is None else str(play_result)
    if pr and pr not in ("Undefined", "None", ""):
        return _spaced(pr)
    return _RESULT_MAP.get(str(pitch_call), _spaced(pitch_call))


def _sibling_ids(*, batter_id, pitcher_id, catcher_id):
    """(subject fact column, sibling id list) for whichever subject was passed."""
    given = [("batter_tm_id", batter_id, "app.data.hitting_wh", "_sibling_ids"),
             ("pitcher_id", pitcher_id, "app.data.pitching", "_sibling_pitcher_ids"),
             ("catcher_id", catcher_id, "app.data.catching", "_sibling_catcher_ids")]
    active = [(col, val, mod, fn) for col, val, mod, fn in given if val is not None]
    if len(active) != 1:
        raise ValueError("pass exactly one of batter_id / pitcher_id / catcher_id")
    col, val, mod, fn = active[0]
    import importlib
    sib = getattr(importlib.import_module(mod), fn)(int(val))
    return col, [int(x) for x in sib]


def pitch_video_df(game_id, *, batter_id=None, pitcher_id=None, catcher_id=None) -> pd.DataFrame:
    """One row per pitch (angles pivoted to url columns) for a game (or list of
    games) and one subject. Empty full-column frame when there is no video."""
    gids = [int(g) for g in (game_id if isinstance(game_id, (list, tuple)) else [game_id])]
    subj_col, sib = _sibling_ids(batter_id=batter_id, pitcher_id=pitcher_id, catcher_id=catcher_id)

    gph = ", ".join(f":g{i}" for i in range(len(gids)))
    sph = ", ".join(f":s{i}" for i in range(len(sib)))
    params = {f"g{i}": g for i, g in enumerate(gids)}
    params.update({f"s{i}": s for i, s in enumerate(sib)})

    raw = query_df(
        f"""
        SELECT v.pitch_uid, v.pitch_no, v.inning, v.balls, v.strikes,
               v.tagged_pitch_type, v.pitch_call, v.play_result, v.game_date,
               v.angle, v.s3_url,
               f.rel_speed, f.izt_zone, f.batter_side
          FROM vw_pitch_video v
          JOIN fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid
         WHERE f.game_id IN ({gph}) AND f.{subj_col} IN ({sph})
        """,
        params,
    )
    if raw.empty:
        return pd.DataFrame(columns=_ALL_COLS)

    # Pivot angle -> url column (one row per pitch_uid).
    urls = (raw.pivot_table(index="pitch_uid", columns="angle", values="s3_url",
                            aggfunc="first")
               .reindex(columns=[a for a, _ in ANGLES]))
    urls.columns = [URL_COL[a] for a in urls.columns]

    meta = (raw.drop_duplicates("pitch_uid")
               .set_index("pitch_uid"))
    out = meta.join(urls)

    zone = out["izt_zone"].astype("object").where(out["izt_zone"].notna(), None)
    df = pd.DataFrame({
        "Pitch": out["pitch_no"].astype("Int64"),
        "Inn": out["inning"].astype("Int64"),
        "Count": out["balls"].astype("Int64").astype(str) + "-" + out["strikes"].astype("Int64").astype(str),
        "Type": out["tagged_pitch_type"],
        "Velo": out["rel_speed"].round(1).map(lambda v: "—" if pd.isna(v) else f"{v:.1f}"),
        "Result": [_result(pc, pr) for pc, pr in zip(out["pitch_call"], out["play_result"])],
        "Zone": [("—" if z is None else str(z)) for z in zone],
        "Date": out["game_date"].astype(str),
    })
    for a in URL_COL.values():
        df[a] = out[a].where(out[a].notna(), None).values
    df["batter_side"] = out["batter_side"].values
    df["pitch_uid"] = out.index.values
    df = df.sort_values(["Date", "Pitch"], ascending=[False, True]).reset_index(drop=True)
    return df[_ALL_COLS]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_video.py -q`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add app/data/video.py tests/test_video.py
git commit -m "feat(video): pitch_video_df data helper (angles pivoted per pitch)"
```

---

### Task 2: Shared UI component `app/dashboards/video/`

**Files:**
- Create: `app/dashboards/video/__init__.py`
- Create: `app/dashboards/video/component.py`
- Test: `tests/test_video_component.py`

**Interfaces:**
- Consumes: `app.data.video` (`ANGLES`, `URL_COL`, `DISPLAY_COLS`, `pitch_video_df` output shape).
- Produces (re-exported from the package `__init__`):
  - `render(df, *, prefix, default_angle) -> html.Div` — `default_angle` is an angle key (e.g. `"HomeBehind"`) or the literal `"batter_side"` (resolve per pitch from `batter_side`). Ids: `f"{prefix}-video-table"`, `f"{prefix}-video-player"`, `f"{prefix}-video-hint"`, stores `f"{prefix}-video-pitch"` / `f"{prefix}-video-angle"`, buttons `{"type": f"{prefix}-angle", "index": <angle key>}`.
  - `register_callbacks(dash_app, prefix, default_angle="HomeBehind") -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_component.py
"""Render-smoke tests for the shared video component (no live DB needed)."""
import pandas as pd
from dash import dash_table, html

from app.dashboards import video as vc
from app.data import video as vdata


def _df():
    row = {c: "x" for c in vdata.DISPLAY_COLS}
    row.update({vdata.URL_COL[a]: (f"http://x/{a}.mp4" if a != "Broadcast" else None)
                for a, _ in vdata.ANGLES})
    row.update({"batter_side": "Right", "pitch_uid": "u1"})
    return pd.DataFrame([row])


def _walk(node):
    yield node
    for child in (getattr(getattr(node, "children", None), "__iter__", lambda: [])()
                  if isinstance(getattr(node, "children", None), (list, tuple))
                  else ([node.children] if getattr(node, "children", None) is not None else [])):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def test_empty_df_shows_empty_state():
    out = vc.render(pd.DataFrame(columns=vdata._ALL_COLS), prefix="pit", default_angle="HomeBehind")
    text = str(out)
    assert "No video" in text


def test_render_has_table_player_and_angle_buttons():
    out = vc.render(_df(), prefix="pit", default_angle="HomeBehind")
    ids = [getattr(n, "id", None) for n in _walk(out)]
    assert "pit-video-table" in ids
    assert "pit-video-player" in ids
    # four angle buttons as pattern-matching dict ids
    btns = [i for i in ids if isinstance(i, dict) and i.get("type") == "pit-angle"]
    assert len(btns) == 4


def test_table_hides_url_columns_but_keeps_them_in_data():
    out = vc.render(_df(), prefix="hit", default_angle="batter_side")
    table = next(n for n in _walk(out)
                 if isinstance(n, dash_table.DataTable) and n.id == "hit-video-table")
    shown = [c["id"] for c in table.columns]
    assert shown == vdata.DISPLAY_COLS          # only display columns shown
    assert "url_homebehind" in table.data[0]    # url still present in row data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_component.py -q`
Expected: FAIL (`ModuleNotFoundError: app.dashboards.video`).

- [ ] **Step 3: Write the implementation**

```python
# app/dashboards/video/component.py
"""Shared pitch-level video tab: pitch table + one player + angle toggle."""
from __future__ import annotations

import pandas as pd
from dash import ALL, Input, Output, State, ctx, dash_table, dcc, html, no_update

from app.data.video import ANGLES, DISPLAY_COLS, URL_COL

CRIMSON = "#9A0021"


def _btn_style(has: bool, on: bool) -> dict:
    return {"border": f"2px solid {CRIMSON}",
            "background": CRIMSON if on else "#fff",
            "color": "#fff" if on else (CRIMSON if has else "#bbb"),
            "borderRadius": "14px", "padding": "4px 14px", "margin": "0 6px 0 0",
            "cursor": "pointer" if has else "not-allowed", "opacity": "1" if has else ".5",
            "fontFamily": "Teko, sans-serif", "fontSize": "15px"}


def render(df: pd.DataFrame, *, prefix: str, default_angle: str) -> html.Div:
    if df is None or df.empty:
        return html.Div("No video available for this selection.",
                        style={"padding": "16px", "color": "#555",
                               "fontFamily": "Teko, sans-serif", "fontSize": "18px"})
    table = dash_table.DataTable(
        id=f"{prefix}-video-table",
        columns=[{"name": c, "id": c} for c in DISPLAY_COLS],
        data=df.to_dict("records"),          # includes hidden url_* + batter_side + pitch_uid
        page_size=15, sort_action="native", filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": CRIMSON, "color": "white", "fontWeight": "bold"},
        style_data_conditional=[{"if": {"state": "active"},
                                 "backgroundColor": "rgba(154,0,33,.15)",
                                 "border": f"1px solid {CRIMSON}"}],
    )
    buttons = [html.Button(label, id={"type": f"{prefix}-angle", "index": key},
                           n_clicks=0, style=_btn_style(True, False))
               for key, label in ANGLES]
    player = html.Video(id=f"{prefix}-video-player", src="", controls=True,
                        autoPlay=True, muted=True, loop=True,
                        style={"width": "100%", "borderRadius": "8px", "background": "#000"})
    return html.Div([
        dcc.Store(id=f"{prefix}-video-pitch"),
        dcc.Store(id=f"{prefix}-video-angle"),
        html.Div([
            html.Div([html.Div("Click a pitch to load video",
                               style={"color": "#555", "marginBottom": "4px"}), table],
                     style={"flex": "1", "minWidth": "340px"}),
            html.Div([
                html.Div(buttons, style={"marginBottom": "8px"}),
                html.Div("Click a pitch row to load video.", id=f"{prefix}-video-hint",
                         style={"color": "#555", "marginBottom": "6px"}),
                player,
            ], style={"flex": "1", "minWidth": "360px"}),
        ], style={"display": "flex", "gap": "16px", "alignItems": "flex-start"}),
    ])


def _resolve_default(pitch: dict | None, default_angle: str) -> str:
    urls = (pitch or {}).get("urls") or {}
    side = (pitch or {}).get("side")
    if default_angle == "batter_side":
        order = ["HomeRight" if side == "Right" else "HomeLeft", "HomeBehind", "Broadcast"]
    else:
        order = [default_angle]
    order += [k for k, _ in ANGLES if k not in order]
    for k in order:
        if urls.get(k):
            return k
    return "HomeBehind" if default_angle == "batter_side" else default_angle


def register_callbacks(dash_app, prefix: str, default_angle: str = "HomeBehind") -> None:

    @dash_app.callback(
        Output(f"{prefix}-video-pitch", "data"),
        Input(f"{prefix}-video-table", "active_cell"),
        State(f"{prefix}-video-table", "derived_viewport_data"),
        prevent_initial_call=True,
    )
    def _select(active, rows):
        if not active or not rows:
            return no_update
        i = active.get("row")
        if i is None or i >= len(rows):
            return no_update
        row = rows[i]
        return {"urls": {k: row.get(URL_COL[k]) for k, _ in ANGLES},
                "side": row.get("batter_side")}

    @dash_app.callback(
        Output(f"{prefix}-video-angle", "data"),
        Input(f"{prefix}-video-pitch", "data"),
        Input({"type": f"{prefix}-angle", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _angle(pitch, _clicks):
        trig = ctx.triggered_id
        if isinstance(trig, dict):
            return trig["index"]
        return _resolve_default(pitch, default_angle)

    @dash_app.callback(
        Output(f"{prefix}-video-player", "src"),
        Output(f"{prefix}-video-hint", "children"),
        Input(f"{prefix}-video-pitch", "data"),
        Input(f"{prefix}-video-angle", "data"),
    )
    def _src(pitch, angle):
        if not pitch:
            return "", "Click a pitch row to load video."
        url = ((pitch.get("urls") or {}).get(angle)) or ""
        return (url, "") if url else ("", "No video for this angle.")

    @dash_app.callback(
        Output({"type": f"{prefix}-angle", "index": ALL}, "disabled"),
        Output({"type": f"{prefix}-angle", "index": ALL}, "style"),
        Input(f"{prefix}-video-pitch", "data"),
        Input(f"{prefix}-video-angle", "data"),
        State({"type": f"{prefix}-angle", "index": ALL}, "id"),
    )
    def _btn_states(pitch, angle, ids):
        urls = (pitch or {}).get("urls") or {}
        disabled, styles = [], []
        for i in ids:
            key = i["index"]
            has = bool(urls.get(key))
            disabled.append(not has)
            styles.append(_btn_style(has, key == angle and has))
        return disabled, styles
```

```python
# app/dashboards/video/__init__.py
"""Shared pitch-level video tab component (used by hitting/pitching/catching)."""
from app.dashboards.video.component import register_callbacks, render

__all__ = ["render", "register_callbacks"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_component.py -q`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/video/ tests/test_video_component.py
git commit -m "feat(video): shared video-tab component (table + player + angle toggle)"
```

---

### Task 3: Wire into the Pitching dashboard

**Files:**
- Modify: `app/dashboards/pitching/layout.py` (tabs list, ~line 105-110)
- Modify: `app/dashboards/pitching/callbacks.py` (`_render_tab`, and `register_callbacks` tail ~line 215)
- Test: `tests/test_pitching_dash.py` (append)

**Interfaces:**
- Consumes: `app.dashboards.video` (`render`, `register_callbacks`); `app.data.video.pitch_video_df`; `P.games_for_pitcher`; `dr.ALL_IN_RANGE`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pitching_dash.py`)

```python
def test_pitchlevel_tab_renders_video_component():
    from app.dashboards.video.component import render as vrender
    import pandas as pd
    from app.data import video as vdata
    # empty-video game -> empty state (no exception)
    out = vrender(pd.DataFrame(columns=vdata._ALL_COLS), prefix="pit", default_angle="HomeBehind")
    assert "No video" in str(out)


def test_pitching_tabs_include_pitch_level():
    from app.dashboards.pitching import layout
    # serve_layout builds under an app/request context in other tests; here just
    # assert the tab value string is wired in the module source.
    import inspect
    src = inspect.getsource(layout.serve_layout)
    assert '"pitchlevel"' in src and "Pitch Level" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py -k "pitch_level or pitchlevel" -q`
Expected: FAIL (`"pitchlevel"` not in `serve_layout` source).

- [ ] **Step 3: Implement the wiring**

In `app/dashboards/pitching/layout.py`, add the tab (after the `Last Outings` tab):

```python
    tabs = dcc.Tabs(id="tabs", value="breakdown", children=[
        dcc.Tab(label="Pitch Breakdown", value="breakdown"),
        dcc.Tab(label="Location / Movement", value="location"),
        dcc.Tab(label="RHH v. LHH", value="splits"),
        dcc.Tab(label="Last Outings", value="outings"),
        dcc.Tab(label="Pitch Level", value="pitchlevel"),
    ])
```

In `app/dashboards/pitching/callbacks.py`, add the import at the top:

```python
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.data import video as videodata
```

Add a `pitchlevel` branch in `_render_tab` **before** the `df.empty` guard (alongside the `outings` branch), because it reads `sel` not `game-data`:

```python
        if tab == "pitchlevel":
            sel = sel or {}
            pid = sel.get("pitcher_id")
            if pid is None:
                return html.Div("Select a pitcher.", style={"padding": "12px", "color": "#555"})
            gid = sel.get("game_id")
            if gid == dr.ALL_IN_RANGE:
                g = P.games_for_pitcher(int(pid), start=sel.get("start"), end=sel.get("end"))
                gids = [int(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select an outing.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [int(gid)]
            vdf = videodata.pitch_video_df(gids, pitcher_id=int(pid))
            return videotab.render(vdf, prefix="pit", default_angle="HomeBehind")
```

Register the callbacks at the end of `register_callbacks` (next to the notes line):

```python
    videotab.register_callbacks(dash_app, "pit", default_angle="HomeBehind")
    notes_ui.register_note_callbacks(dash_app, "pitching", "pitcher_id")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/pitching/layout.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(video): add Pitch Level video tab to pitching dashboard"
```

---

### Task 4: Wire into the Hitting dashboard

**Files:**
- Modify: `app/dashboards/hitting/layout.py` (tabs list, ~line 109-113)
- Modify: `app/dashboards/hitting/callbacks.py` (`_render_tab` ~line 101, `register_callbacks` tail ~line 142)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `app.dashboards.video`; `app.data.video.pitch_video_df`; `hitting_wh.wh_games_for_batter`; `selectors.resolve_batter` is not needed here (sel already carries the resolved `batter_id`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_hitting_dash.py`)

```python
def test_hitting_tabs_include_video():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"video"' in src and "Video" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py -k video -q`
Expected: FAIL.

- [ ] **Step 3: Implement the wiring**

In `app/dashboards/hitting/layout.py`, add the tab:

```python
    tabs = dcc.Tabs(id="tabs", value="game", children=[
        dcc.Tab(label="Game Level", value="game"),
        dcc.Tab(label="Plate Appearances", value="pa"),
        dcc.Tab(label="Zone Location", value="zone"),
        dcc.Tab(label="Video", value="video"),
    ])
```

In `app/dashboards/hitting/callbacks.py`, add imports:

```python
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.data import hitting_wh
from app.data import video as videodata
```

Add a `video` branch at the **top** of `_render_tab` (it uses `sel`, not `df`):

```python
        if tab == "video":
            sel = sel or {}
            bid = sel.get("batter_id")
            if bid is None:
                return html.Div("Select a hitter.", style={"padding": "12px", "color": "#555"})
            gid = sel.get("game_id")
            if gid == dr.ALL_IN_RANGE:
                g = hitting_wh.wh_games_for_batter(int(bid), start=sel.get("start"), end=sel.get("end"))
                gids = [int(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select a game.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [int(gid)]
            vdf = videodata.pitch_video_df(gids, batter_id=int(bid))
            return videotab.render(vdf, prefix="hit", default_angle="batter_side")
```

Register callbacks at the end of `register_callbacks`:

```python
    videotab.register_callbacks(dash_app, "hit", default_angle="batter_side")
    notes_ui.register_note_callbacks(dash_app, "hitting", "batter_id")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/layout.py app/dashboards/hitting/callbacks.py tests/test_hitting_dash.py
git commit -m "feat(video): add Video tab to hitting dashboard"
```

---

### Task 5: Wire into the Catching dashboard

**Files:**
- Modify: `app/dashboards/catching/layout.py` (tabs list, ~line 105-109)
- Modify: `app/dashboards/catching/callbacks.py` (`_render_tab` signature + branch ~line 86-101, `register_callbacks` tail ~line 194)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `app.dashboards.video`; `app.data.video.pitch_video_df`; `C.games_for_catcher`; `dr.ALL_IN_RANGE`.
- Note: catching's `_render_tab` currently takes only `(tab, data_json)` and returns early on empty df. Add `State("selection", "data")` and handle `pitchlevel` **before** the empty guard.

- [ ] **Step 1: Write the failing test** (append to `tests/test_catching_dash.py`)

```python
def test_catching_tabs_include_pitch_level():
    import inspect
    from app.dashboards.catching import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"pitchlevel"' in src and "Pitch Level" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k pitch_level -q`
Expected: FAIL.

- [ ] **Step 3: Implement the wiring**

In `app/dashboards/catching/layout.py`, add the tab:

```python
    tabs = dcc.Tabs(id="tabs", value="framing", children=[
        dcc.Tab(label="Overall Framing", value="framing"),
        dcc.Tab(label="Static Framing", value="static"),
        dcc.Tab(label="Caught Stealing", value="caught"),
        dcc.Tab(label="Pitch Level", value="pitchlevel"),
    ])
```

In `app/dashboards/catching/callbacks.py`, add imports:

```python
from app.dashboards import date_range as dr, notes_ui, video as videotab
from app.data import video as videodata
```

Replace the `_render_tab` callback so it also receives `selection` and handles `pitchlevel` before the empty-df guard:

```python
    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        if tab == "pitchlevel":
            sel = sel or {}
            cid = sel.get("catcher_id")
            if cid is None:
                return html.Div("Select a catcher.", style={"padding": "12px", "color": "#555"})
            gid = sel.get("game_id")
            if gid == dr.ALL_IN_RANGE:
                g = C.games_for_catcher(int(cid), start=sel.get("start"), end=sel.get("end"))
                gids = [int(x) for x in g["game_id"]] if not g.empty else []
            elif gid is None:
                return html.Div("Select a game.", style={"padding": "12px", "color": "#555"})
            else:
                gids = [int(gid)]
            vdf = videodata.pitch_video_df(gids, catcher_id=int(cid))
            return videotab.render(vdf, prefix="cat", default_angle="HomeBehind")
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "framing":
            return framing.render(df)
        if tab == "static":
            return static_framing.render(df)
        if tab == "caught":
            return caught_stealing.render(df)
        return html.Div()
```

Register callbacks at the end of `register_callbacks`:

```python
    videotab.register_callbacks(dash_app, "cat", default_angle="HomeBehind")
    notes_ui.register_note_callbacks(dash_app, "catching", "catcher_id")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching_dash.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/layout.py app/dashboards/catching/callbacks.py tests/test_catching_dash.py
git commit -m "feat(video): add Pitch Level video tab to catching dashboard"
```

---

### Task 6: Full-suite + live smoke

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: all green (was 314; now +~10 new tests).

- [ ] **Step 2: In-process live smoke** (do NOT disturb any running :8050 server — use a fresh in-process app, per memory §3b)

```python
# scratchpad smoke: build each dash, render the video tab for a game known to have video
from app import create_app
app = create_app()
from app.data import video
df = video.pitch_video_df(58, pitcher_id=50)  # a Spring-2026 game w/ video
assert not df.empty and df["pitch_uid"].is_unique
print("video rows:", len(df), "angles present:",
      [c for c in df.columns if c.startswith("url_")])
```

Expected: prints a non-empty row count and the four url columns.

- [ ] **Step 3: Commit any smoke fixes** (only if needed), else proceed.

---

## Notes for the implementer
- Keep video URLs OUT of the DataTable `columns` (so they don't display) but IN the row `data` — the row-select callback reads them from `derived_viewport_data`.
- `active_cell["row"]` is viewport-relative, so read `derived_viewport_data` (current page), not `derived_virtual_data`.
- The pattern-matching angle buttons + stores live inside the tab content, which only exists when the tab is active; that's why `suppress_callback_exceptions=True` (already set) is required.
- Do not add a coach-note card to the video tab (notes stay on the analytical tabs).
