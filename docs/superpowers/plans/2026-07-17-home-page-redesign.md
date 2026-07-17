# Home Page Redesign + Brand Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the home/landing page in the R app's design language (marquee hero + module cards) and refresh the whole app to the official LMU brand colors.

**Architecture:** Presentational only — no new routes or data. `base.html` gets official color tokens + a self-hosted Alfa Slab One font. `main/index.html` is rebuilt as a crimson marquee hero (LIONS wordmark + "THE PAW" in Alfa Slab One + role-aware welcome) over three module cards, with a subtle palms motif. The official crimson is swept everywhere including the PDF report (hue only; report layout unchanged).

**Tech Stack:** Flask + Jinja2 templates, plain CSS (no framework, no CDN), matplotlib (report charts), pytest, Playwright (visual check).

## Global Constraints

- Official LMU Crimson = **#AB0C2F**; official LMU Blue = **#0076A5** (verbatim from spec).
- Derived shades allowed for contrast: `--crimson-dark: #8a0a26`, `--blue-dark: #005e84`.
- **No web fonts via CDN** — all fonts self-hosted under `app/static/`. Never reference `fonts.googleapis.com` / `fonts.gstatic.com`.
- Report *layout/content* must not change — only the crimson/blue hue.
- Full test suite must stay green (currently **108 passing**). Run `python -m pytest -q`.
- App run/restart: kill by port owner then relaunch a single instance (see repo memory); templates/CSS auto-reload, Python needs restart.

---

### Task 1: Official brand tokens + Alfa Slab One font (base.html)

**Files:**
- Create: `app/static/brand/AlfaSlabOne-Regular.ttf` (downloaded)
- Modify: `app/templates/base.html` (the `<style>` `:root` block + `@font-face` list + focus rgba)
- Test: `tests/test_shell.py`

**Interfaces:**
- Produces: CSS custom properties `--crimson` (#AB0C2F), `--crimson-dark` (#8a0a26), `--blue` (#0076A5), `--blue-dark` (#005e84), `--font-display` (Teko, unchanged), `--font-marquee` ("Alfa Slab One", Georgia, serif). Self-hosted font family `"Alfa Slab One"` at `static/brand/AlfaSlabOne-Regular.ttf`. Consumed by Task 2.

- [ ] **Step 1: Download the Alfa Slab One font**

Run:
```bash
curl -L -o "app/static/brand/AlfaSlabOne-Regular.ttf" \
  "https://github.com/google/fonts/raw/main/ofl/alfaslabone/AlfaSlabOne-Regular.ttf"
```
Expected: a ~50-120KB TTF. Verify:
```bash
python -c "from pathlib import Path; b=Path('app/static/brand/AlfaSlabOne-Regular.ttf').read_bytes(); print(len(b), b[:4])"
```
Expected: a size in the tens/hundreds of KB and a font magic header (`b'\x00\x01\x00\x00'` or `b'OTTO'` or `b'true'`).
**Fallback if the download fails (offline):** skip this file; in Step 5 set `--font-marquee: "Teko", system-ui, sans-serif;` and DO NOT add the Alfa Slab `@font-face`; note the fallback in the commit message. If fallback is used, Step 3's new test asserting the AlfaSlabOne path must be omitted.

- [ ] **Step 2: Write the failing shell tests**

Append to `tests/test_shell.py`:
```python
def test_shell_loads_alfa_slab_locally_not_cdn():
    body = _app().test_client().get("/login").get_data(as_text=True)
    assert "/static/brand/AlfaSlabOne-Regular.ttf" in body
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body


def test_shell_uses_official_lmu_colors():
    body = _app().test_client().get("/login").get_data(as_text=True)
    assert "#AB0C2F" in body   # official LMU Crimson
    assert "#0076A5" in body   # official LMU Blue
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_shell.py -q`
Expected: the two new tests FAIL (old hex `#9A0021` / no Alfa Slab path yet); the original 3 still pass.

- [ ] **Step 4: Update the `@font-face` block in `app/templates/base.html`**

Immediately after the last Teko `@font-face` (the weight-700 one ending at the `}` before `:root`), add:
```css
    @font-face {
      font-family: "Alfa Slab One"; font-weight: 400; font-display: swap;
      src: url("{{ url_for('static', filename='brand/AlfaSlabOne-Regular.ttf') }}") format("truetype");
    }
```

- [ ] **Step 5: Update the `:root` tokens and focus ring in `app/templates/base.html`**

Replace the existing `:root { ... }` block with:
```css
    :root {
      --crimson: #AB0C2F; --crimson-dark: #8a0a26;
      --blue: #0076A5; --blue-dark: #005e84;
      --bg: #f5f5f5; --ink: #1a1a1a;
      --radius: 8px; --shadow: 0 2px 8px rgba(0,0,0,.08);
      --font-display: "Teko", system-ui, sans-serif;
      --font-marquee: "Alfa Slab One", Georgia, serif;
    }
```
Then replace the focus-ring shadow `box-shadow: 0 0 0 3px rgba(154,0,33,.15);` with:
```css
      outline: none; border-color: var(--crimson); box-shadow: 0 0 0 3px rgba(171,12,47,.15);
```

- [ ] **Step 6: Run the shell tests to verify they pass**

Run: `python -m pytest tests/test_shell.py -q`
Expected: all 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add app/static/brand/AlfaSlabOne-Regular.ttf app/templates/base.html tests/test_shell.py
git commit -m "feat(brand): official LMU colors + self-hosted Alfa Slab One in base shell"
```

---

### Task 2: Home page marquee hero + module cards (index.html)

**Files:**
- Modify: `app/templates/main/index.html` (full rewrite of the content block)
- Test: `tests/test_home.py` (create)

**Interfaces:**
- Consumes: `base.html` tokens `--crimson`, `--blue-dark`, `--font-marquee`, `--font-display`, `--radius`, `--shadow` (Task 1); assets `static/brand/lions-arch.png` and `static/brand/palms.png` (already in repo); route `main.index` passes `user=current_user` (unchanged); `user.name`, `user.is_coach`.
- Produces: the rendered home page (no downstream consumers).

- [ ] **Step 1: Write the failing home-page tests**

Create `tests/test_home.py`:
```python
"""Home/landing page: marquee hero + module cards, role-aware copy."""
import pytest

from app import create_app
from app.extensions import db
from app.auth.models import User
from config import Config


@pytest.fixture
def app_ctx(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    app = create_app(TestConfig)
    with app.app_context():
        for email, role, name in [("c@lmu.edu", "coach", "Coach C"),
                                   ("p@lmu.edu", "player", "Player P")]:
            u = User(email=email, name=name, role=role)
            u.set_password("x")
            db.session.add(u)
        db.session.commit()
    return app


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "x"},
                       follow_redirects=True)


def test_home_shows_hero_and_module_cards(app_ctx):
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    body = client.get("/").get_data(as_text=True)
    assert "THE PAW" in body                              # marquee
    assert "/static/brand/lions-arch.png" in body         # hero wordmark
    assert "/static/brand/palms.png" in body              # palms motif
    assert "/dash/hitting/" in body                       # Hitting module
    assert "/reports/pitching" in body                    # Pitching module
    assert "Coming soon" in body                          # Catching disabled
    assert "coach" in body                                # role copy


def test_home_player_sees_player_copy(app_ctx):
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    body = client.get("/").get_data(as_text=True)
    assert "player" in body
    assert "Player P" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_home.py -q`
Expected: FAIL (current index has no "THE PAW"/lions-arch/palms/"Coming soon").

- [ ] **Step 3: Rewrite `app/templates/main/index.html`**

Replace the entire file with:
```html
{% extends "base.html" %}
{% block title %}The PAW — LMU Baseball{% endblock %}
{% block content %}
<style>
  .home-hero {
    position: relative; overflow: hidden; text-align: center;
    background: var(--crimson); color: #fff;
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
  .home-hero .welcome {
    margin: 14px auto 0; max-width: 640px; font-size: 15px; color: rgba(255,255,255,.92);
  }
  .home-hero .welcome strong { color: #fff; }

  .modules-section { position: relative; margin-top: 26px; padding-bottom: 40px; }
  .palms {
    position: absolute; left: 0; right: 0; bottom: 0; width: 100%;
    opacity: .12; pointer-events: none; z-index: 0;
  }
  .modules {
    position: relative; z-index: 1;
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
  }
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
  <img class="palms" src="{{ url_for('static', filename='brand/palms.png') }}" alt="" aria-hidden="true">
  <div class="modules">
    <a class="module" href="/dash/hitting/">
      <h3>Hitting</h3>
      <p>Swing decisions, batted ball, plate discipline.</p>
    </a>
    <a class="module" href="{{ url_for('reports.pitching_landing') }}">
      <h3>Pitching Reports</h3>
      <p>Postgame pitcher reports (PDF).</p>
    </a>
    <div class="module disabled">
      <h3>Catching</h3>
      <p>Blocking, framing, throws.</p>
      <span class="soon">Coming soon</span>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Run the home-page tests to verify they pass**

Run: `python -m pytest tests/test_home.py -q`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/main/index.html tests/test_home.py
git commit -m "feat(home): marquee hero + module cards landing page"
```

---

### Task 3: Sweep official crimson through the report + remaining templates

**Files:**
- Modify: `app/reports/static/report.css`
- Modify: `app/reports/plots.py`
- Modify: `app/templates/reports/pitching_landing.html` (hardcoded crimson rgba only)
- Test: `tests/test_brand_colors.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: report + landing hover use official crimson `#AB0C2F`; no `#9A0021` remains anywhere in `app/`.

- [ ] **Step 1: Write the failing color-sweep test**

Create `tests/test_brand_colors.py`:
```python
"""Guard: the legacy crimson #9A0021 is fully replaced by official #AB0C2F."""
from pathlib import Path

import pytest

_FILES = [
    "app/reports/static/report.css",
    "app/reports/plots.py",
    "app/templates/reports/pitching_landing.html",
    "app/templates/base.html",
    "app/templates/main/index.html",
]


@pytest.mark.parametrize("path", _FILES)
def test_no_legacy_crimson(path):
    text = Path(path).read_text(encoding="utf-8")
    assert "#9A0021" not in text, f"legacy crimson still in {path}"
    assert "154,0,33" not in text and "154, 0, 33" not in text, f"legacy crimson rgba in {path}"


def test_report_css_has_official_crimson():
    text = Path("app/reports/static/report.css").read_text(encoding="utf-8")
    assert "#AB0C2F" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_brand_colors.py -q`
Expected: FAIL (legacy `#9A0021` present in report.css / plots.py, `154,0,33` in pitching_landing.html).

- [ ] **Step 3: Swap crimson in `app/reports/static/report.css`**

Make these exact replacements:
- `.hdr { ... background: #9A0021; ... }` → `background: #AB0C2F;`
- `.panel-t { ... color: #9A0021; ... }` → `color: #AB0C2F;`
- `.chip.good        { background: #d6e4f5; color: #1e4d8c; }` → `color: #005e84;`
- `.chip.good-strong { background: #1e4d8c; color: #fff;    }` → `background: #005e84;`
- `.chip.bad-strong  { background: #9A0021; color: #fff;    }` → `background: #AB0C2F;`

(`.chip.bad` light-red tint stays as-is.)

- [ ] **Step 4: Swap crimson in `app/reports/plots.py`**

Replace all occurrences of `#9A0021` with `#AB0C2F` (the `_PALETTE[0]` entry, the `"Fastball"`/`"Four-Seam"`/`"FourSeamFastBall"` entries in `_PITCH_COLOR`, and the two `set_title(..., color="#9A0021")` calls). Use a global replace, then verify:
```bash
python -c "import pathlib; print('#9A0021' in pathlib.Path('app/reports/plots.py').read_text())"
```
Expected: `False`.

- [ ] **Step 5: Swap the hardcoded crimson rgba in `app/templates/reports/pitching_landing.html`**

Replace `.seg-opt:hover { background: rgba(154,0,33,.08); }` with `background: rgba(171,12,47,.08);`. Verify no other `154,0,33` remains in that file.

- [ ] **Step 6: Run the color-sweep test to verify it passes**

Run: `python -m pytest tests/test_brand_colors.py -q`
Expected: all PASS.

- [ ] **Step 7: Clear the report cache (stale PDFs use the old hue)**

Run:
```bash
rm -f instance/report_cache/*.pdf
```

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (110: prior 108 + Task 2's 2 + this task's 4, minus none — confirm the count is green, not the exact number).

- [ ] **Step 9: Commit**

```bash
git add app/reports/static/report.css app/reports/plots.py app/templates/reports/pitching_landing.html tests/test_brand_colors.py
git commit -m "feat(brand): sweep official LMU crimson through report + landing"
```

---

## Final verification (not a task — run after all tasks)

- Restart the app (kill by port owner, relaunch one instance) and log in.
- Playwright screenshot of `/` as coach and as player — confirm the marquee, LIONS wordmark, palms motif, three module cards, and correct role copy.
- Re-download one pitcher report — confirm the crimson header/chips/charts read as the official `#AB0C2F` and the layout is unchanged.

## Self-Review (completed while writing)

- **Spec coverage:** tokens+font (T1), hero+cards+role copy+palms (T2), report/landing color sweep + cache clear (T3), tests in every task, visual verification listed. All spec sections mapped.
- **Placeholders:** none — full code/commands in every step; offline font fallback spelled out.
- **Type/name consistency:** token names (`--crimson`, `--blue-dark`, `--font-marquee`) and asset paths (`brand/lions-arch.png`, `brand/palms.png`, `brand/AlfaSlabOne-Regular.ttf`) match across Task 1 → Task 2; `user.is_coach`/`user.name` match the existing route.
