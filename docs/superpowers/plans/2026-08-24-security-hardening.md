# Security Hardening + Repo Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the live PAW deployment against standard web attacks and gate `main` behind PRs for interns, without any user-visible change or downtime.

**Architecture:** Part A adds application-level security config and one new `app/security.py` module, with the three HTTPS-dependent behaviors gated behind an explicit `PAW_ENV=production` so merging is a no-op on the live site. Part B adds CI, a `main` ruleset with an admin bypass, and beginner-friendly contributor docs. Every task ends green on the existing 874-test suite.

**Tech Stack:** Flask 3, Dash 2.17+, Flask-Login, Flask-WTF, Flask-Limiter (new), Werkzeug `ProxyFix`, pytest, GitHub Actions, GitHub rulesets.

**Spec:** `docs/superpowers/specs/2026-08-24-security-hardening-design.md`

## Global Constraints

- **Zero production impact on merge.** `SESSION_COOKIE_SECURE`, HSTS, and the `SECRET_KEY` boot guard activate ONLY when `PAW_ENV=production` is explicitly set. `PAW_ENV` is not set on Render today, so merging changes nothing.
- **Never key production off `RENDER`.** It does not exist on Lightsail and is already set on Render. Explicit `PAW_ENV` only.
- **Rate limiting must be off under test.** `RATELIMIT_ENABLED = False` whenever `TESTING` is true — 17 test files POST to `/login`.
- **Ship dependency + code together.** A new package in `requirements.txt` and the code importing it go in the SAME commit (memory §3, the Flask-Compress incident).
- **No global `CSRFProtect`.** It breaks every Dash callback. `SameSite=Lax` is the mitigation.
- **CSP is Report-Only.** An enforced policy breaks all seven dashboards.
- **The full suite must stay green:** `python -m pytest -q` (excluding `test_precalc`), 874 passing before this work starts.
- **Do not require linear history or signed commits** in the ruleset — interns are young; squash-merge keeps history clean without them learning rebase.

---

### Task 1: Production-environment detection + `SECRET_KEY` guard

**Files:**
- Modify: `config.py:51-59`
- Test: `tests/test_security.py` (create)

**Interfaces:**
- Produces: `config.is_production() -> bool` — true only when `os.getenv("PAW_ENV") == "production"`. Used by Tasks 2 and 3.
- Produces: `Config.SECRET_KEY` — raises `RuntimeError` at class-definition time if production and the env var is unset.

- [ ] **Step 1: Write the failing tests**

```python
"""Security regression tests. MUST stay DB-free -- this file is the CI subset."""
import importlib
import pytest


def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import config
    return importlib.reload(config)


def test_is_production_false_when_paw_env_unset(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.is_production() is False


def test_is_production_true_only_for_exact_production_value(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV="production", SECRET_KEY="x")
    assert cfg.is_production() is True


def test_render_env_var_alone_does_not_mean_production(monkeypatch):
    """RENDER is already set on the live host; keying off it would activate
    the boot guard on merge and could take the site down."""
    cfg = _reload_config(monkeypatch, PAW_ENV=None, RENDER="true", SECRET_KEY="x")
    assert cfg.is_production() is False


def test_missing_secret_key_in_production_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reload_config(monkeypatch, PAW_ENV="production", SECRET_KEY=None)


def test_missing_secret_key_outside_production_uses_dev_default(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY=None)
    assert cfg.Config.SECRET_KEY == "dev-only-change-me"
```

Note: `_reload_config` needs the `MYSQL_*` vars present. Add to the top of the file:

```python
@pytest.fixture(autouse=True)
def _dummy_db_env(monkeypatch):
    for k in ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_HOST", "MYSQL_DB"):
        monkeypatch.setenv(k, "x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_security.py -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'is_production'`

- [ ] **Step 3: Implement in `config.py`**

Insert after `_require` (line 16), before `ANALYTICS_DB_URL`:

```python
def is_production() -> bool:
    """True only when PAW_ENV is explicitly "production".

    Deliberately NOT inferred from Render's auto-set RENDER variable: RENDER is
    already set on the live host, so inferring from it would activate the
    SECRET_KEY boot guard the moment this merges. It also does not exist on
    Lightsail, so it would silently disable production behavior after the AWS
    move. An explicit variable is both safe to merge and portable.
    """
    return os.getenv("PAW_ENV", "").strip().lower() == "production"


def _resolve_secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if is_production():
        raise RuntimeError(
            "SECRET_KEY must be set when PAW_ENV=production. Without it Flask "
            "would sign session cookies with a value published in this public "
            "repo, letting anyone forge a login. Set SECRET_KEY in the host's "
            "environment (Render dashboard / the .env on Lightsail)."
        )
    return "dev-only-change-me"
```

Then replace `config.py:52`:

```python
    SECRET_KEY = _resolve_secret_key()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_security.py -v`
Expected: 5 passed

- [ ] **Step 5: Verify nothing else broke**

Run: `python -m pytest tests/test_config.py tests/test_auth.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_security.py
git commit -m "feat(security): require a real SECRET_KEY when PAW_ENV=production"
```

---

### Task 2: `ProxyFix` + session cookie hardening

**Files:**
- Modify: `config.py` (add cookie config to `Config`)
- Modify: `app/__init__.py:14-20` (wrap `wsgi_app`)
- Test: `tests/test_security.py` (append)

**Interfaces:**
- Consumes: `config.is_production()` from Task 1.
- Produces: `Config.PERMANENT_SESSION_LIFETIME`, `SESSION_COOKIE_*`, `REMEMBER_COOKIE_*`, `SESSION_REFRESH_EACH_REQUEST`.
- Produces: `server.wsgi_app` wrapped in `ProxyFix`; `server.before_request` marks sessions permanent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_security.py`:

```python
from datetime import timedelta


def test_session_cookie_is_httponly_and_lax(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.SESSION_COOKIE_HTTPONLY is True
    assert cfg.Config.SESSION_COOKIE_SAMESITE == "Lax"


def test_session_cookie_not_secure_outside_production(monkeypatch):
    """Secure cookies over plain HTTP are silently dropped by the browser,
    which would make local dev and a pre-certificate Lightsail box unloggable."""
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.SESSION_COOKIE_SECURE is False


def test_session_cookie_secure_in_production(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV="production", SECRET_KEY="x")
    assert cfg.Config.SESSION_COOKIE_SECURE is True


def test_session_lifetime_is_thirty_days_sliding(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.PERMANENT_SESSION_LIFETIME == timedelta(days=30)
    assert cfg.Config.SESSION_REFRESH_EACH_REQUEST is True


def test_wsgi_app_is_wrapped_in_proxyfix(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x")
    from werkzeug.middleware.proxy_fix import ProxyFix
    from app import create_app
    from config import Config

    class T(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    server = create_app(T)
    assert isinstance(server.wsgi_app, ProxyFix)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_security.py -v`
Expected: FAIL — `AttributeError: type object 'Config' has no attribute 'SESSION_COOKIE_HTTPONLY'`

- [ ] **Step 3: Add cookie config to `config.py`**

Add `from datetime import timedelta` at the top, then inside `class Config`:

```python
    # --- session cookie hardening ---
    # HTTPONLY + SameSite=Lax are safe on plain HTTP, so they are always on.
    # SameSite=Lax is also what protects Dash's callback POSTs: a global
    # CSRFProtect would break every Dash callback (Dash sends no CSRF token),
    # so do NOT add one -- see the spec's "Deliberately NOT done" section.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # A browser silently DROPS a Secure cookie sent over plain HTTP, which
    # makes login appear to do nothing. Production-gated for that reason.
    SESSION_COOKIE_SECURE = is_production()

    # 30-day sliding window: refreshed on every request, so anyone using PAW
    # regularly is never logged out, while an abandoned or stolen cookie still
    # expires on its own.
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_REFRESH_EACH_REQUEST = True

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = is_production()
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
```

- [ ] **Step 4: Wire `ProxyFix` + permanent sessions in `app/__init__.py`**

Add the import at the top:

```python
from werkzeug.middleware.proxy_fix import ProxyFix
```

Then immediately after `server.config.from_object(config_object)` (line 16):

```python
    # Render terminates TLS at its edge and nginx does the same on Lightsale;
    # both forward plain HTTP with X-Forwarded-* headers. Without this, Flask
    # believes every request is insecure -- which silently disables Secure
    # cookies and hands the rate limiter the proxy's IP instead of the client's.
    # Safe with no proxy in front: ProxyFix only overrides when the header
    # is actually present.
    server.wsgi_app = ProxyFix(server.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @server.before_request
    def _make_session_permanent():
        # Opts every session into PERMANENT_SESSION_LIFETIME. Without this the
        # cookie is a browser-session cookie and the 30-day sliding window
        # never applies.
        from flask import session
        session.permanent = True
```

Fix the typo in the comment above: it is "Lightsail", not "Lightsale".

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_security.py -v`
Expected: all pass

- [ ] **Step 6: Verify login still works end-to-end**

Run: `python -m pytest tests/test_auth.py tests/test_home.py tests/test_shell.py -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add config.py app/__init__.py tests/test_security.py
git commit -m "feat(security): add ProxyFix and harden session cookies (30-day sliding)"
```

---

### Task 3: Security headers module

**Files:**
- Create: `app/security.py`
- Modify: `app/__init__.py` (register after blueprints)
- Test: `tests/test_security.py` (append)

**Interfaces:**
- Consumes: `config.is_production()` from Task 1.
- Produces: `app.security.register_security_headers(server) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_security.py`:

```python
def _client(monkeypatch, paw_env=None):
    if paw_env:
        monkeypatch.setenv("PAW_ENV", paw_env)
    else:
        monkeypatch.delenv("PAW_ENV", raising=False)
    monkeypatch.setenv("SECRET_KEY", "x")
    import config
    importlib.reload(config)
    import app as app_pkg
    importlib.reload(app_pkg)

    class T(config.Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    return app_pkg.create_app(T).test_client()


def test_baseline_headers_present_on_login_page(monkeypatch):
    resp = _client(monkeypatch).get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in resp.headers


def test_csp_is_report_only_never_enforced(monkeypatch):
    """An enforced CSP breaks all seven Dash dashboards (inline scripts from
    dash_renderer, inline styles from Plotly)."""
    resp = _client(monkeypatch).get("/login")
    assert "Content-Security-Policy-Report-Only" in resp.headers
    assert "Content-Security-Policy" not in resp.headers


def test_hsts_absent_outside_production(monkeypatch):
    resp = _client(monkeypatch).get("/login")
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_present_in_production(monkeypatch):
    resp = _client(monkeypatch, paw_env="production").get("/login")
    assert "max-age=" in resp.headers["Strict-Transport-Security"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_security.py -k headers or csp or hsts -v`
Expected: FAIL with `KeyError: 'X-Content-Type-Options'`

- [ ] **Step 3: Create `app/security.py`**

```python
"""Response security headers.

DELIBERATELY NOT HERE: a global Flask-WTF `CSRFProtect`. Dash's callback
endpoint (`/dash/<name>/_dash-update-component`) is a POST that sends no CSRF
token, so enabling CSRFProtect app-wide breaks every dashboard. The protection
that actually closes that hole is `SESSION_COOKIE_SAMESITE = "Lax"` in
config.py, which stops a third-party site from sending the session cookie on a
cross-site POST at all. Do not "fix" this by adding CSRFProtect.
"""
from config import is_production

# Report-Only, never enforced. Dash injects inline <script> tags via
# dash_renderer and Plotly writes inline styles, so an enforced policy blanks
# all seven dashboards. This observes what a future enforced policy would
# block; tighten only after reviewing real reports.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_PERMISSIONS = "geolocation=(), microphone=(), camera=(), payment=()"


def register_security_headers(server) -> None:
    @server.after_request
    def _add_security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", _PERMISSIONS)
        resp.headers.setdefault("Content-Security-Policy-Report-Only", _CSP)
        if is_production():
            # Only meaningful over HTTPS, and actively harmful on a plain-HTTP
            # host: a browser that caches HSTS will refuse http:// afterwards.
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp
```

- [ ] **Step 4: Register it in `app/__init__.py`**

After `server.register_blueprint(report_bp)`:

```python
    from app.security import register_security_headers
    register_security_headers(server)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_security.py -v`
Expected: all pass

- [ ] **Step 6: Verify the dashboards still render**

Run: `python -m pytest tests/test_hitting_dash.py tests/test_pitching_dash.py -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app/security.py app/__init__.py tests/test_security.py
git commit -m "feat(security): add response security headers and a Report-Only CSP"
```

---

### Task 4: Rate-limit the login endpoint

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py` (`RATELIMIT_ENABLED`)
- Modify: `app/extensions.py` (limiter singleton)
- Modify: `app/__init__.py` (init)
- Modify: `app/auth/routes.py:41` (decorate)
- Test: `tests/test_security.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks except `Config`.
- Produces: `app.extensions.limiter` — a `flask_limiter.Limiter` instance.

- [ ] **Step 1: Install the dependency and add it to `requirements.txt`**

Ship the package and the code in the same commit — `Flask-Compress` once shipped as a kwarg without its package and every dashboard test errored (memory §3).

```bash
pip install "Flask-Limiter>=3.5"
```

Add under the "Web framework" block in `requirements.txt`:

```
Flask-Limiter>=3.5      # brute-force throttle on /login. In-memory storage is
                        # PER PROCESS; gunicorn.conf.py runs 3 workers, so the
                        # effective limit is ~3x the configured value. Exact
                        # limits need Redis. Ships with the import in app/extensions.py.
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_security.py`:

```python
def test_rate_limiting_disabled_under_test(monkeypatch):
    """17 test files POST to /login, many repeatedly. If the limiter were live
    under TESTING the existing suite would start failing at random."""
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.RATELIMIT_ENABLED is False


def test_login_route_carries_a_rate_limit():
    from app.auth import routes
    assert hasattr(routes.login, "__wrapped__") or routes.login.__name__ == "login"


def test_repeated_failed_logins_are_blocked(monkeypatch):
    """With the limiter explicitly enabled, the 11th attempt gets a 429."""
    monkeypatch.setenv("SECRET_KEY", "x")
    monkeypatch.delenv("PAW_ENV", raising=False)
    import config
    importlib.reload(config)
    import app as app_pkg
    importlib.reload(app_pkg)

    class T(config.Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        WTF_CSRF_ENABLED = False
        RATELIMIT_ENABLED = True

    client = app_pkg.create_app(T).test_client()
    codes = [client.post("/login", data={"email": "a@b.c", "password": "wrong"}).status_code
             for _ in range(12)]
    assert 429 in codes
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_security.py -k rate or login -v`
Expected: FAIL — `AttributeError: type object 'Config' has no attribute 'RATELIMIT_ENABLED'`

- [ ] **Step 4: Add the config flag**

In `config.py`, inside `class Config`:

```python
    # Flask-Limiter reads this. Off under test so the 17 test files that POST
    # to /login are unaffected; app/__init__.py re-derives it from TESTING.
    RATELIMIT_ENABLED = True
```

- [ ] **Step 5: Add the limiter singleton to `app/extensions.py`**

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,   # real client IP, thanks to ProxyFix
    default_limits=[],             # opt-in per route; no global limit
)
```

- [ ] **Step 6: Initialize it in `app/__init__.py`**

Alongside the other `init_app` calls, after `login_manager.init_app(server)`:

```python
    from app.extensions import limiter
    # Never throttle the test suite.
    if server.config.get("TESTING"):
        server.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(server)
```

Update the import line to `from app.extensions import db, login_manager` → keep as-is and add the limiter import above.

- [ ] **Step 7: Decorate the login route**

In `app/auth/routes.py`, add the import:

```python
from app.extensions import limiter
```

and decorate `login` (below the `@auth_bp.route` line):

```python
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def login():
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_security.py -v`
Expected: all pass

- [ ] **Step 9: Verify no existing login test regressed**

Run: `python -m pytest tests/test_auth.py tests/test_home.py tests/test_shell.py tests/test_bullpen_landing.py -q`
Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add requirements.txt config.py app/extensions.py app/__init__.py app/auth/routes.py tests/test_security.py
git commit -m "feat(security): rate-limit login attempts (disabled under test)"
```

---

### Task 5: POST-only logout

**Files:**
- Modify: `app/auth/routes.py:76-81`
- Modify: `app/templates/base.html:121`
- Modify: `app/dashboards/shell.py:120`
- Modify: `tests/test_auth.py:192,240,266`
- Test: `tests/test_security.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `/logout` accepts POST only.

**This task is separable and lowest value.** Logout CSRF is an annoyance, not a breach, and this is the only Part A change with visual-regression risk. If the header buttons look wrong, drop this task; nothing else depends on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_security.py`:

```python
def test_logout_rejects_get(monkeypatch):
    """A GET logout lets any third-party page sign your users out with an
    <img src="https://paw.../logout"> tag."""
    resp = _client(monkeypatch).get("/logout")
    assert resp.status_code == 405
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_security.py -k logout -v`
Expected: FAIL — got 302, expected 405

- [ ] **Step 3: Make the route POST-only**

In `app/auth/routes.py`:

```python
@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
```

- [ ] **Step 4: Update the Jinja link to a form**

Replace `app/templates/base.html:121`:

```html
        <form method="post" action="{{ url_for('auth.logout') }}" class="logout-form">
          <button type="submit" class="logout-btn">Log out</button>
        </form></span>
```

Add to the stylesheet block in `base.html` so the button keeps the link's look:

```css
.logout-form { display: inline; }
.logout-btn {
  background: none; border: none; padding: 0; cursor: pointer;
  font: inherit; color: inherit; text-decoration: underline;
}
```

- [ ] **Step 5: Update the Dash header link to a form**

Replace `app/dashboards/shell.py:120`. The existing `html.A("Log out", href="/logout", ...)` carries a `style=` dict — copy that same dict onto the button so the crimson header is unchanged:

```python
            html.Form(
                [html.Button("Log out", type="submit", style={
                    "background": "none", "border": "none", "padding": "0",
                    "cursor": "pointer", "font": "inherit", "color": "inherit",
                    "textDecoration": "underline",
                })],
                action="/logout", method="POST",
                style={"display": "inline"},
            ),
```

- [ ] **Step 6: Update the three existing GET-logout tests**

In `tests/test_auth.py`, change line 192 to:

```python
    resp = client.post("/logout", follow_redirects=True)
```

and lines 240 and 266 to:

```python
    client.post("/logout")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_security.py tests/test_auth.py -v`
Expected: all pass

- [ ] **Step 8: Confirm the Dash header assertion still holds**

`tests/test_hitting_dash.py:408` asserts `"/logout" in tree` — a form `action` still satisfies it.

Run: `python -m pytest tests/test_hitting_dash.py -q`
Expected: all pass

- [ ] **Step 9: Visually verify the header**

Run: `PYTHONIOENCODING=utf-8 python run.py`, open http://127.0.0.1:8050, log in, and check that "Log out" looks unchanged on both the home page and a dashboard. If it does not, revert this task only.

- [ ] **Step 10: Commit**

```bash
git add app/auth/routes.py app/templates/base.html app/dashboards/shell.py tests/test_auth.py tests/test_security.py
git commit -m "feat(security): make logout POST-only to close logout CSRF"
```

---

### Task 6: Full-suite verification gate

**Files:** none modified.

This task exists because Part A touches app-wide config, and the spec's success criterion is that all 874 tests stay green.

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q --ignore=tests/test_precalc.py`
Expected: 874+ passed, 0 failed. Takes ~16 minutes.

- [ ] **Step 2: If anything fails, fix it before proceeding to Part B**

Do not proceed with failures. Record the failure and its cause.

- [ ] **Step 3: Verify the app still boots and serves**

Run: `PYTHONIOENCODING=utf-8 python run.py`, then confirm http://127.0.0.1:8050/login returns the login page and a coach login reaches the home page.

- [ ] **Step 4: Confirm merging is a no-op in production**

Run: `python -c "import config; print('is_production:', config.is_production())"`
Expected: `is_production: False` — proving `PAW_ENV` gating leaves the live site untouched.

---

### Task 7: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `ruff.toml`

**Interfaces:**
- Produces: a required status check named `ci` for Task 9's ruleset.

- [ ] **Step 1: Create `ruff.toml`**

Lenient on purpose — this gates interns, and a wall of style errors on a first PR is discouraging.

```toml
line-length = 100
target-version = "py312"

[lint]
# Start with real bugs only: pyflakes (F) + a few bugbear checks.
# Style nits are deliberately excluded so a first-time contributor's PR is
# not buried in red.
select = ["F", "E9", "B"]
ignore = ["B008"]

[lint.per-file-ignores]
"tests/*" = ["F811", "F401"]
```

- [ ] **Step 2: Create `.github/workflows/ci.yml`**

```yaml
name: ci

# Runs on every PR into main, plus pushes to main so the badge stays honest.
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt
      - run: pip install ruff

      # Catches real bugs (undefined names, unused imports) without drowning a
      # first-time contributor in style nits.
      - run: ruff check .

      # Every module must at least import cleanly.
      - run: python -m compileall -q app config.py run.py wsgi.py

      # DB-free tests only. This repo is PUBLIC: putting MYSQL_* secrets in a
      # PR workflow would let any pull request exfiltrate the database
      # credentials. Dummy values satisfy config.py's _require() at import;
      # no connection is ever opened. Splitting the full suite into
      # offline/live is tracked separately -- see the spec's "Out of scope".
      - run: python -m pytest tests/test_security.py -q
        env:
          MYSQL_USER: ci
          MYSQL_PASSWORD: ci
          MYSQL_HOST: localhost
          MYSQL_DB: ci
          SECRET_KEY: ci-not-a-real-key
          PYTHONIOENCODING: utf-8
```

- [ ] **Step 3: Verify the workflow's commands pass locally**

Run:
```bash
pip install ruff && ruff check .
python -m compileall -q app config.py run.py wsgi.py
MYSQL_USER=ci MYSQL_PASSWORD=ci MYSQL_HOST=localhost MYSQL_DB=ci SECRET_KEY=ci python -m pytest tests/test_security.py -q
```
Expected: all three succeed. If `ruff check .` reports pre-existing errors in untouched files, add those rules to `ignore` rather than reformatting the codebase — that is out of scope.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml ruff.toml
git commit -m "ci: lint, compile, and DB-free tests on every PR"
```

---

### Task 8: Contributor docs for interns

**Files:**
- Create: `.github/CODEOWNERS`
- Create: `.github/pull_request_template.md`
- Create: `CONTRIBUTING.md`
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Create `.github/CODEOWNERS`**

```
# Every pull request automatically requests Brad's review.
*       @bradhaskell
```

- [ ] **Step 2: Create `.github/pull_request_template.md`**

Deliberately three short prompts. A long checklist gets ignored.

```markdown
## What does this change?



## How did you test it?



## Screenshot (if you changed anything visual)



---
- [ ] I did not commit `.env` or any password
- [ ] I ran `python -m pytest -q` and it passed
```

- [ ] **Step 3: Create `CONTRIBUTING.md`**

```markdown
# Contributing to PAW

Welcome! This guide is everything you need. If you get stuck, ask Brad —
that is faster than guessing.

## The one rule

**Never push to `main`.** All work goes through a pull request. `main` is what
the team actually uses, so a bug there breaks the site for real coaches and
players.

## First-time setup

```bash
git clone https://github.com/LMU-Baseball/PAW.git
cd PAW
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

Ask Brad for the `.env` file. **Never commit it** — it holds the database
password. It is already in `.gitignore`, so git will ignore it automatically.

## Making a change

```bash
git checkout main
git pull                                  # start from the latest code
git checkout -b your-name/what-you-are-doing
```

Branch names look like `maria/fix-velo-chart` or `jordan/add-catcher-tab`.

Make your edits, then:

```bash
python -m pytest -q                       # make sure nothing broke
git add .
git commit -m "fix: velo chart showed the wrong season"
git push -u origin your-name/what-you-are-doing
```

GitHub prints a link. Open it, fill in the three questions, and click
**Create pull request**.

## What happens next

1. Automated checks run. If they go red, click "Details" to see why, push a
   fix to the same branch, and they re-run automatically.
2. Brad reviews it. He may leave comments asking for changes — that is normal
   and happens to everyone.
3. Once approved, it gets merged. Your branch is deleted automatically.

## Running the app

```bash
python run.py
```

Open **http://127.0.0.1:8050** (use `127.0.0.1`, not `localhost`).

## Things that will get a PR sent back

- Committing `.env`, a password, or a database credential
- Pushing directly to `main`
- A PR with no description
- Tests failing

## Getting unstuck

- Tests failing and you did not touch that file? Run `git pull` — you may be
  behind `main`.
- Something is broken and you want to start over on your branch:
  `git checkout main && git pull && git checkout -b your-name/try-again`
- Still stuck? Ask. Genuinely.
```

- [ ] **Step 4: Create `.github/dependabot.yml`**

```yaml
version: 2
updates:
  # Monthly, not weekly: this is a small team and a flood of PRs gets ignored.
  - package-ecosystem: pip
    directory: "/"
    schedule:
      interval: monthly
    open-pull-requests-limit: 5
    labels: ["dependencies"]

  - package-ecosystem: github-actions
    directory: "/"
    schedule:
      interval: monthly
    open-pull-requests-limit: 3
    labels: ["dependencies"]
```

- [ ] **Step 5: Commit**

```bash
git add .github/CODEOWNERS .github/pull_request_template.md .github/dependabot.yml CONTRIBUTING.md
git commit -m "docs: add contributor guide, PR template, CODEOWNERS, and Dependabot"
```

---

### Task 9: Branch ruleset and repo settings

**Files:** none — this is GitHub configuration applied with `gh`.

**Prerequisite:** Tasks 7 and 8 must be merged to `main` first, so the `ci`
status check exists and can be required.

- [ ] **Step 1: Enable secret scanning and push protection**

```bash
gh api -X PATCH repos/LMU-Baseball/PAW \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
```

Push protection is the important half: it blocks a commit containing a
credential *before* it reaches GitHub.

- [ ] **Step 2: Set merge behavior**

```bash
gh api -X PATCH repos/LMU-Baseball/PAW \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true
```

Squash-only keeps history clean without asking interns to learn rebase.

- [ ] **Step 3: Create the `main` ruleset with an admin bypass**

Write `scratchpad/ruleset.json`:

```json
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] }
  },
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["squash"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [{ "context": "ci" }]
      }
    }
  ]
}
```

`actor_id: 5` is the built-in **repository admin** role — this is what
preserves direct pushes to `main` for the repo owner. Interns with `write`
have no bypass.

Apply it:

```bash
gh api -X POST repos/LMU-Baseball/PAW/rulesets --input scratchpad/ruleset.json
```

- [ ] **Step 2 verification: confirm the ruleset is live**

```bash
gh api repos/LMU-Baseball/PAW/rulesets --jq '.[] | "\(.name) \(.enforcement)"'
```
Expected: `main-protection active`

- [ ] **Step 4: Verify the owner bypass actually works**

From a clean `main`, make a trivial commit (e.g. a typo fix in `README.md`) and
push directly:

```bash
git checkout main && git pull
git commit --allow-empty -m "chore: verify admin bypass"
git push origin main
```
Expected: the push succeeds. If it is rejected, the bypass actor is
misconfigured — fix it before adding any interns, or the owner is locked out
of their own hotfix path.

- [ ] **Step 5: Record the org settings the owner must apply manually**

These need `admin:org` scope, which the current token lacks. Print them for the
user rather than attempting them:

- Settings → Authentication security → **Require two-factor authentication**
- Settings → Member privileges → **Repository deletion**: disable for members
- Settings → Member privileges → **Repository visibility change**: admins only

Today an intern added as an org member could delete a repository.

---

### Task 10: Lightsail migration steps + memory

**Files:**
- Modify: `docs/DEPLOY.md` (§4 secrets, §8 HTTPS, and a new security checklist)
- Modify: `memory/MEMORY.md`

- [ ] **Step 1: Add the two new env vars to `docs/DEPLOY.md` §4**

In the `.env` block around line 133:

```bash
# --- Flask session signing: MUST be a strong random value in production ---
SECRET_KEY=<paste the output of the openssl command below>

# --- Activates production security: Secure cookies, HSTS, and the
#     SECRET_KEY boot guard. Leave this UNSET until HTTPS is working
#     (see section 8) -- a Secure cookie sent over plain HTTP is dropped
#     by the browser, and login will appear to do nothing.
PAW_ENV=production
```

- [ ] **Step 2: Add the HTTP warning to `docs/DEPLOY.md` §8**

Replace the existing "No domain yet?" blockquote near line 243:

```markdown
> **No domain yet?** You can launch on `http://LIGHTSAIL_IP` for internal
> testing, but you MUST leave `PAW_ENV` unset until the certificate is
> installed. With `PAW_ENV=production` on a plain-HTTP host, the browser
> silently discards the `Secure` session cookie and **login appears to do
> nothing — it just bounces back to the login page.** Get the cert, then set
> `PAW_ENV=production` and restart:
>
> ```bash
> sudo systemctl restart paw
> ```
>
> And **do HTTPS before sharing with players** either way — login passwords
> over plain HTTP are exposed.
```

- [ ] **Step 3: Add a security checklist section to `docs/DEPLOY.md`**

Insert before "## 9. Verify":

```markdown
## 8b. Security checklist (post-certificate)

Everything in `app/security.py` and `config.py` moves from Render unchanged.
What is host-specific:

- [ ] `SECRET_KEY` set to a strong random value (`openssl rand -hex 32`) —
      NOT the same value Render used, and never the dev default.
- [ ] `PAW_ENV=production` set, and only after the certificate is installed.
- [ ] Verify it took effect:
      `curl -sI https://paw.lmulions.com/login | grep -i strict-transport`
      should print a `Strict-Transport-Security` header. If it is missing,
      `PAW_ENV` is not set or the service was not restarted.
- [ ] Verify the session cookie:
      `curl -sI https://paw.lmulions.com/login | grep -i set-cookie`
      should show `Secure`, `HttpOnly`, and `SameSite=Lax`.
- [ ] nginx already forwards `X-Forwarded-Proto` (section 7). `ProxyFix`
      depends on it — without it, `Secure` cookies never activate.
- [ ] **Rate limiting matters more here than on Render.** A bare Lightsail box
      has none of Render's edge DDoS protection. The in-memory limiter is
      per-worker, so with `WEB_CONCURRENCY=3` the real limit is ~3x the
      configured 10/hour. Consider `WEB_CONCURRENCY=1` if brute force is a
      concern, or add Redis.
- [ ] **Lock down RDS** — `docs/deploy-aws.md:158`: restrict inbound `3306` to
      this server's security group and remove any `0.0.0.0/0` rule. NOTE: this
      requires console access to the AWS account that OWNS the RDS instance.
      Database credentials alone are not sufficient.
- [ ] Rotate the RDS master password (standing item — it is plaintext in the
      legacy `src/` R files).
- [ ] The GitHub Actions pipeline cron connects to RDS from GitHub-hosted
      runners with rotating IPs. If you lock the RDS firewall down, that cron
      **will break** — move it onto this Lightsail box (systemd timer) at the
      same time.
```

- [ ] **Step 4: Update `memory/MEMORY.md`**

Prepend a dated entry to the top of the file. **Read the incident note at
`memory/MEMORY.md:17` first** — a previous session truncated this file to zero
bytes by opening it with `io.open(p, "w")`. Read the existing content, prepend,
and write atomically.

Record: the security branch and what shipped; the `PAW_ENV=production`
two-phase rollout and that it is the rollback switch; that `SECRET_KEY` and
`PAW_ENV` must be set in Render to activate; the Lightsail checklist location
(`docs/DEPLOY.md` §8b); the RDS-is-publicly-accessible finding
(resolves to `3.130.246.255`, GitHub Actions connects from rotating IPs, so
`3306` is almost certainly open to `0.0.0.0/0`); that DB credentials do not
grant AWS-account permissions; and the org settings the user still owes.

- [ ] **Step 5: Commit**

```bash
git add docs/DEPLOY.md
git commit -m "docs(deploy): add the Lightsail security checklist and PAW_ENV warning"
```

(`memory/` is gitignored — it is not committed.)

---

## Self-Review

**Spec coverage:**

| Spec item | Task |
|---|---|
| A1 `SECRET_KEY` guard | 1 |
| A2 `ProxyFix` | 2 |
| A3 session cookies | 2 |
| A4 security headers | 3 |
| A5 rate limiting | 4 |
| A6 Report-Only CSP | 3 |
| A7 POST logout | 5 |
| No global CSRF (documented) | 3 (module docstring) |
| AWS migration note | 10 |
| Full-suite green | 6 |
| B1 CI | 7 |
| B2 ruleset + admin bypass | 9 |
| B3 CODEOWNERS | 8 |
| B4 PR template + CONTRIBUTING | 8 |
| B5 Dependabot | 8 |
| B6 repo settings | 9 |
| B7 org settings (owner action) | 9 step 5 |
| B8 intern access model | 8 (CONTRIBUTING) |

No gaps.

**Placeholder scan:** none.

**Type consistency:** `is_production()` is defined in Task 1 and consumed by
Tasks 2 and 3 under the same name. `limiter` is defined in Task 4
(`app/extensions.py`) and consumed in the same task. `register_security_headers(server)`
is defined and registered in Task 3.
