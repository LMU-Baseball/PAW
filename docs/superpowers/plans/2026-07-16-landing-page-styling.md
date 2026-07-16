# Landing Page Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the PAW shared shell and the pitching-report landing page an "athletic/broadcast" branded look (direction B) — presentational only, no behavior changes.

**Architecture:** Two Jinja templates get restyled. `base.html` (the shared shell every page extends) gains a local Teko `@font-face` block, CSS design tokens in `:root`, a crimson header with the LMU logo, and restyled shared `.card`/`.btn`/`.flash`/form styles — so all pages inherit the polish. `pitching_landing.html` (extends `base.html`) gains a crimson hero banner, a styled game-picker card, a matchup header, and pitcher row cards. All styling is inline `<style>`/inline attributes, matching the existing codebase pattern. No new files, routes, data helpers, or dependencies.

**Tech Stack:** Flask + Jinja2 templates, plain CSS. Assets (`lmu.png`, `lmu-bsb.png`, `Teko-*.ttf`) already live in `app/static/reports/`, served at `/static/reports/...`. Tests: pytest via the Flask test client.

## Global Constraints

- Presentational-only: no changes to routes, data helpers, or template context variables.
- No JavaScript. Server-rendered only.
- No new dependencies and no build step / CSS bundler.
- **No Google Fonts CDN** — Teko loads via local `@font-face` from `/static/reports/Teko-*.ttf` (offline / CSP).
- Assets stay in `app/static/reports/` (no file moves).
- Palette (exact values): crimson `#9A0021`, crimson-dark `#7a001a`, blue accent `#2864a8`, bg `#f5f5f5`, ink `#1a1a1a`.
- Fonts: Teko for display (headings, logo text, buttons); system-ui for body copy.
- Existing tests must keep passing unmodified; full suite is 73 passing before this work.
- Visual polish is verified live on the running app (`python run.py` → http://127.0.0.1:8050, use 127.0.0.1 not localhost). Automated tests only guard branded markup / asset references / no-CDN and existing content-and-link regressions.

---

## File Structure

- `app/templates/base.html` — MODIFY. Shared shell: `@font-face`, `:root` tokens, header with logo, restyled shared components. Inherited by every page.
- `app/templates/reports/pitching_landing.html` — MODIFY. Hero banner, picker card, matchup header, pitcher row cards.
- `tests/test_shell.py` — CREATE. Structural regression tests for the shell branding (asset refs, no CDN, brand link).
- `tests/test_pitching_landing.py` — MODIFY. Append one structural test for the hero image; existing tests are the behavior regression guard and stay untouched.

---

### Task 1: Brand the shared shell (`base.html`)

**Files:**
- Modify: `app/templates/base.html`
- Test: `tests/test_shell.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a shell that renders, in every page's HTML, (1) a local Teko `@font-face` referencing `/static/reports/Teko-Regular.ttf`, (2) an `<img>` with `src` containing `/static/reports/lmu.png` in the header, (3) a header brand cluster linking to `/`, (4) restyled `.card`/`.btn`/`.flash` classes and form controls using `:root` CSS variables. No `fonts.googleapis.com` or `fonts.gstatic.com` anywhere. Task 2 relies on these `:root` tokens (`--crimson`, `--crimson-dark`, `--blue`, `--bg`, `--ink`, `--radius`, `--shadow`, `--font-display`) and the `.card`/`.btn` classes existing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_shell.py`:

```python
"""Structural regression tests for the branded shared shell (base.html).

These assert that branded markup and local assets are present and that no
Google Fonts CDN is referenced. Visual polish is verified live, not here.
The shell renders on the login page (extends base.html), so no auth needed.
"""
from app import create_app
from config import Config


def _app():
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    return create_app(TestConfig)


def test_shell_loads_teko_locally_not_cdn():
    resp = _app().test_client().get("/login")
    body = resp.get_data(as_text=True)
    assert "@font-face" in body
    assert "/static/reports/Teko-Regular.ttf" in body
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body


def test_shell_header_shows_logo_linking_home():
    resp = _app().test_client().get("/login")
    body = resp.get_data(as_text=True)
    assert "/static/reports/lmu.png" in body
    assert 'href="/"' in body


def test_shell_defines_design_tokens():
    resp = _app().test_client().get("/login")
    body = resp.get_data(as_text=True)
    assert "--crimson" in body
    assert "--font-display" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_shell.py -v`
Expected: FAIL — `test_shell_loads_teko_locally_not_cdn` and `test_shell_defines_design_tokens` fail (no `@font-face`, no `--font-display`); `test_shell_header_shows_logo_linking_home` fails (no `lmu.png`, current header brand is a plain `<span>` not a link).

Note: if `/login` is not the login route in this app, adjust the path — verify with `pytest -v` output. (The auth blueprint registers `/login`; confirm the login template extends `base.html` before relying on it — if it does not, point these tests at another anonymous page that extends the shell.)

- [ ] **Step 3: Rewrite `base.html`**

Replace the entire contents of `app/templates/base.html` with:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}The PAW — LMU Baseball{% endblock %}</title>
  <style>
    @font-face {
      font-family: "Teko"; font-weight: 400; font-display: swap;
      src: url("{{ url_for('static', filename='reports/Teko-Regular.ttf') }}") format("truetype");
    }
    @font-face {
      font-family: "Teko"; font-weight: 500; font-display: swap;
      src: url("{{ url_for('static', filename='reports/Teko-Medium.ttf') }}") format("truetype");
    }
    @font-face {
      font-family: "Teko"; font-weight: 600; font-display: swap;
      src: url("{{ url_for('static', filename='reports/Teko-SemiBold.ttf') }}") format("truetype");
    }
    @font-face {
      font-family: "Teko"; font-weight: 700; font-display: swap;
      src: url("{{ url_for('static', filename='reports/Teko-Bold.ttf') }}") format("truetype");
    }
    :root {
      --crimson: #9A0021; --crimson-dark: #7a001a; --blue: #2864a8;
      --bg: #f5f5f5; --ink: #1a1a1a;
      --radius: 8px; --shadow: 0 2px 8px rgba(0,0,0,.08);
      --font-display: "Teko", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, sans-serif; color: var(--ink); background: var(--bg); }
    header.bar {
      background: var(--crimson); color: #fff; padding: 0 20px; height: 64px;
      display: flex; align-items: center; justify-content: space-between;
      box-shadow: var(--shadow);
    }
    header.bar .brand {
      display: flex; align-items: center; gap: 12px; text-decoration: none; color: #fff;
    }
    header.bar .brand img { height: 40px; width: auto; display: block; }
    header.bar .brand .wordmark {
      font-family: var(--font-display); font-weight: 700; font-size: 30px;
      line-height: 1; letter-spacing: 1px; text-transform: uppercase;
    }
    header.bar a { color: #fff; }
    .user { font-size: 14px; color: rgba(255,255,255,.85); }
    .user a { text-decoration: underline; }
    main.wrap { max-width: 900px; margin: 32px auto; padding: 0 20px; }
    h1, h2, h3 { font-family: var(--font-display); font-weight: 600; letter-spacing: .5px; }
    .flash { padding: 10px 14px; border-radius: var(--radius); margin-bottom: 14px; font-size: 14px; }
    .flash.error { background: #fdecea; color: #a3271f; border: 1px solid #f3b6b1; }
    .flash.info  { background: #e8f1fb; color: #1c5390; border: 1px solid #b6d4f3; }
    .card {
      background: #fff; border: 1px solid #e2e2e2; border-radius: var(--radius);
      padding: 24px; box-shadow: var(--shadow);
    }
    .btn {
      display: inline-block; background: var(--crimson); color: #fff; border: none;
      padding: 10px 20px; border-radius: var(--radius); font-size: 16px; cursor: pointer;
      text-decoration: none; font-family: var(--font-display); font-weight: 600;
      letter-spacing: .5px; text-transform: uppercase; transition: background .15s, transform .05s;
    }
    .btn:hover { background: var(--crimson-dark); }
    .btn:active { transform: translateY(1px); }
    label { display: block; margin: 12px 0 4px; font-size: 14px; font-weight: 600; }
    input[type=text], input[type=password], select {
      width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: var(--radius);
      font-size: 15px; background: #fff;
    }
    input[type=text]:focus, input[type=password]:focus, select:focus {
      outline: none; border-color: var(--crimson); box-shadow: 0 0 0 3px rgba(154,0,33,.15);
    }
  </style>
</head>
<body>
  <header class="bar">
    <a class="brand" href="{{ url_for('main.index') }}">
      <img src="{{ url_for('static', filename='reports/lmu.png') }}" alt="LMU">
      <span class="wordmark">The Paw</span>
    </a>
    {% if current_user.is_authenticated %}
      <span class="user">{{ current_user.name }} · {{ current_user.role }} ·
        <a href="{{ url_for('auth.logout') }}">Log out</a></span>
    {% endif %}
  </header>
  <main class="wrap">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for category, message in messages %}
        <div class="flash {{ category }}">{{ message }}</div>
      {% endfor %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

Note: the brand links to `url_for('main.index')`. Confirm the home route endpoint is `main.index` (it is referenced as such in `app/templates/main/index.html` context); if the endpoint name differs, use the correct one — the test only requires the rendered `href` to be `/`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_shell.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `pytest -q`
Expected: PASS — 76 passing (73 prior + 3 new).

- [ ] **Step 6: Verify live**

Run `python run.py`, open http://127.0.0.1:8050/login and any logged-in page. Confirm: crimson header shows the `lmu.png` logo + "The Paw" wordmark in Teko (condensed font, not a fallback), header links home, cards have soft shadows, buttons are crimson and darken on hover.

- [ ] **Step 7: Commit**

```bash
git add app/templates/base.html tests/test_shell.py
git commit -m "feat(ui): brand shared shell — Teko font, logo header, design tokens"
```

---

### Task 2: Brand the pitching-report page (`pitching_landing.html`)

**Files:**
- Modify: `app/templates/reports/pitching_landing.html`
- Test: `tests/test_pitching_landing.py` (append one test)

**Interfaces:**
- Consumes: from Task 1 — the `:root` tokens (`--crimson`, `--crimson-dark`, `--blue`, `--radius`, `--shadow`, `--font-display`) and the `.card`/`.btn` classes defined in `base.html`.
- Produces: a page whose HTML contains `/static/reports/lmu-bsb.png` (hero image) while preserving all existing behavior — the `name="game_id"` picker, both games' text, each pitcher's `display_name`, and the `/reports/pitcher/<game_id>/<pitcher_id>.pdf` links. No new template context variables.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pitching_landing.py`:

```python
def test_landing_renders_hero_banner(app_ctx, monkeypatch):
    monkeypatch.setattr("app.data.pitching.recent_games", lambda limit=25: _GAMES)
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    resp = client.get("/reports/pitching")
    body = resp.get_data(as_text=True)
    assert "/static/reports/lmu-bsb.png" in body   # branded hero image
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_pitching_landing.py::test_landing_renders_hero_banner -v`
Expected: FAIL — `lmu-bsb.png` not yet referenced.

- [ ] **Step 3: Rewrite `pitching_landing.html`**

Replace the entire contents of `app/templates/reports/pitching_landing.html` with:

```html
{% extends "base.html" %}
{% block title %}Pitching Reports — The PAW{% endblock %}
{% block content %}
<style>
  .hero {
    background: var(--crimson); color: #fff; border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 22px 26px; margin-bottom: 20px;
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  }
  .hero img { height: 56px; width: auto; display: block; }
  .hero .hero-text h1 {
    margin: 0; color: #fff; font-size: 40px; line-height: 1; text-transform: uppercase;
  }
  .hero .hero-text p { margin: 6px 0 0; color: rgba(255,255,255,.85); font-size: 15px; }
  .matchup {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 0 0 16px;
  }
  .matchup h3 { margin: 0; font-size: 26px; }
  .badge {
    font-size: 13px; font-weight: 600; padding: 4px 10px; border-radius: 999px;
    background: #eee; color: #333;
  }
  .badge.date { background: rgba(40,100,168,.12); color: var(--blue); }
  .pitcher-row {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    flex-wrap: wrap; padding: 14px 16px; border: 1px solid #e2e2e2;
    border-radius: var(--radius); margin-bottom: 10px; background: #fff;
    transition: box-shadow .15s, transform .05s;
  }
  .pitcher-row:hover { box-shadow: var(--shadow); transform: translateY(-1px); }
  .pitcher-row .name { font-family: var(--font-display); font-weight: 600; font-size: 22px; }
  .empty { color: #777; font-style: italic; }
</style>

<div class="hero">
  <img src="{{ url_for('static', filename='reports/lmu-bsb.png') }}" alt="LMU Baseball">
  <div class="hero-text">
    <h1>Pitching Reports</h1>
    <p>Pick a game, then download a pitcher's postgame report.</p>
  </div>
</div>

<div class="card">
  <form method="get" action="{{ url_for('reports.pitching_landing') }}">
    <label for="game_id">Game</label>
    <select name="game_id" id="game_id">
      <option value="">— Select a game —</option>
      {% for g in games %}
        <option value="{{ g.game_id }}" {% if g.game_id == game_id %}selected{% endif %}>
          {{ g.game_date }} · {{ g.away_team }} @ {{ g.home_team }}
          ({{ g.season_label }}{% if g.game_type %} · {{ g.game_type }}{% endif %})
        </option>
      {% endfor %}
    </select>
    <button type="submit" class="btn" style="margin-top: 14px;">Show pitchers</button>
  </form>
</div>

{% if game_id is not none %}
<div class="card" style="margin-top: 20px;">
  {% if selected_game %}
    <div class="matchup">
      <h3>{{ selected_game.away_team }} @ {{ selected_game.home_team }}</h3>
      <span class="badge date">{{ selected_game.game_date }}</span>
      {% if selected_game.season_label %}
        <span class="badge">{{ selected_game.season_label }}{% if selected_game.game_type %} · {{ selected_game.game_type }}{% endif %}</span>
      {% endif %}
    </div>
  {% else %}
    <div class="matchup"><h3>Selected game</h3></div>
  {% endif %}

  {% if pitchers %}
    {% for p in pitchers %}
      <div class="pitcher-row">
        <span class="name">{{ p.display_name }}</span>
        <a class="btn" href="{{ url_for('reports.pitcher_pdf', game_id=game_id, pitcher_id=p.player_id) }}">
          Download Report ↓
        </a>
      </div>
    {% endfor %}
  {% else %}
    <p class="empty">No pitchers found for this game.</p>
  {% endif %}
</div>
{% endif %}
{% endblock %}
```

Note: `selected_game` fields used here (`away_team`, `home_team`, `game_date`, `season_label`, `game_type`) match the existing template's usage and the `_GAMES` test fixture — no new context variables introduced.

- [ ] **Step 4: Run the pitching-landing tests to verify they pass**

Run: `pytest tests/test_pitching_landing.py -v`
Expected: PASS — the new hero test plus the 3 existing behavior tests (games listed, pitchers + download links, anonymous redirect) all pass, confirming no behavior regression.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS — 77 passing (76 after Task 1 + 1 new).

- [ ] **Step 6: Verify live**

Run `python run.py`, log in as coach (`coach@lmu.edu` / `paw2026`), open http://127.0.0.1:8050/reports/pitching. Confirm: crimson hero shows `lmu-bsb.png` + "PITCHING REPORTS"; picking a game shows the "AWAY @ HOME" matchup header with date/season badges and pitcher row cards, each with a crimson "Download Report ↓" button that returns a real PDF; the button wraps below the name when the window is narrow.

- [ ] **Step 7: Commit**

```bash
git add app/templates/reports/pitching_landing.html tests/test_pitching_landing.py
git commit -m "feat(ui): brand pitching-report page — hero, matchup header, pitcher cards"
```

---

## Self-Review

**1. Spec coverage:**
- Fonts / local `@font-face` / no CDN → Task 1 Step 3 + test `test_shell_loads_teko_locally_not_cdn`. ✓
- Design tokens in `:root` → Task 1 Step 3 + test `test_shell_defines_design_tokens`. ✓
- Header with logo + Teko wordmark linking home → Task 1 Step 3 + test `test_shell_header_shows_logo_linking_home`. ✓
- Restyled shared `.card`/`.btn`/`.flash` + form focus ring → Task 1 Step 3. ✓
- Hero banner with `lmu-bsb.png` → Task 2 Step 3 + test `test_landing_renders_hero_banner`. ✓
- Styled picker card (GET form, no JS) → Task 2 Step 3; behavior guarded by existing `test_landing_lists_games`. ✓
- Matchup header with date/season/type badges → Task 2 Step 3. ✓
- Pitcher row cards + download button, responsive wrap → Task 2 Step 3; links guarded by existing `test_landing_shows_pitchers_and_download_links`. ✓
- Empty state styled → Task 2 Step 3. ✓
- Assets stay in `app/static/reports/` → both tasks reference `filename='reports/...'`; no moves. ✓
- No behavior/route/context changes; existing tests unmodified → confirmed; only additive tests. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". All code blocks are complete and copy-paste ready. ✓

**3. Type consistency:** `:root` token names (`--crimson`, `--crimson-dark`, `--blue`, `--bg`, `--ink`, `--radius`, `--shadow`, `--font-display`) and class names (`.card`, `.btn`) defined in Task 1 are used verbatim in Task 2. `selected_game`/`pitchers`/`games`/`game_id` context names match the existing template and test fixtures. ✓
