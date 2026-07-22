# Section Hubs + Pitching Game-Stats Dashboard (Slice 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each PAW section into a hub-with-submenu, and add a new warehouse-based Pitching game-stats Dash dashboard (4 tabs) mirroring the hitting module.

**Architecture:** Flask/Jinja hub pages route home → section hub → action (Stats Dashboard / Postgame Reports). A new shared Dash shell module removes the brand/header boilerplate duplicated in the hitting module; the hitting module is refactored onto it first, then a new `app/dashboards/pitching/` package is built on top, reusing the transforms and Plotly figure builders that already live in `app/data/pitching.py`.

**Tech Stack:** Flask, Flask-Login, Dash (mounted on Flask), Plotly, pandas, SQLAlchemy/PyMySQL against the modern Trackman warehouse, pytest.

## Global Constraints

- **Warehouse only** for new data: `fact_tm_game_pitch`, `dim_tm_game`, `tm_player`, `vw_pitcher_*`. Never legacy `GAMES`.
- **LMU-only:** pitchers filtered by `fact_tm_game_pitch.pitcher_team = 'LOY_LIO'` (constant `P.LMU_PITCHER_TEAM`). LMU `team_id = 78` (`P.LMU_TEAM_ID`).
- **Role gating:** coach may view any LMU pitcher; a player is locked to self via `current_user.trackman_id` matched to the pitcher's raw Trackman id (`pitcher_tm_id`). Selection helpers are pure — they never read `current_user`; layout/callbacks pass role + own id in.
- **Brand values** (single source now = `app/dashboards/shell.py`): crimson `#9A0021`, translucent banner `rgba(154,0,33,0.82)`, blue `#0076A5`, bg `#f5f5f5`, palms `/static/brand/palms-grey.png`, favicon `/static/reports/lion.png`, display font Teko. These are hardcoded in the shell (a Dash `index_string` cannot read base.html CSS tokens) — see Memory §3c.
- **No CDN** for fonts/assets (self-host rule). Teko `@font-face` is served from `/static/reports/`.
- **Pitch type** via `P.pitch_type(df)` (tagged, falling back to auto).
- **Provisional metrics** stay isolated in docstring'd functions, coach-confirmable.
- **Run:** `python run.py` → http://127.0.0.1:8050 (headless: prefix `PYTHONIOENCODING=utf-8`). Restart by killing the **port owner**, not the process name (see Memory §3b).
- **Test suite** currently 168 passing; keep it green. Live-DB tests follow the existing unguarded convention (`test_hitting_wh.py`, `test_pitching.py`).

---

## File Structure

**Create:**
- `app/dashboards/shell.py` — shared Dash shell: `index_string()`, `header()`, brand constants, `section()`.
- `app/templates/partials/_module_card.html` — reusable card-grid macro (home + hubs).
- `app/templates/main/pitching_hub.html`, `hitting_hub.html`, `catching_hub.html` — the three hub pages.
- `app/dashboards/pitching/__init__.py` — `build_pitching_dash(server)`.
- `app/dashboards/pitching/index.py` — Dash INDEX_STRING via the shell.
- `app/dashboards/pitching/selectors.py` — role-aware pitcher/outing options + `resolve_pitcher`.
- `app/dashboards/pitching/layout.py` — sidebar + selector row + tab frame.
- `app/dashboards/pitching/callbacks.py` — selection → stores → tabs.
- `app/dashboards/pitching/charts.py` — thin re-exports/wrappers over `app/data/pitching.py` figures (only if a tab needs a figure not already there).
- `app/dashboards/pitching/tables.py` — Dash DataTable builders.
- `app/dashboards/pitching/tabs/__init__.py`, `pitch_breakdown.py`, `location_movement.py`, `rhh_lhh.py`, `last_outings.py`.
- `tests/test_pitching_dash.py` — pure selector/tab tests + Dash builds.

**Modify:**
- `app/data/pitching.py` — add `_sibling_pitcher_ids`, `wh_lmu_pitchers`, `games_for_pitcher`, `pitcher_profile`, `season_summary`.
- `app/dashboards/hitting/index.py` + `layout.py` — import shell instead of local copies.
- `app/dashboards/__init__.py` — register `build_pitching_dash`.
- `app/main/routes.py` — add `pitching`, `hitting`, `catching` hub routes.
- `app/templates/main/index.html` — cards link to hubs; consume the shared card macro.
- `tests/test_shell.py` — hub-navigation assertions + shared-shell assertions.
- `tests/test_pitching.py` — data-layer additions.

---

## Task 1: Shared Dash shell (`app/dashboards/shell.py`) + refactor hitting

**Files:**
- Create: `app/dashboards/shell.py`
- Modify: `app/dashboards/hitting/index.py`, `app/dashboards/hitting/layout.py:1-36`
- Test: `tests/test_shell.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `shell.CRIMSON: str` = `"#9A0021"`, `shell.BANNER: str` = `"rgba(154,0,33,0.82)"`, `shell.PHOTO_PLACEHOLDER: str` = `"/static/reports/lion.png"`.
  - `shell.index_string() -> str` — the Dash INDEX_STRING (grey bg + palms + favicon + Teko fonts). Identical bytes to the hitting module's current INDEX_STRING.
  - `shell.header(back_href: str | None = None, back_label: str | None = None) -> dash.html.Div` — crimson header (LMU logo → home, "The Paw" wordmark, `{name} · {role} · Log out`); optional back-link on the right of the brand. Reads `current_user`.
  - `shell.section(title: str) -> dash.html.H3` — crimson section header (`color: #9A0021`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_shell.py`:

```python
def test_shell_index_string_has_brand():
    from app.dashboards import shell
    s = shell.index_string()
    assert "#f5f5f5" in s
    assert "palms-grey.png" in s
    assert "/static/reports/lion.png" in s
    assert "Teko-Regular.ttf" in s


def test_shell_constants():
    from app.dashboards import shell
    assert shell.CRIMSON == "#9A0021"
    assert shell.BANNER == "rgba(154,0,33,0.82)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shell.py::test_shell_index_string_has_brand -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dashboards.shell'`.

- [ ] **Step 3: Create `app/dashboards/shell.py`**

Move the constants + INDEX_STRING + `header()` out of the hitting module verbatim (so behavior is byte-identical), generalizing `header()` with an optional back-link.

```python
"""Shared Dash shell: brand index_string, crimson header, constants, section helper.

A Dash page does not extend base.html, so the site's grey+palms background and
lion favicon live here (hardcoded — a Dash index_string cannot read base.html CSS
tokens; keep in sync with the site brand). See Memory §3c. This is the single
source for these values across ALL Dash dashboards (hitting, pitching, ...).
"""
from __future__ import annotations

from dash import html
from flask_login import current_user

CRIMSON = "#9A0021"
BANNER = "rgba(154,0,33,0.82)"
PHOTO_PLACEHOLDER = "/static/reports/lion.png"

_INDEX_STRING = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
<link rel="icon" type="image/png" href="/static/reports/lion.png">
{%css%}
<style>
  @font-face {
    font-family: "Teko"; font-weight: 400; font-display: swap;
    src: url("/static/reports/Teko-Regular.ttf") format("truetype");
  }
  @font-face {
    font-family: "Teko"; font-weight: 600; font-display: swap;
    src: url("/static/reports/Teko-SemiBold.ttf") format("truetype");
  }
  @font-face {
    font-family: "Teko"; font-weight: 700; font-display: swap;
    src: url("/static/reports/Teko-Bold.ttf") format("truetype");
  }
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


def index_string() -> str:
    return _INDEX_STRING


def header(back_href: str | None = None, back_label: str | None = None) -> html.Div:
    """Site header (matches base.html): logo -> home, wordmark, optional back-link,
    user + logout."""
    brand_children = [
        html.Img(src="/static/reports/lmu.png",
                 style={"height": "40px", "width": "auto", "display": "block"}),
        html.Span("The Paw", style={
            "fontFamily": "Teko, sans-serif", "fontWeight": "700", "fontSize": "30px",
            "lineHeight": "1", "letterSpacing": "1px", "textTransform": "uppercase",
            "color": "#fff"}),
    ]
    brand = html.A(brand_children, href="/",
                   style={"display": "flex", "alignItems": "center", "gap": "12px",
                          "textDecoration": "none"})
    left = [brand]
    if back_href:
        left.append(html.A(back_label or "← Back", href=back_href, style={
            "color": "#fff", "textDecoration": "underline", "fontSize": "14px",
            "marginLeft": "18px"}))
    right = html.Span()
    if current_user.is_authenticated:
        right = html.Span([
            f"{current_user.name} · {current_user.role} · ",
            html.A("Log out", href="/logout",
                   style={"color": "#fff", "textDecoration": "underline"}),
        ], style={"fontSize": "14px", "color": "rgba(255,255,255,.85)"})
    return html.Div([html.Div(left, style={"display": "flex", "alignItems": "center"}),
                     right], style={
        "background": BANNER, "color": "#fff", "padding": "0 20px", "height": "64px",
        "display": "flex", "alignItems": "center", "justifyContent": "space-between",
        "boxShadow": "0 2px 8px rgba(0,0,0,.15)"})


def section(title: str) -> html.H3:
    return html.H3(title, style={"color": CRIMSON})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_shell.py::test_shell_index_string_has_brand tests/test_shell.py::test_shell_constants -v`
Expected: PASS.

- [ ] **Step 5: Refactor the hitting module onto the shell**

In `app/dashboards/hitting/index.py`, replace the whole file with a re-export so `INDEX_STRING` keeps working for `__init__.py`:

```python
"""The Dash HTML shell for hitting — now delegates to the shared shell.
Kept as a thin module so app.dashboards.hitting.index.INDEX_STRING still resolves.
"""
from app.dashboards.shell import index_string

INDEX_STRING = index_string()
```

In `app/dashboards/hitting/layout.py`, delete the local `_CRIMSON`/`_BANNER`/`_PHOTO_PLACEHOLDER` constants and the local `header()` (lines ~10-36) and import from the shell instead. At the top of the file:

```python
from app.dashboards.shell import CRIMSON as _CRIMSON, PHOTO_PLACEHOLDER as _PHOTO_PLACEHOLDER, header
```

Remove the old `def header() -> html.Div:` block entirely (the shell's `header()` is called with no args, which is the same behavior). Keep `_tile`, `sidebar`, `scoreboard`, `serve_layout` unchanged except that they now reference the imported `_CRIMSON`/`_PHOTO_PLACEHOLDER`. `serve_layout` still calls `header()` — now the shell's.

- [ ] **Step 6: Run the hitting dashboard tests to confirm no regression**

Run: `python -m pytest tests/test_hitting_dash.py tests/test_shell.py -v`
Expected: PASS (all previously-passing hitting-dash + shell tests still pass).

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/shell.py app/dashboards/hitting/index.py app/dashboards/hitting/layout.py tests/test_shell.py
git commit -m "refactor(dash): extract shared Dash shell; refactor hitting onto it"
```

---

## Task 2: Section hub navigation (Flask/Jinja)

**Files:**
- Create: `app/templates/partials/_module_card.html`, `app/templates/main/pitching_hub.html`, `app/templates/main/hitting_hub.html`, `app/templates/main/catching_hub.html`
- Modify: `app/main/routes.py`, `app/templates/main/index.html`
- Test: `tests/test_shell.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: Flask endpoints `main.pitching` (`/pitching`), `main.hitting` (`/hitting`), `main.catching` (`/catching`), all `@login_required`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_shell.py` (reuse the existing logged-in client fixture in that file; if none, mirror the pattern from `tests/test_home.py`):

```python
def test_section_hubs_render_and_link(logged_in_client):
    # Home cards now point at the hubs.
    home = logged_in_client.get("/")
    assert home.status_code == 200
    assert b'href="/pitching"' in home.data
    assert b'href="/hitting"' in home.data

    # Pitching hub lists its two actions.
    ph = logged_in_client.get("/pitching")
    assert ph.status_code == 200
    assert b"/dash/pitching/" in ph.data           # Stats Dashboard
    assert b"/reports/pitching" in ph.data          # Postgame Reports

    # Hitting hub: Stats Dashboard live, HitTrax practice "Coming soon".
    hh = logged_in_client.get("/hitting")
    assert hh.status_code == 200
    assert b"/dash/hitting/" in hh.data
    assert b"Coming soon" in hh.data

    # Catching hub is a placeholder.
    ch = logged_in_client.get("/catching")
    assert ch.status_code == 200
    assert b"Coming soon" in ch.data
```

If `tests/test_shell.py` has no `logged_in_client` fixture, add one copied from `tests/test_home.py` (create a coach user, log in via the test client).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shell.py::test_section_hubs_render_and_link -v`
Expected: FAIL — `/pitching` returns 404 (route not defined).

- [ ] **Step 3: Add the hub routes**

In `app/main/routes.py`:

```python
@main_bp.route("/pitching")
@login_required
def pitching():
    return render_template("main/pitching_hub.html", user=current_user)


@main_bp.route("/hitting")
@login_required
def hitting():
    return render_template("main/hitting_hub.html", user=current_user)


@main_bp.route("/catching")
@login_required
def catching():
    return render_template("main/catching_hub.html", user=current_user)
```

- [ ] **Step 4: Create the shared card macro**

`app/templates/partials/_module_card.html`:

```jinja
{% macro card_grid(cards) %}
<style>
  .modules { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  @media (max-width: 720px) { .modules { grid-template-columns: 1fr; } }
  .module {
    display: block; text-decoration: none; color: var(--ink);
    background: #fff; border: 1px solid #e2e2e2; border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 20px; border-top: 4px solid var(--crimson);
    transition: box-shadow .15s, transform .05s;
  }
  a.module:hover { box-shadow: 0 6px 18px rgba(0,0,0,.12); transform: translateY(-2px); }
  .module h3 { margin: 0 0 6px; color: var(--crimson); font-size: 24px; }
  .module p { margin: 0; font-size: 14px; color: #555; }
  .module.disabled { border-top-color: #bbb; opacity: .7; }
  .module.disabled h3 { color: #888; }
  .module .soon {
    display: inline-block; margin-top: 8px; font-size: 12px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .5px; color: var(--blue-dark);
  }
</style>
<div class="modules">
  {% for c in cards %}
    {% if c.href %}
      <a class="module" href="{{ c.href }}">
        <h3>{{ c.title }}</h3><p>{{ c.desc }}</p>
      </a>
    {% else %}
      <div class="module disabled">
        <h3>{{ c.title }}</h3><p>{{ c.desc }}</p>
        <span class="soon">Coming soon</span>
      </div>
    {% endif %}
  {% endfor %}
</div>
{% endmacro %}
```

- [ ] **Step 5: Rewrite the home page to use the macro + link to hubs**

Replace the `<style>` + `.modules-section` block in `app/templates/main/index.html` so the hero stays but the module grid comes from the macro and links to the hubs:

```jinja
{% extends "base.html" %}
{% from "partials/_module_card.html" import card_grid %}
{% block title %}The PAW — LMU Baseball{% endblock %}
{% block content %}
<style>
  .home-hero {
    position: relative; overflow: hidden; text-align: center;
    background: var(--banner); color: #fff;
    border-radius: var(--radius); box-shadow: var(--shadow);
    padding: 34px 30px;
  }
  .home-hero .lions { height: 58px; width: auto; margin-bottom: 8px; }
  .home-hero .marquee {
    font-family: var(--font-marquee); font-size: 66px; line-height: .95;
    margin: 4px 0 2px; letter-spacing: 1px;
  }
  .home-hero .tagline {
    font-family: var(--font-display); font-size: 20px; letter-spacing: 1px;
    text-transform: uppercase; color: rgba(255,255,255,.85); margin: 0;
  }
  .home-hero .welcome { margin: 14px auto 0; max-width: 640px; font-size: 15px;
    color: rgba(255,255,255,.92); }
  .home-hero .welcome strong { color: #fff; }
  .modules-section { margin-top: 26px; }
</style>

<section class="home-hero">
  <img class="lions" src="{{ url_for('static', filename='brand/lions-arch.png') }}" alt="LMU Lions">
  <div class="marquee">THE PAW</div>
  <p class="tagline">LMU Baseball Analytics</p>
  <p class="welcome">
    Welcome, <strong>{{ user.name }}</strong> —
    {% if user.is_coach %}
      signed in as <strong>coach</strong>: view every LMU player &amp; add game notes.
    {% else %}
      signed in as <strong>player</strong>: your own postgame data.
    {% endif %}
  </p>
</section>

<div class="modules-section">
  {{ card_grid([
    {"title": "Hitting", "desc": "Swing decisions, batted ball, plate discipline.", "href": url_for('main.hitting')},
    {"title": "Pitching", "desc": "Game stats dashboard and postgame reports.", "href": url_for('main.pitching')},
    {"title": "Catching", "desc": "Blocking, framing, throws.", "href": url_for('main.catching')}
  ]) }}
</div>
{% endblock %}
```

- [ ] **Step 6: Create the three hub templates**

`app/templates/main/pitching_hub.html`:

```jinja
{% extends "base.html" %}
{% from "partials/_module_card.html" import card_grid %}
{% block title %}Pitching — The PAW{% endblock %}
{% block content %}
<p><a href="{{ url_for('main.index') }}">← Back to home</a></p>
<h2 style="color: var(--crimson); font-family: var(--font-display);">Pitching</h2>
{{ card_grid([
  {"title": "Stats Dashboard", "desc": "Pitch breakdown, location/movement, splits, last outings.", "href": "/dash/pitching/"},
  {"title": "Postgame Reports (PDF)", "desc": "One-page pitcher reports for a game.", "href": url_for('reports.pitching_landing')}
]) }}
{% endblock %}
```

`app/templates/main/hitting_hub.html`:

```jinja
{% extends "base.html" %}
{% from "partials/_module_card.html" import card_grid %}
{% block title %}Hitting — The PAW{% endblock %}
{% block content %}
<p><a href="{{ url_for('main.index') }}">← Back to home</a></p>
<h2 style="color: var(--crimson); font-family: var(--font-display);">Hitting</h2>
{{ card_grid([
  {"title": "Stats Dashboard", "desc": "Swing decisions, batted ball, plate discipline.", "href": "/dash/hitting/"},
  {"title": "Practice Dashboard (HitTrax)", "desc": "Practice hitting metrics from HitTrax.", "href": none}
]) }}
{% endblock %}
```

`app/templates/main/catching_hub.html`:

```jinja
{% extends "base.html" %}
{% from "partials/_module_card.html" import card_grid %}
{% block title %}Catching — The PAW{% endblock %}
{% block content %}
<p><a href="{{ url_for('main.index') }}">← Back to home</a></p>
<h2 style="color: var(--crimson); font-family: var(--font-display);">Catching</h2>
{{ card_grid([
  {"title": "Blocking / Framing / Throws", "desc": "Catching analytics.", "href": none}
]) }}
{% endblock %}
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `python -m pytest tests/test_shell.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/main/routes.py app/templates/main/index.html app/templates/main/pitching_hub.html app/templates/main/hitting_hub.html app/templates/main/catching_hub.html app/templates/partials/_module_card.html tests/test_shell.py
git commit -m "feat(nav): section hub pages (pitching/hitting/catching) with shared card grid"
```

---

## Task 3: Pitching data-layer additions (`app/data/pitching.py`)

**Files:**
- Modify: `app/data/pitching.py`
- Test: `tests/test_pitching.py`

**Interfaces:**
- Consumes: `query_df`, `LMU_PITCHER_TEAM`, `pitcher_tm_id_for`, existing `game_pitches`.
- Produces:
  - `wh_lmu_pitchers() -> pd.DataFrame` with columns `PitcherId` (int), `Pitcher` (str "Last, First"). One row per pitcher (split ids deduped to the most-tracked id).
  - `_sibling_pitcher_ids(pitcher_id: int) -> list[int]` — all warehouse pitcher_ids sharing the pitcher's Trackman raw id / name.
  - `games_for_pitcher(pitcher_id: int) -> pd.DataFrame` columns `game_id` (int), `GameLabel` (str, newest first).
  - `pitcher_profile(pitcher_id: int) -> dict` keys `name, class_year, position, throws, jersey, photo`.
  - `season_summary(pitcher_id: int) -> dict` keys `appearances, pitches, k, bb` (all str, "—" when unknown).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitching.py` (this file already runs against the live DB; reuse its style). Pick a real LMU pitcher dynamically so the test isn't brittle:

```python
def _a_real_lmu_pitcher_id():
    from app.data import pitching as P
    from app.db import query_df
    df = query_df(
        """
        SELECT pitcher_id FROM fact_tm_game_pitch
         WHERE pitcher_team = 'LOY_LIO' AND pitcher_id IS NOT NULL
         GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "pitcher_id"])


def test_wh_lmu_pitchers_has_rows_and_columns():
    from app.data import pitching as P
    df = P.wh_lmu_pitchers()
    assert not df.empty
    assert {"PitcherId", "Pitcher"} <= set(df.columns)
    assert df["PitcherId"].is_unique


def test_games_for_pitcher_newest_first():
    from app.data import pitching as P
    pid = _a_real_lmu_pitcher_id()
    g = P.games_for_pitcher(pid)
    assert not g.empty
    assert {"game_id", "GameLabel"} <= set(g.columns)


def test_pitcher_profile_and_season_summary_keys():
    from app.data import pitching as P
    pid = _a_real_lmu_pitcher_id()
    prof = P.pitcher_profile(pid)
    assert set(prof) >= {"name", "class_year", "position", "throws", "jersey", "photo"}
    summ = P.season_summary(pid)
    assert set(summ) >= {"appearances", "pitches", "k", "bb"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching.py::test_wh_lmu_pitchers_has_rows_and_columns -v`
Expected: FAIL — `AttributeError: module 'app.data.pitching' has no attribute 'wh_lmu_pitchers'`.

- [ ] **Step 3: Implement the additions**

Append to `app/data/pitching.py` (after `pitchers_for_game`). `throws` reads `fact_tm_game_pitch.pitcher_throws`; photo/jersey come from `roster_media` (best-effort — pitchers may be unmatched → blanks → placeholder in the sidebar).

```python
def wh_lmu_pitchers() -> pd.DataFrame:
    """One row per LMU pitcher for the dashboard dropdown.

    Some pitchers have multiple pitcher_ids (split Trackman id schemes, same
    name); collapse to the most-tracked id per name, like the hitting module.
    Names come from tm_player as "Last, First".
    """
    return query_df(
        """
        SELECT PitcherId, Pitcher FROM (
          SELECT p.player_id AS PitcherId,
                 CONCAT(p.last_name, ', ', p.first_name) AS Pitcher,
                 COUNT(*) AS n,
                 ROW_NUMBER() OVER (
                   PARTITION BY p.last_name, p.first_name
                   ORDER BY COUNT(*) DESC) AS rn
            FROM fact_tm_game_pitch f
            JOIN tm_player p ON p.player_id = f.pitcher_id
           WHERE f.pitcher_team = :lmu AND f.pitcher_id IS NOT NULL
           GROUP BY p.player_id, p.last_name, p.first_name
        ) t
        WHERE rn = 1
        ORDER BY Pitcher
        """,
        {"lmu": LMU_PITCHER_TEAM},
    )


def _sibling_pitcher_ids(pitcher_id: int) -> list[int]:
    """All LMU pitcher_ids sharing this pitcher's name (split-id union)."""
    df = query_df(
        """
        SELECT DISTINCT f2.pitcher_id
          FROM fact_tm_game_pitch f
          JOIN tm_player p  ON p.player_id = f.pitcher_id
          JOIN tm_player p2 ON p2.last_name = p.last_name
                           AND p2.first_name = p.first_name
          JOIN fact_tm_game_pitch f2 ON f2.pitcher_id = p2.player_id
         WHERE f.pitcher_id = :pid AND f2.pitcher_team = :lmu
        """,
        {"pid": pitcher_id, "lmu": LMU_PITCHER_TEAM},
    )
    ids = [int(x) for x in df["pitcher_id"].tolist()]
    return ids or [int(pitcher_id)]


def games_for_pitcher(pitcher_id: int) -> pd.DataFrame:
    """A pitcher's outings, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'."""
    ids = _sibling_pitcher_ids(pitcher_id)
    marks = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": v for i, v in enumerate(ids)}
    params["lmu"] = LMU_TEAM_ID
    df = query_df(
        f"""
        SELECT DISTINCT g.game_id, g.game_date,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE f.pitcher_id IN ({marks})
         ORDER BY g.game_date DESC, g.game_id DESC
        """,
        params,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "GameLabel"])
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "GameLabel"]].reset_index(drop=True)


def pitcher_profile(pitcher_id: int) -> dict:
    """Name + throws (from the warehouse) + jersey/photo (best-effort roster media)."""
    from app.data import roster_media
    name = pitcher_name(pitcher_id)  # "First Last"
    thr = query_df(
        """
        SELECT pitcher_throws FROM fact_tm_game_pitch
         WHERE pitcher_id = :pid AND pitcher_throws IS NOT NULL LIMIT 1
        """,
        {"pid": pitcher_id},
    )
    throws = "" if thr.empty else str(thr.iloc[0]["pitcher_throws"])
    tm_id = pitcher_tm_id_for(pitcher_id)
    media = roster_media.player_media(tm_id) if tm_id is not None else {"jersey": "", "photo_url": ""}
    return {"name": name, "class_year": "", "position": "",
            "throws": throws, "jersey": media.get("jersey", ""),
            "photo": media.get("photo_url", "")}


def season_summary(pitcher_id: int) -> dict:
    """Coarse season tiles: appearances (distinct games) + total pitches + K + BB."""
    ids = _sibling_pitcher_ids(pitcher_id)
    marks = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": v for i, v in enumerate(ids)}
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT game_id) AS apps, COUNT(*) AS pitches,
               SUM(korbb = 'Strikeout') AS k, SUM(korbb = 'Walk') AS bb
          FROM fact_tm_game_pitch
         WHERE pitcher_id IN ({marks})
        """,
        params,
    )
    if df.empty:
        return {"appearances": "—", "pitches": "—", "k": "—", "bb": "—"}
    r = df.iloc[0]
    def _s(v):
        return "—" if v is None or pd.isna(v) else str(int(v))
    return {"appearances": _s(r["apps"]), "pitches": _s(r["pitches"]),
            "k": _s(r["k"]), "bb": _s(r["bb"])}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching.py -k "wh_lmu_pitchers or games_for_pitcher or pitcher_profile or season_summary" -v`
Expected: PASS (against the live DB).

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching-data): pitcher list, games-for-pitcher, profile, season summary"
```

---

## Task 4: Pitching dashboard scaffold (`app/dashboards/pitching/`)

**Files:**
- Create: `app/dashboards/pitching/__init__.py`, `index.py`, `selectors.py`, `layout.py`, `callbacks.py`, `tables.py`, `tabs/__init__.py`
- Modify: `app/dashboards/__init__.py`
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `shell.index_string/header/section/CRIMSON/PHOTO_PLACEHOLDER`; `P.wh_lmu_pitchers/games_for_pitcher/pitcher_profile/season_summary/pitcher_tm_id_for/game_pitches/game_context`.
- Produces:
  - `build_pitching_dash(server) -> Dash` mounted at `/dash/pitching/`.
  - `selectors.resolve_pitcher(requested_id, *, is_coach, own_trackman_id) -> int | None`
  - `selectors.pitcher_options(*, is_coach, own_trackman_id) -> list[dict]`
  - `selectors.outing_options(pitcher_id) -> list[dict]`
  - Dash component ids: `pitcher-dd`, `outing-dd`, `scoreboard`, `sidebar`, `tabs` (values `breakdown`/`location`/`splits`/`outings`), `selection` Store, `game-data` Store, `tab-content`.

- [ ] **Step 1: Write the failing test**

`tests/test_pitching_dash.py`:

```python
"""Tests for the Dash pitching dashboard (shell, selectors, build)."""
import pandas as pd
import pytest

from app import create_app
from app.data import pitching as P
from app.db import query_df
from config import Config


@pytest.fixture(scope="module")
def real_pitcher():
    df = query_df(
        """
        SELECT pitcher_id FROM fact_tm_game_pitch
         WHERE pitcher_team = 'LOY_LIO' AND pitcher_id IS NOT NULL
         GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "pitcher_id"])


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(TestConfig)


def test_resolve_pitcher_player_is_self_only():
    from app.dashboards.pitching import selectors
    # A player ignores the requested id and gets their own.
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_pitcher(999, is_coach=True, own_trackman_id=None) == 999


def test_pitcher_options_coach_nonempty():
    from app.dashboards.pitching import selectors
    opts = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])


def test_outing_options_for_real_pitcher(real_pitcher):
    from app.dashboards.pitching import selectors
    opts = selectors.outing_options(real_pitcher)
    assert opts and {"label", "value"} <= set(opts[0])


def test_build_pitching_dash_mounts(server):
    # The dashboard registers at /dash/pitching/ during create_app.
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/pitching/") for r in rules)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_resolve_pitcher_player_is_self_only -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dashboards.pitching'`.

- [ ] **Step 3: Create `selectors.py`**

```python
"""Role-aware selection helpers for the pitching dashboard (pure functions).

A player is locked to their own data server-side. Ids are warehouse pitcher_id;
a player's own id is resolved from their Trackman raw id.
"""
from __future__ import annotations

from app.data import pitching as P


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The pitcher_id a request may view. Players are self-only."""
    if not is_coach:
        if own_trackman_id is None:
            return None
        # Map the player's Trackman raw id -> a warehouse pitcher_id.
        return _pitcher_id_for_tm(int(own_trackman_id))
    return int(requested_id) if requested_id not in (None, "") else None


def _pitcher_id_for_tm(tm_id: int):
    from app.db import query_df
    df = query_df(
        """
        SELECT pitcher_id FROM fact_tm_game_pitch
         WHERE pitcher_tm_id = :tm AND pitcher_team = 'LOY_LIO'
         GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        {"tm": tm_id},
    )
    return None if df.empty else int(df.loc[0, "pitcher_id"])


def pitcher_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    if is_coach:
        df = P.wh_lmu_pitchers()
        return [{"label": str(r.Pitcher), "value": int(r.PitcherId)}
                for r in df.itertuples()]
    pid = resolve_pitcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if pid is None:
        return []
    return [{"label": P.pitcher_name(pid), "value": pid}]


def outing_options(pitcher_id) -> list[dict]:
    if pitcher_id is None:
        return []
    df = P.games_for_pitcher(int(pitcher_id))
    return [{"label": str(r.GameLabel), "value": int(r.game_id)}
            for r in df.itertuples()]
```

- [ ] **Step 4: Create `tables.py`, `tabs/__init__.py`, and the placeholder tab renders**

`app/dashboards/pitching/tabs/__init__.py`: empty file.

`app/dashboards/pitching/tables.py`:

```python
"""Dash DataTable builders for the pitching dashboard."""
from __future__ import annotations

import pandas as pd
from dash import dash_table


def df_table(df: pd.DataFrame, id_: str | None = None):
    return dash_table.DataTable(
        id=id_ or "pitching-table",
        columns=[{"name": str(c), "id": str(c)} for c in df.columns],
        data=df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": "#9A0021", "color": "white",
                      "fontWeight": "bold"},
    )
```

- [ ] **Step 5: Create `layout.py`**

```python
"""The pitching dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from dash import dcc, html
from flask_login import current_user

from app.data import pitching as P
from app.dashboards.shell import CRIMSON, PHOTO_PLACEHOLDER, header, section
from app.dashboards.pitching import selectors

_BANNER = "rgba(154,0,33,0.82)"


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(pitcher_id) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    prof = P.pitcher_profile(int(pitcher_id))
    summ = P.season_summary(int(pitcher_id))
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Throws {prof['throws']}" if prof["throws"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("APP", summ["appearances"]), _tile("PITCHES", summ["pitches"]),
                  _tile("K", summ["k"]), _tile("BB", summ["bb"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Season totals = warehouse (provisional).",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id) -> html.Div:
    if not game_id:
        return html.Div()
    try:
        ctx = P.game_context(int(game_id))
    except Exception:
        return html.Div()
    opp = ctx["away_team"] if ctx["lmu_is_home"] else ctx["home_team"]
    loc = "vs" if ctx["lmu_is_home"] else "@"
    parts = [str(ctx["game_date"]), f"{loc} {opp}", ctx.get("game_type") or ""]
    return html.Div(" · ".join(p for p in parts if p),
                    style={"color": "white", "fontWeight": "bold",
                           "fontSize": "20px", "alignSelf": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    pitchers = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own)
    default_pitcher = selectors.resolve_pitcher(
        pitchers[0]["value"] if pitchers else None,
        is_coach=is_coach, own_trackman_id=own)
    outings = selectors.outing_options(default_pitcher)
    default_game = outings[0]["value"] if outings else None

    selector_row = html.Div([
        html.Div([
            html.Label("Pitcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="pitcher-dd", options=pitchers, value=default_pitcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Outing", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="outing-dd", options=outings, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": _BANNER})

    tabs = dcc.Tabs(id="tabs", value="breakdown", children=[
        dcc.Tab(label="Pitch Breakdown", value="breakdown"),
        dcc.Tab(label="Location / Movement", value="location"),
        dcc.Tab(label="RHH v. LHH", value="splits"),
        dcc.Tab(label="Last Outings", value="outings"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"pitcher_id": default_pitcher,
                                        "game_id": default_game}),
        dcc.Store(id="game-data"),
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div([
            html.Div(id="sidebar", children=sidebar(default_pitcher),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
```

- [ ] **Step 6: Create `callbacks.py` (placeholder tab bodies for now)**

```python
"""Dash callbacks: selection -> data stores -> reactive sidebar/scoreboard/tabs."""
from __future__ import annotations

import io

import pandas as pd
from dash import Input, Output, State, html
from flask_login import current_user

from app.data import pitching as P
from app.dashboards.pitching import layout, selectors


def _read_game_df(data_json):
    if not data_json:
        return pd.DataFrame()
    return pd.read_json(io.StringIO(data_json), orient="split")


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("outing-dd", "options"), Output("outing-dd", "value"),
        Input("pitcher-dd", "value"),
    )
    def _on_pitcher(pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        opts = selectors.outing_options(pid)
        return opts, (opts[0]["value"] if opts else None)

    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("pitcher-dd", "value"), Input("outing-dd", "value"),
    )
    def _on_selection(pitcher_id, game_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        return ({"pitcher_id": pid, "game_id": game_id},
                layout.sidebar(pid), layout.scoreboard(game_id))

    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("game_id") is None or sel.get("pitcher_id") is None:
            return None
        df = P.game_pitches(int(sel["game_id"]), int(sel["pitcher_id"]))
        return None if df.empty else df.to_json(orient="split")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
        State("selection", "data"),
    )
    def _render_tab(tab, data_json, sel):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        # Tabs wired in Tasks 5-8.
        return html.Div(f"[{tab}] {len(df)} pitches", style={"padding": "12px"})
```

- [ ] **Step 7: Create `index.py` + `__init__.py` and register the dashboard**

`app/dashboards/pitching/index.py`:

```python
"""The Dash HTML shell for pitching — delegates to the shared shell."""
from app.dashboards.shell import index_string

INDEX_STRING = index_string()
```

`app/dashboards/pitching/__init__.py`:

```python
"""Login-protected Pitching game-stats dashboard (Flask + Dash)."""
from dash import Dash

from app.dashboards.pitching.index import INDEX_STRING
from app.dashboards.pitching import layout

__all__ = ["build_pitching_dash", "INDEX_STRING"]


def build_pitching_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/pitching/",
        suppress_callback_exceptions=True,
        title="Pitching — The PAW",
    )
    dash_app.index_string = INDEX_STRING
    dash_app.layout = layout.serve_layout

    from app.dashboards.pitching import callbacks
    callbacks.register_callbacks(dash_app)
    return dash_app
```

In `app/dashboards/__init__.py`, register it alongside hitting:

```python
def register_dashboards(server):
    _protect_dash_routes(server)
    from app.dashboards.hitting import build_hitting_dash
    build_hitting_dash(server)
    from app.dashboards.pitching import build_pitching_dash
    build_pitching_dash(server)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py -v`
Expected: PASS.

- [ ] **Step 9: Manual smoke check**

Start the app (`PYTHONIOENCODING=utf-8 python run.py`), log in as coach (`coach@lmu.edu` / `paw2026`), visit `/pitching` → Stats Dashboard → confirm the page loads, a pitcher + outing are selected by default, the sidebar shows the photo/name/tiles, and each tab shows the placeholder text. Kill the server by port owner when done.

- [ ] **Step 10: Commit**

```bash
git add app/dashboards/pitching app/dashboards/__init__.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): scaffold /dash/pitching/ (shell, selectors, layout, callbacks)"
```

---

## Task 5: Pitch Breakdown tab

**Files:**
- Create: `app/dashboards/pitching/tabs/pitch_breakdown.py`
- Modify: `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `P.pitch_characteristics(df)`, `P.pitch_usage(df)`, `P.game_overall_line(df)`, `P.fig_velo_by_inning(df)`, `P.fig_velo_by_pitch(df)`; `tables.df_table`; `shell.section`.
- Produces: `pitch_breakdown.render(df: pd.DataFrame) -> dash.html.Div`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitching_dash.py`:

```python
@pytest.fixture(scope="module")
def outing_df(real_pitcher):
    from app.data import pitching as P
    g = P.games_for_pitcher(real_pitcher)
    gid = int(g.iloc[0]["game_id"])
    return P.game_pitches(gid, real_pitcher)


def test_pitch_breakdown_render(outing_df):
    from app.dashboards.pitching.tabs import pitch_breakdown
    comp = pitch_breakdown.render(outing_df)
    assert comp is not None  # renders without raising on real data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_pitch_breakdown_render -v`
Expected: FAIL — `ModuleNotFoundError: ...tabs.pitch_breakdown`.

- [ ] **Step 3: Implement `pitch_breakdown.py`**

```python
"""Pitch Breakdown tab: characteristics + usage + velo trend (inning / pitch count)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_CHAR_COLS = {
    "pitch": "Pitch", "count": "#", "usage_pct": "Usage%",
    "avg_velo": "Velo", "max_velo": "Max", "spin_rate": "Spin",
    "ivb": "IVB", "hb": "HB", "extension": "Ext",
}


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    char = P.pitch_characteristics(df)[list(_CHAR_COLS)].rename(columns=_CHAR_COLS)
    return html.Div([
        section("Pitch Characteristics"),
        tables.df_table(char, id_="pb-char"),
        section("Velocity Trend"),
        dcc.Tabs(id="pb-velo-tabs", value="inning", children=[
            dcc.Tab(label="By Inning", value="inning",
                    children=[dcc.Graph(figure=P.fig_velo_by_inning(df))]),
            dcc.Tab(label="By Pitch Count", value="pc",
                    children=[dcc.Graph(figure=P.fig_velo_by_pitch(df))]),
        ]),
    ])
```

- [ ] **Step 4: Wire it into the tab-content callback**

In `app/dashboards/pitching/callbacks.py`, add the import and replace the `breakdown` branch of `_render_tab`:

```python
from app.dashboards.pitching.tabs import pitch_breakdown
```

```python
        if tab == "breakdown":
            return pitch_breakdown.render(df)
```

(Leave the final `return html.Div(f"[{tab}] ...")` for the not-yet-built tabs.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/pitching/tabs/pitch_breakdown.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): Pitch Breakdown tab"
```

---

## Task 6: Location / Movement tab

**Files:**
- Create: `app/dashboards/pitching/tabs/location_movement.py`
- Modify: `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `P.fig_movement(df)`, `P.fig_location(df)`, `P.pitch_type(df)`; `tables.df_table`; `shell.section`.
- Produces: `location_movement.render(df: pd.DataFrame) -> dash.html.Div`.

- [ ] **Step 1: Write the failing test**

```python
def test_location_movement_render(outing_df):
    from app.dashboards.pitching.tabs import location_movement
    assert location_movement.render(outing_df) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_location_movement_render -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `location_movement.py`**

The all-pitches table shows the columns a coach scans: pitch type, count, velo, result. Build it from the raw df with `P.pitch_type`.

```python
"""Location / Movement tab: movement map + location scatter + all-pitches table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def _all_pitches(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "Pitch": P.pitch_type(df),
        "Count": df["balls"].astype("Int64").astype(str) + "-"
                 + df["strikes"].astype("Int64").astype(str),
        "Velo": df["rel_speed"].round(1),
        "IVB": df["induced_vert_break"].round(1),
        "HB": df["horz_break"].round(1),
        "Result": df["pitch_call"],
    })
    return out.reset_index(drop=True)


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([
        html.Div([
            html.Div([section("Movement"), dcc.Graph(figure=P.fig_movement(df))],
                     style={"flex": "1"}),
            html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                     style={"flex": "1"}),
        ], style={"display": "flex", "gap": "16px"}),
        section("All Pitches"),
        tables.df_table(_all_pitches(df), id_="lm-all"),
    ])
```

- [ ] **Step 4: Wire it into the callback**

In `callbacks.py`:

```python
from app.dashboards.pitching.tabs import location_movement
```

```python
        if tab == "location":
            return location_movement.render(df)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/pitching/tabs/location_movement.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): Location/Movement tab"
```

---

## Task 7: RHH v. LHH tab

**Files:**
- Create: `app/dashboards/pitching/tabs/rhh_lhh.py`
- Modify: `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `P.splits_by_batter_side(df)` (returns `{"Left": {...}, "Right": {...}}` with `overall` dict + `usage` DataFrame), `P.fig_location_split(df)`; `tables.df_table`; `shell.section`.
- Produces: `rhh_lhh.render(df: pd.DataFrame) -> dash.html.Div`.

- [ ] **Step 1: Write the failing test**

```python
def test_rhh_lhh_render(outing_df):
    from app.dashboards.pitching.tabs import rhh_lhh
    assert rhh_lhh.render(outing_df) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_rhh_lhh_render -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `rhh_lhh.py`**

`fig_location_split(df)` filters internally by side; pass the per-side subset. Usage tables come from `splits_by_batter_side`.

```python
"""RHH v. LHH tab: side-by-side usage + location vs left/right-handed hitters."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_USAGE_COLS = {"pitch": "Pitch", "count": "#", "usage_pct": "Usage%"}


def _side_col(df: pd.DataFrame, side: str, usage: pd.DataFrame) -> html.Div:
    sub = df[df["batter_side"] == side]
    tbl = (usage[list(_USAGE_COLS)].rename(columns=_USAGE_COLS)
           if not usage.empty else pd.DataFrame(columns=list(_USAGE_COLS.values())))
    return html.Div([
        section(f"vs {side}-handed"),
        tables.df_table(tbl, id_=f"split-usage-{side.lower()}"),
        dcc.Graph(figure=P.fig_location_split(sub)),
    ], style={"flex": "1"})


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    splits = P.splits_by_batter_side(df)
    return html.Div([
        _side_col(df, "Left", splits["Left"]["usage"]),
        _side_col(df, "Right", splits["Right"]["usage"]),
    ], style={"display": "flex", "gap": "16px"})
```

- [ ] **Step 4: Wire it into the callback**

In `callbacks.py`:

```python
from app.dashboards.pitching.tabs import rhh_lhh
```

```python
        if tab == "splits":
            return rhh_lhh.render(df)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/pitching/tabs/rhh_lhh.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): RHH v. LHH tab"
```

---

## Task 8: Last Outings tab

**Files:**
- Create: `app/dashboards/pitching/tabs/last_outings.py`
- Modify: `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `P.recent_outings(pitcher_id, game_id, n)` (cols include `game_date, away_team_name, home_team_name, appearance_avg_velo, appearance_max_velo, pitch_count`), `P.averages_last5(recent_df)`; `tables.df_table`; `shell.section`. This tab is multi-game, so it needs `pitcher_id`+`game_id` from the selection Store, not just the single-game df.
- Produces: `last_outings.render(pitcher_id, game_id, n: int = 5) -> dash.html.Div`.

- [ ] **Step 1: Write the failing test**

```python
def test_last_outings_render(real_pitcher):
    from app.data import pitching as P
    from app.dashboards.pitching.tabs import last_outings
    gid = int(P.games_for_pitcher(real_pitcher).iloc[0]["game_id"])
    assert last_outings.render(real_pitcher, gid, 5) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_last_outings_render -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `last_outings.py`**

```python
"""Last Outings tab: averages across the last N appearances + a trend table."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_COLS = {
    "game_date": "Date", "appearance_avg_velo": "Avg Velo",
    "appearance_max_velo": "Max Velo", "pitch_count": "Pitches",
}


def render(pitcher_id, game_id, n: int = 5) -> html.Div:
    if pitcher_id is None or game_id is None:
        return html.Div("No outing selected.")
    recent = P.recent_outings(int(pitcher_id), int(game_id), n)
    if recent.empty:
        return html.Div("No prior outings.")
    avg = P.averages_last5(recent)
    show = avg[[c for c in _COLS if c in avg.columns]].rename(columns=_COLS)
    return html.Div([
        section(f"Last {len(show)} Outings"),
        tables.df_table(show, id_="lo-avgs"),
    ])
```

- [ ] **Step 4: Wire it into the callback**

The Last Outings tab needs the selection Store (pitcher_id + game_id), which `_render_tab` already receives as `sel`. In `callbacks.py`:

```python
from app.dashboards.pitching.tabs import last_outings
```

Replace the trailing placeholder return in `_render_tab` with:

```python
        if tab == "outings":
            sel = sel or {}
            return last_outings.render(sel.get("pitcher_id"), sel.get("game_id"), 5)
        return html.Div()
```

Note: the `outings` branch must run even when the single-game `df` is empty logic above returns early — move the `if df.empty` guard so it applies only to the game-df tabs. Adjust `_render_tab` so the empty-df message covers `breakdown`/`location`/`splits`, but `outings` is handled before that check:

```python
    def _render_tab(tab, data_json, sel):
        if tab == "outings":
            sel = sel or {}
            return last_outings.render(sel.get("pitcher_id"), sel.get("game_id"), 5)
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "breakdown":
            return pitch_breakdown.render(df)
        if tab == "location":
            return location_movement.render(df)
        if tab == "splits":
            return rhh_lhh.render(df)
        return html.Div()
```

- [ ] **Step 5: Run the full pitching + shell + hitting suites**

Run: `python -m pytest tests/test_pitching_dash.py tests/test_pitching.py tests/test_shell.py tests/test_hitting_dash.py -v`
Expected: PASS.

- [ ] **Step 6: Manual smoke check (both roles)**

Start the app; as **coach** open `/pitching` → Stats Dashboard, pick a pitcher + outing, click through all four tabs (charts + tables render, no console errors). Log in as the **player** demo (`hitter@lmu.edu` is a hitter — if no player pitcher account exists, note it and verify the coach path only; a player pitcher account can be created with `flask --app run create-user`). Confirm the player's pitcher dropdown is disabled/self-only. Kill the server by port owner.

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/pitching/tabs/last_outings.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): Last Outings tab; wire all four tabs"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** Section A (nav) → Task 2. Section B (shared shell) → Task 1. Section C (pitching module + 4 tabs) → Tasks 4–8. Section D (data layer) → Task 3 (+ reuse of existing transforms/figures noted per tab). Section E (testing) → tests in every task. Section F (deferred) → not built, hub shows HitTrax/Catching as "Coming soon" (Task 2). §6 no-notes-box → honored (no notes control in Task 5). All spec sections map to a task.

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. The scaffold's `_render_tab` intentionally returns a placeholder string in Task 4 and is replaced branch-by-branch in Tasks 5–8 (documented, not a plan placeholder).

**Type consistency:** `wh_lmu_pitchers` → columns `PitcherId`/`Pitcher` used by `selectors.pitcher_options`. `games_for_pitcher` → `game_id`/`GameLabel` used by `selectors.outing_options`. `pitcher_profile`/`season_summary` dict keys match `layout.sidebar`. Store keys `pitcher_id`/`game_id` consistent across `layout`, `callbacks`, `last_outings`. Component ids (`pitcher-dd`, `outing-dd`, `tabs` values `breakdown`/`location`/`splits`/`outings`) consistent across `layout` and `callbacks`.

---

## Task Checklist

- [ ] **Task 1 — Shared Dash shell + refactor hitting** (`app/dashboards/shell.py`; hitting index/layout onto it; brand values single-sourced)
- [ ] **Task 2 — Section hub navigation** (shared card macro; home cards → hubs; `/pitching` `/hitting` `/catching` routes + templates; HitTrax & Catching "Coming soon")
- [ ] **Task 3 — Pitching data-layer additions** (`wh_lmu_pitchers`, `_sibling_pitcher_ids`, `games_for_pitcher`, `pitcher_profile`, `season_summary`)
- [ ] **Task 4 — Pitching dashboard scaffold** (`app/dashboards/pitching/`: index, selectors, layout, callbacks, tables; mount `/dash/pitching/`; register)
- [ ] **Task 5 — Pitch Breakdown tab** (characteristics table + velo trend by inning/pitch count)
- [ ] **Task 6 — Location / Movement tab** (movement map + location scatter + all-pitches table)
- [ ] **Task 7 — RHH v. LHH tab** (side-by-side usage + location split by batter hand)
- [ ] **Task 8 — Last Outings tab** (last-N averages table; wire all four tabs; both-role smoke check)
- [ ] **Final — whole-branch review** (run full suite `python -m pytest -q`; requesting-code-review before merge)
