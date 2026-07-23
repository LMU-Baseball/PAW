# Pitching Dashboard — Slice 2 (refinements + roster media fix) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Apply coach-feedback refinements to the pitching dashboard (velo chart, pitch-type chip filter, hover result, splits coloring, configurable Last Outings + velo trend), add back-links to Jinja pages, and fix the roster photo/jersey mismatch.

**Architecture:** Modify the existing `app/dashboards/pitching/` tabs + `app/data/pitching.py` Plotly figure builders (which are NOT used by the shipped one-pager report). Add pattern-matching Dash callbacks for the chip filters. Fix `scripts/scrape_roster_media.py` to cover pitchers with collision-aware, confident-only matching; the controller re-runs the scrape.

**Tech Stack:** Flask/Jinja, Dash (Plotly), pandas, MySQL Trackman warehouse, pytest.

## Global Constraints

- Warehouse-only; LMU-only (`P.LMU_PITCHER_TEAM='LOY_LIO'`, `P.LMU_TEAM_ID=78`).
- Role gating unchanged — chips/dropdowns are display filters, NOT security boundaries.
- Brand via `app/dashboards/shell.py`; no CDN. Crimson `#9A0021`, blue `#0076A5`.
- Pitch type via `P.pitch_type(df)`. Pitch→color via the new `P.pitch_color(pt)` (Task 3).
- The Plotly `fig_*` builders in `app/data/pitching.py` are unused by the shipped report — safe to modify for the dashboard.
- Dash: pattern-matching callbacks use `dash.ctx.triggered_id` (Dash ≥2.4 — this repo's Dash supports it; `dash_table.DataTable` deprecation warnings are pre-existing/expected).
- Run: `python run.py` → http://127.0.0.1:8050 (headless: prefix `PYTHONIOENCODING=utf-8`). The dev server is ALREADY RUNNING on 8050 during this work — Python edits need a restart (kill by **port owner**, not name: `Get-NetTCPConnection -LocalPort 8050 -State Listen | %{ Stop-Process -Id $_.OwningProcess -Force }`), templates/CSS auto-reload. Implementers must NOT start/stop the server — the controller owns it.
- Tests: full suite currently 183 passing; keep green. Live-DB tests follow the existing unguarded convention.

---

## File Structure

**Modify:**
- `scripts/scrape_roster_media.py` — cover pitchers; collision-aware; confident-only (Task 2).
- `app/templates/reports/pitching_landing.html` (+ any hub-child template missing a back link) (Task 1).
- `app/data/pitching.py` — `pitch_color`, `pretty_result`; per-outing velo x-axis; color-by-type + result-hover figures; outings velo-trend figure; `last_n_outings` helper (Tasks 3–6).
- `app/dashboards/pitching/tabs/{pitch_breakdown,location_movement,rhh_lhh,last_outings}.py` (Tasks 3–6).
- `app/dashboards/pitching/callbacks.py` — chip-filter + outings-count callbacks (Tasks 4–6).
- `tests/test_pitching.py`, `tests/test_pitching_dash.py`.

---

## Task 1: Back-links on Jinja pages

**Files:**
- Modify: `app/templates/reports/pitching_landing.html`
- Test: `tests/test_pitching_landing.py`

**Interfaces:** none produced.

- [ ] **Step 1: Write the failing test.** Add to `tests/test_pitching_landing.py` (reuse its existing logged-in client fixture):

```python
def test_pitching_landing_has_back_link(logged_in_client):
    r = logged_in_client.get("/reports/pitching")
    assert r.status_code == 200
    assert b'href="/pitching"' in r.data  # back to the Pitching hub
```

- [ ] **Step 2: Run it — expect FAIL** (no back link yet).
Run: `python -m pytest tests/test_pitching_landing.py::test_pitching_landing_has_back_link -v`

- [ ] **Step 3: Add the back link.** Near the top of the content block in `app/templates/reports/pitching_landing.html`, add (matching the hub pages' style):

```jinja
<p><a href="{{ url_for('main.pitching') }}">← Back to Pitching</a></p>
```

Place it as the first element inside the main content (before the hero/picker). If the template has a hero wrapper, put the link immediately above it.

- [ ] **Step 4: Audit other hub-child Jinja templates.** Grep `app/templates` for templates rendered by a logged-in route that lack a `← Back` link. The hub pages (`pitching_hub.html`/`hitting_hub.html`/`catching_hub.html`) already have "← Back to home" (Slice 1) — leave them. Only `pitching_landing.html` is expected to need the fix; if the grep finds another, add the same link to its logical parent and note it in the report.

Run: `python -m pytest tests/test_pitching_landing.py -v` → expect PASS.

- [ ] **Step 5: Commit.**
```bash
git add app/templates/reports/pitching_landing.html tests/test_pitching_landing.py
git commit -m "feat(nav): back link on the pitching reports landing page"
```

---

## Task 2: Roster media fix (cover pitchers, collision-aware, confident-only)

**Files:**
- Modify: `scripts/scrape_roster_media.py`
- Test: `tests/test_roster_media.py`

**Interfaces:**
- Produces: `scrape_roster_media.lmu_players() -> list[tuple[int, str, int]]` (raw_tm_id, name, n_pitches) unioning batters + pitchers; `build_media(players, roster_cards)` now takes the id/name/weight tuples and resolves same-id collisions by max weight. `player_media(id)` / `roster_media.json` shape UNCHANGED.

**Context:** `roster_media.json` is `{ "<raw_tm_id>": {"jersey","photo_url","name"} }`. Today only hitters are fed in, keyed by `batter_tm_id`; pitchers resolve against a hitter-only map and can inherit a wrong id (Bender's `832473` → Malone stray). Fix = feed BOTH sides, keyed by raw tm id, dominant-identity wins.

- [ ] **Step 1: Write the failing test.** Add to `tests/test_roster_media.py` (runs against the live DB + network via the script's helpers; mirror the file's existing style — if it guards network, follow that guard):

```python
def test_lmu_players_includes_pitchers():
    from scripts import scrape_roster_media as s
    players = s.lmu_players()
    assert players and len(players[0]) == 3  # (id, name, n_pitches)
    names = {n for _, n, _ in players}
    # A known LMU pitcher name is present in the union (not hitters-only).
    assert any("Bender" in n for n in names)


def test_build_media_prefers_dominant_identity():
    from scripts import scrape_roster_media as s
    cards = [
        {"name": "Zach Bender", "jersey": "42", "photo_url": "bender.jpg"},
        {"name": "Noah Malone", "jersey": "4", "photo_url": "malone.jpg"},
    ]
    # Same raw id 832473 claimed by a 1-pitch Malone stray AND the full Bender pitcher.
    players = [(832473, "Malone, Noah", 1), (832473, "Bender, Zachary", 500),
               (832474, "Malone, Noah", 300)]
    media, _, _ = s.build_media(players, cards)
    assert media["832473"]["name"] == "Zach Bender"   # dominant identity won
    assert media["832473"]["jersey"] == "42"
    assert media["832474"]["name"] == "Noah Malone"
```

- [ ] **Step 2: Run — expect FAIL** (`lmu_players` missing; `build_media` signature differs).
Run: `python -m pytest tests/test_roster_media.py -k "lmu_players or dominant_identity" -v`

- [ ] **Step 3: Replace `lmu_hitters` with `lmu_players` (union + weight).** In `scripts/scrape_roster_media.py`, replace `lmu_hitters()` with:

```python
def lmu_players() -> list[tuple[int, str, int]]:
    """(raw_tm_id, name, n_tracked) for LMU batters AND pitchers, so pitchers get
    their own roster card. n_tracked is that (id,name) identity's row count, used
    to break same-id collisions (a stray 1-row identity loses to the real one)."""
    bat = query_df(
        """
        SELECT batter_tm_id AS id, batter_name AS name, COUNT(*) AS n
          FROM fact_tm_game_pitch
         WHERE batter_team = :team AND batter_tm_id IS NOT NULL
         GROUP BY batter_tm_id, batter_name
        """, {"team": LMU_BATTER_TEAM})
    pit = query_df(
        """
        SELECT pitcher_tm_id AS id, pitcher_name AS name, COUNT(*) AS n
          FROM fact_tm_game_pitch
         WHERE pitcher_team = :team AND pitcher_tm_id IS NOT NULL
         GROUP BY pitcher_tm_id, pitcher_name
        """, {"team": LMU_BATTER_TEAM})
    rows = [(int(r.id), str(r.name), int(r.n)) for r in bat.itertuples()]
    rows += [(int(r.id), str(r.name), int(r.n)) for r in pit.itertuples()]
    return rows
```

- [ ] **Step 4: Rewrite `build_media` to accept weighted tuples + resolve collisions.** Replace `build_media`:

```python
def build_media(players, roster_cards):
    """Map raw_tm_id -> roster card, confident matches only, dominant identity wins.

    players: list of (raw_tm_id, warehouse_name, n_tracked).
    Sorting by n_tracked ascending means the heaviest identity is written LAST and
    wins the id key (a 1-pitch stray under someone else's id loses)."""
    by_norm = {_norm_name(p["name"]): p for p in roster_cards}
    li_index: dict[tuple[str, str], list[dict]] = {}
    for p in roster_cards:
        first, last = _name_parts(p["name"])
        li_index.setdefault((last, first[:1]), []).append(p)

    def match(name):
        p = by_norm.get(_norm_name(name))
        if p is None:
            first, last = _name_parts(name)
            cand = li_index.get((last, first[:1]), [])
            p = cand[0] if len(cand) == 1 else None  # unambiguous only
        return p

    media, matched_names, unmatched = {}, set(), []
    for tm_id, name, _n in sorted(players, key=lambda t: t[2]):  # light first
        p = match(name)
        if p:
            media[str(tm_id)] = {"jersey": p["jersey"], "photo_url": p["photo_url"],
                                 "name": p["name"]}
            matched_names.add(p["name"])
        else:
            unmatched.append(name)
    unmatched_roster = [p["name"] for p in roster_cards if p["name"] not in matched_names]
    return media, sorted(set(unmatched)), unmatched_roster
```

- [ ] **Step 5: Update `main()` to call the new functions.** In `main()`, replace the `hitters = lmu_hitters()` / `build_media(players, hitters)` block:

```python
    roster_cards = scrape_roster(_fetch(ROSTER_URL))
    print(f"  parsed {len(roster_cards)} roster cards")
    players = lmu_players()
    print(f"  {len(players)} LMU (batter+pitcher) identities in the warehouse")
    media, unmatched, unmatched_roster = build_media(players, roster_cards)
```

Keep the JSON write + summary prints; update the label from "hitters" to "players".

- [ ] **Step 6: Run the tests — expect PASS.**
Run: `python -m pytest tests/test_roster_media.py -v`
Note: if the file's other tests hit the network, they behave as they did before. The two new tests: `test_build_media_prefers_dominant_identity` is pure (no network); `test_lmu_players_includes_pitchers` needs the DB.

- [ ] **Step 7: Commit** (code only — the controller regenerates the JSON next).
```bash
git add scripts/scrape_roster_media.py tests/test_roster_media.py
git commit -m "fix(roster-media): match pitchers too; dominant-identity id collision resolution"
```

- [ ] **Step 8: CONTROLLER runs the scrape + verifies** (not the implementer): `PYTHONIOENCODING=utf-8 python scripts/scrape_roster_media.py`, then confirm `pitcher_profile` for Bender returns jersey `42` + a `Bender` photo (not Malone), and report the matched-pitcher count. Clear nothing else.

---

## Task 3: Pitch Breakdown — delete By Inning, per-outing pitch sequence, pitch colors

**Files:**
- Modify: `app/data/pitching.py`, `app/dashboards/pitching/tabs/pitch_breakdown.py`
- Test: `tests/test_pitching.py`, `tests/test_pitching_dash.py`

**Interfaces:**
- Produces: `P.pitch_color(pt: str) -> str` (hex, stable per type); `P.fig_velo_by_pitch(df)` now plots velo vs the pitcher's own 1..N sequence, colored by pitch type.

- [ ] **Step 1: Write failing tests.** Add to `tests/test_pitching.py`:

```python
def test_pitch_color_stable_and_hex():
    from app.data import pitching as P
    c = P.pitch_color("Fastball")
    assert c.startswith("#") and c == P.pitch_color("Fastball")


def test_fig_velo_by_pitch_uses_1_based_sequence(outing_like_df):
    from app.data import pitching as P
    fig = P.fig_velo_by_pitch(outing_like_df)
    xs = [x for tr in fig.data for x in (tr.x or [])]
    assert xs and min(xs) == 1  # per-outing sequence starts at 1, not game pitch_no
```

Add a small fixture `outing_like_df` to `tests/test_pitching.py` if none exists (a real outing df):
```python
import pytest
from app.data import pitching as P
@pytest.fixture(scope="module")
def outing_like_df():
    pid = _a_real_lmu_pitcher_id()          # helper added in Slice 1 task 3
    gid = int(P.games_for_pitcher(pid).iloc[0]["game_id"])
    return P.game_pitches_for(gid, pid)
```

- [ ] **Step 2: Run — expect FAIL.**
Run: `python -m pytest tests/test_pitching.py -k "pitch_color or by_pitch_uses_1_based" -v`

- [ ] **Step 3: Add `pitch_color` + rewrite `fig_velo_by_pitch`.** In `app/data/pitching.py`, add near the top of the FIGURES section:

```python
PITCH_COLORS = {
    "Fastball": "#9A0021", "Sinker": "#7a5230", "Cutter": "#2e8b57",
    "Slider": "#0076A5", "Curveball": "#e08a1e", "ChangeUp": "#6a4c93",
    "Splitter": "#c2185b", "Sweeper": "#00897b",
}
_PT_FALLBACK = ["#9A0021", "#0076A5", "#2e8b57", "#e08a1e", "#6a4c93",
                "#7a5230", "#00897b", "#c2185b"]


def pitch_color(pt: str) -> str:
    """Stable hex color for a pitch type (chips + charts share this)."""
    import zlib
    return PITCH_COLORS.get(pt) or _PT_FALLBACK[zlib.crc32(str(pt).encode()) % len(_PT_FALLBACK)]
```

Replace `fig_velo_by_pitch`:

```python
def fig_velo_by_pitch(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"]).sort_values("pitch_no").copy()
    d["_seq"] = range(1, len(d) + 1)          # pitcher's own 1..N for THIS outing
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["_seq"], y=sub["rel_speed"],
                                 mode="markers+lines", name=pt,
                                 marker=dict(color=pitch_color(pt)),
                                 line=dict(color=pitch_color(pt))))
    fig.update_xaxes(title="Pitch # (this outing)"); fig.update_yaxes(title="Velo (mph)")
    return _base_layout(fig, "Velocity Across Outing")
```

- [ ] **Step 4: Drop the By Inning sub-tab.** Replace `pitch_breakdown.render` body's velo section — remove the `dcc.Tabs` wrapper, show only the pitch-count chart:

```python
    return html.Div([
        section("Pitch Characteristics"),
        tables.df_table(char, id_="pb-char"),
        section("Velocity Across Outing"),
        dcc.Graph(figure=P.fig_velo_by_pitch(df)),
    ])
```

(`fig_velo_by_inning` stays defined but unused.)

- [ ] **Step 5: Run tests — expect PASS.**
Run: `python -m pytest tests/test_pitching.py -k "pitch_color or by_pitch" tests/test_pitching_dash.py::test_pitch_breakdown_render -v`

- [ ] **Step 6: Commit.**
```bash
git add app/data/pitching.py app/dashboards/pitching/tabs/pitch_breakdown.py tests/test_pitching.py
git commit -m "feat(pitching-dash): velo chart per-outing pitch sequence + pitch colors; drop By Inning"
```

---

## Task 4: Location / Movement — color by type, result-on-hover, chip filter

**Files:**
- Modify: `app/data/pitching.py`, `app/dashboards/pitching/tabs/location_movement.py`, `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching.py`, `tests/test_pitching_dash.py`

**Interfaces:**
- Produces: `P.pretty_result(call: str) -> str`; `P.fig_movement`/`P.fig_location` colored by `pitch_color`; `fig_location` hover shows the pitch result. Chip components: a chip row of `html.Button`s with id `{"type":"lm-chip","index":<pt>}`, Store `lm-active`, container `lm-body`.

- [ ] **Step 1: Write failing tests.** Add to `tests/test_pitching.py`:

```python
def test_pretty_result_maps_calls():
    from app.data import pitching as P
    assert P.pretty_result("StrikeSwinging") == "Swinging Strike"
    assert P.pretty_result("BallCalled") == "Ball"
    assert P.pretty_result("InPlay") == "In Play"
    assert P.pretty_result("Nonsense") == "Nonsense"  # unknown passes through
```

Add to `tests/test_pitching_dash.py`:

```python
def test_location_movement_render_has_chip_filter(outing_df):
    from app.dashboards.pitching.tabs import location_movement
    comp = location_movement.render(outing_df)
    assert comp is not None  # renders chip row + body without raising
```

- [ ] **Step 2: Run — expect FAIL.**
Run: `python -m pytest tests/test_pitching.py::test_pretty_result_maps_calls -v`

- [ ] **Step 3: Add `pretty_result` + recolor/hover the figures.** In `app/data/pitching.py`, add:

```python
_RESULT_LABELS = {
    "StrikeCalled": "Called Strike", "StrikeSwinging": "Swinging Strike",
    "BallCalled": "Ball", "BallinDirt": "Ball (Dirt)",
    "BallIntentional": "Intentional Ball", "AutomaticBall": "Automatic Ball",
    "FoulBallNotFieldable": "Foul", "FoulBallFieldable": "Foul",
    "InPlay": "In Play", "HitByPitch": "HBP",
}


def pretty_result(call: str) -> str:
    return _RESULT_LABELS.get(call, call)
```

Rewrite `fig_movement` to color by type:
```python
def fig_movement(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["horz_break"], y=sub["induced_vert_break"],
                                 mode="markers", name=pt,
                                 marker=dict(color=pitch_color(pt), size=9)))
    fig.update_xaxes(title="Horizontal Break (in)", zeroline=True)
    fig.update_yaxes(title="Induced Vert Break (in)", zeroline=True)
    return _base_layout(fig, "Pitch Movement")
```

Rewrite `fig_location` to color by type + hover the result:
```python
def fig_location(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    d["_res"] = d["pitch_call"].map(pretty_result)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=pt,
            marker=dict(color=pitch_color(pt), size=9), customdata=sub[["_res"]],
            hovertemplate=f"{pt}<br>Result: %{{customdata[0]}}<extra></extra>"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Pitch Location (Catcher View)")
```

- [ ] **Step 4: Rewrite the tab to render a chip row + body container.** Replace `app/dashboards/pitching/tabs/location_movement.py`:

```python
"""Location / Movement tab: pitch-type chip filter -> movement + location + table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def chip_row(df: pd.DataFrame, prefix: str) -> html.Div:
    """A clickable color chip per pitch type present (all active by default)."""
    types = list(P.pitch_type(df).value_counts().index)
    chips = [html.Button(
        pt, id={"type": f"{prefix}-chip", "index": pt}, n_clicks=0,
        style={"border": f"2px solid {P.pitch_color(pt)}", "background": P.pitch_color(pt),
               "color": "#fff", "borderRadius": "14px", "padding": "3px 12px",
               "margin": "0 6px 6px 0", "cursor": "pointer",
               "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        for pt in types]
    return html.Div([dcc.Store(id=f"{prefix}-active", data=types),
                     html.Div(chips)], style={"margin": "6px 0"})


def all_pitches(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Pitch": P.pitch_type(df),
        "Count": df["balls"].astype("Int64").astype(str) + "-"
                 + df["strikes"].astype("Int64").astype(str),
        "Velo": df["rel_speed"].round(1),
        "Result": df["pitch_call"].map(P.pretty_result),
    }).reset_index(drop=True)


def body(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitches for the selected pitch types.")
    return html.Div([
        html.Div([
            html.Div([section("Movement"), dcc.Graph(figure=P.fig_movement(df))],
                     style={"flex": "1"}),
            html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                     style={"flex": "1"}),
        ], style={"display": "flex", "gap": "16px"}),
        section("All Pitches"),
        tables.df_table(all_pitches(df), id_="lm-all"),
    ])


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([chip_row(df, "lm"),
                     html.Div(id="lm-body", children=body(df))])
```

- [ ] **Step 5: Add the chip callbacks.** In `app/dashboards/pitching/callbacks.py`, add imports and, inside `register_callbacks`, two callbacks. Import at top: `from dash import ALL, ctx` (extend the existing `from dash import ...`) and `from app.dashboards.pitching.tabs import location_movement`.

```python
    # Chip click -> toggle the pitch type in the active-set store.
    @dash_app.callback(
        Output("lm-active", "data"),
        Input({"type": "lm-chip", "index": ALL}, "n_clicks"),
        State("lm-active", "data"),
        prevent_initial_call=True,
    )
    def _lm_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]
        active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    # Active-set (or new data) -> re-render movement + location + table, filtered.
    @dash_app.callback(
        Output("lm-body", "children"),
        Input("lm-active", "data"), State("game-data", "data"),
    )
    def _lm_body(active, data_json):
        df = _read_game_df(data_json)
        if not df.empty and active is not None:
            df = df[P.pitch_type(df).isin(active)]
        return location_movement.body(df)
```

Also give the active chips a visual "off" state: add a third callback that dims deselected chips.
```python
    @dash_app.callback(
        Output({"type": "lm-chip", "index": ALL}, "style"),
        Input("lm-active", "data"),
        State({"type": "lm-chip", "index": ALL}, "id"),
    )
    def _lm_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = P.pitch_color(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out
```

The existing `_render_tab` already returns `location_movement.render(df)` for the `location` branch — no change needed there.

- [ ] **Step 6: Run tests — expect PASS.**
Run: `python -m pytest tests/test_pitching.py::test_pretty_result_maps_calls tests/test_pitching_dash.py -v`

- [ ] **Step 7: Commit.**
```bash
git add app/data/pitching.py app/dashboards/pitching/tabs/location_movement.py app/dashboards/pitching/callbacks.py tests/test_pitching.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): Location/Movement pitch-type chip filter + color-by-type + result hover"
```

---

## Task 5: RHH v. LHH — color by pitch type + chip filter

**Files:**
- Modify: `app/data/pitching.py`, `app/dashboards/pitching/tabs/rhh_lhh.py`, `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Produces: `P.fig_location_split(df)` colored by pitch type (+ result hover). Chip components with prefix `splits`: id `{"type":"splits-chip","index":<pt>}`, Store `splits-active`, container `splits-body`.

- [ ] **Step 1: Write the failing test.** Add to `tests/test_pitching_dash.py`:

```python
def test_rhh_lhh_render_has_chip_filter(outing_df):
    from app.dashboards.pitching.tabs import rhh_lhh
    assert rhh_lhh.render(outing_df) is not None
```

- [ ] **Step 2: Run — expect FAIL** (render signature/ids change).
Run: `python -m pytest tests/test_pitching_dash.py::test_rhh_lhh_render_has_chip_filter -v`

- [ ] **Step 3: Recolor `fig_location_split` by pitch type.** Replace `fig_location_split` in `app/data/pitching.py`:

```python
def fig_location_split(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    d["_res"] = d["pitch_call"].map(pretty_result)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=pt,
            marker=dict(color=pitch_color(pt), size=9), customdata=sub[["_res"]],
            hovertemplate=f"{pt}<br>Result: %{{customdata[0]}}<extra></extra>"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Location by Pitch Type")
```

- [ ] **Step 4: Rewrite the tab with a chip row + body.** Replace `app/dashboards/pitching/tabs/rhh_lhh.py`:

```python
"""RHH v. LHH tab: pitch-type chip filter -> side-by-side usage + location by type."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.pitching.tabs.location_movement import chip_row
from app.dashboards.shell import section

_USAGE_COLS = {"pitch": "Pitch", "count": "#", "usage_pct": "Usage%"}


def _side_col(df: pd.DataFrame, side: str) -> html.Div:
    sub = df[df["batter_side"] == side]
    usage = P.pitch_usage(sub) if len(sub) else P.pitch_usage(df.iloc[0:0])
    tbl = (usage[list(_USAGE_COLS)].rename(columns=_USAGE_COLS)
           if not usage.empty else pd.DataFrame(columns=list(_USAGE_COLS.values())))
    return html.Div([
        section(f"vs {side}-handed"),
        tables.df_table(tbl, id_=f"split-usage-{side.lower()}"),
        dcc.Graph(figure=P.fig_location_split(sub)),
    ], style={"flex": "1"})


def body(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitches for the selected pitch types.")
    return html.Div([_side_col(df, "Left"), _side_col(df, "Right")],
                    style={"display": "flex", "gap": "16px"})


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([chip_row(df, "splits"),
                     html.Div(id="splits-body", children=body(df))])
```

- [ ] **Step 5: Add the `splits` chip callbacks.** In `callbacks.py`, add `from app.dashboards.pitching.tabs import rhh_lhh` and three callbacks mirroring Task 4 but with the `splits` prefix and `rhh_lhh.body`:

```python
    @dash_app.callback(
        Output("splits-active", "data"),
        Input({"type": "splits-chip", "index": ALL}, "n_clicks"),
        State("splits-active", "data"), prevent_initial_call=True,
    )
    def _splits_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]; active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    @dash_app.callback(
        Output("splits-body", "children"),
        Input("splits-active", "data"), State("game-data", "data"),
    )
    def _splits_body(active, data_json):
        df = _read_game_df(data_json)
        if not df.empty and active is not None:
            df = df[P.pitch_type(df).isin(active)]
        return rhh_lhh.body(df)

    @dash_app.callback(
        Output({"type": "splits-chip", "index": ALL}, "style"),
        Input("splits-active", "data"),
        State({"type": "splits-chip", "index": ALL}, "id"),
    )
    def _splits_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = P.pitch_color(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col, "borderRadius": "14px",
                        "padding": "3px 12px", "margin": "0 6px 6px 0",
                        "cursor": "pointer", "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out
```

- [ ] **Step 6: Run tests — expect PASS.**
Run: `python -m pytest tests/test_pitching_dash.py -v`

- [ ] **Step 7: Commit.**
```bash
git add app/data/pitching.py app/dashboards/pitching/tabs/rhh_lhh.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): RHH v. LHH color-by-type + shared chip filter"
```

---

## Task 6: Last Outings — preset count dropdown + avg/max velo trend chart

**Files:**
- Modify: `app/data/pitching.py`, `app/dashboards/pitching/tabs/last_outings.py`, `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching.py`, `tests/test_pitching_dash.py`

**Interfaces:**
- Produces: `P.fig_outings_velo_trend(recent_df)` (two lines: Avg + Max velo over outing dates). Reuses `P.recent_outings(pid, gid, n)`. Component ids: dropdown `lo-count-dd`, container `lo-body`.

- [ ] **Step 1: Write failing tests.** Add to `tests/test_pitching.py`:

```python
def test_fig_outings_velo_trend_two_lines(real_pitcher_id_and_game):
    from app.data import pitching as P
    pid, gid = real_pitcher_id_and_game
    recent = P.recent_outings(pid, gid, 5)
    fig = P.fig_outings_velo_trend(recent)
    names = {tr.name for tr in fig.data}
    assert {"Avg Velo", "Max Velo"} <= names
```
Add a fixture if needed:
```python
@pytest.fixture(scope="module")
def real_pitcher_id_and_game():
    from app.data import pitching as P
    pid = _a_real_lmu_pitcher_id()
    gid = int(P.games_for_pitcher(pid).iloc[0]["game_id"])
    return pid, gid
```

- [ ] **Step 2: Run — expect FAIL.**
Run: `python -m pytest tests/test_pitching.py::test_fig_outings_velo_trend_two_lines -v`

- [ ] **Step 3: Add the two-line trend figure.** In `app/data/pitching.py`, add:

```python
def fig_outings_velo_trend(recent_df: pd.DataFrame) -> go.Figure:
    """Avg + Max velo across the selected outings (chronological)."""
    fig = go.Figure()
    if not recent_df.empty:
        d = recent_df.sort_values("game_date")
        fig.add_trace(go.Scatter(x=d["game_date"], y=d["appearance_avg_velo"].round(1),
                                 mode="markers+lines", name="Avg Velo",
                                 line=dict(color="#0076A5")))
        fig.add_trace(go.Scatter(x=d["game_date"], y=d["appearance_max_velo"].round(1),
                                 mode="markers+lines", name="Max Velo",
                                 line=dict(color="#9A0021")))
    fig.update_xaxes(title="Outing Date"); fig.update_yaxes(title="Velo (mph)")
    return _base_layout(fig, "Velocity Trend (Selected Outings)")
```

- [ ] **Step 4: Rewrite the tab with a count dropdown + body.** Replace `app/dashboards/pitching/tabs/last_outings.py`:

```python
"""Last Outings tab: coach picks how many outings; table + avg/max velo trend."""
from __future__ import annotations

from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_COLS = {
    "game_date": "Date", "appearance_avg_velo": "Avg Velo",
    "appearance_max_velo": "Max Velo", "pitch_count": "Pitches",
}
COUNT_OPTIONS = [{"label": "Last 3", "value": 3}, {"label": "Last 5", "value": 5},
                 {"label": "Last 10", "value": 10}, {"label": "Last 15", "value": 15},
                 {"label": "All", "value": 9999}]


def body(pitcher_id, game_id, n) -> html.Div:
    if pitcher_id is None or game_id is None:
        return html.Div("No outing selected.")
    recent = P.recent_outings(int(pitcher_id), int(game_id), int(n))
    if recent.empty:
        return html.Div("No prior outings.")
    show = recent[[c for c in _COLS if c in recent.columns]].rename(columns=_COLS)
    for col in ("Avg Velo", "Max Velo"):
        if col in show.columns:
            show[col] = show[col].round(1)
    label = "All" if int(n) >= 9999 else f"Last {len(show)}"
    return html.Div([
        section(f"{label} Outings"),
        tables.df_table(show, id_="lo-avgs"),
        section("Velocity Trend"),
        dcc.Graph(figure=P.fig_outings_velo_trend(recent)),
    ])


def render(pitcher_id, game_id, n: int = 5) -> html.Div:
    return html.Div([
        html.Div([
            html.Label("Outings", style={"fontWeight": "bold", "marginRight": "8px"}),
            dcc.Dropdown(id="lo-count-dd", options=COUNT_OPTIONS, value=5,
                         clearable=False, style={"width": "160px"}),
        ], style={"display": "flex", "alignItems": "center", "margin": "6px 0"}),
        html.Div(id="lo-body", children=body(pitcher_id, game_id, n)),
    ])
```

- [ ] **Step 5: Add the count-dropdown callback.** In `callbacks.py`, add `from app.dashboards.pitching.tabs import last_outings` (if not already imported) and:

```python
    @dash_app.callback(
        Output("lo-body", "children"),
        Input("lo-count-dd", "value"), State("selection", "data"),
    )
    def _lo_body(n, sel):
        sel = sel or {}
        return last_outings.body(sel.get("pitcher_id"), sel.get("game_id"), n or 5)
```

The existing `_render_tab` `outings` branch already calls `last_outings.render(sel.get("pitcher_id"), sel.get("game_id"), 5)` — leave it (it now renders the dropdown + default body).

- [ ] **Step 6: Run tests — expect PASS.**
Run: `python -m pytest tests/test_pitching.py -k outings_velo tests/test_pitching_dash.py -v`

- [ ] **Step 7: Full verification.** Run:
`python -m pytest tests/test_pitching_dash.py tests/test_pitching.py tests/test_pitching_landing.py tests/test_roster_media.py tests/test_shell.py tests/test_hitting_dash.py -v`
and confirm all pass; report counts.

- [ ] **Step 8: Commit.**
```bash
git add app/data/pitching.py app/dashboards/pitching/tabs/last_outings.py app/dashboards/pitching/callbacks.py tests/test_pitching.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): Last Outings count dropdown + avg/max velo trend chart"
```

---

## Self-Review (plan author)

**Spec coverage:** §1 roster fix → Task 2 (+ controller scrape). §2 back arrow → Task 1. §3 Pitch Breakdown → Task 3. §4 Location/Movement → Task 4. §5 RHH v. LHH → Task 5. §6 Last Outings → Task 6. §7 files all covered. All spec sections map to a task.

**Placeholder scan:** No TBD/TODO; every code step is complete. The chip style dict is repeated in the render helper and the style callback (Tasks 4/5) — intentional (initial render vs reactive restyle); acceptable minor duplication, could be factored later.

**Type consistency:** `pitch_color`/`pretty_result` defined in Task 3/4 and used in Tasks 4/5/6. `game_pitches_for` (Slice 1 fix) used by fixtures. Store/id names (`lm-active`/`lm-body`/`lm-chip`, `splits-*`, `lo-count-dd`/`lo-body`) consistent between tab render and callbacks. `recent_outings(pid, gid, n)` signature matches Task 6 usage. Chip prefix reuse: `rhh_lhh` imports `chip_row` from `location_movement` — one definition.

---

## Task Checklist

- [ ] **Task 1 — Back-links on Jinja pages** (pitching reports landing → Pitching hub; audit others)
- [ ] **Task 2 — Roster media fix** (match pitchers, dominant-identity collision resolution; controller re-scrapes + verifies Bender→#42)
- [ ] **Task 3 — Pitch Breakdown** (delete By Inning; velo x-axis = per-outing 1…N; `pitch_color`)
- [ ] **Task 4 — Location/Movement** (color-by-type, result-on-hover, clickable chip filter across charts+table)
- [ ] **Task 5 — RHH v. LHH** (color-by-type location + shared chip filter)
- [ ] **Task 6 — Last Outings** (preset count dropdown 3/5/10/15/All + avg/max velo trend chart + rounding)
- [ ] **Final — whole-slice review + live both-role smoke; controller restarts server**
