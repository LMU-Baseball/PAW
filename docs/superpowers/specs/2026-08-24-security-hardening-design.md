# Security Hardening + Repo Governance — Design

**Date:** 2026-08-24
**Branch:** `feat/2026-08-24-security-hardening`
**Status:** approved by user, ready for implementation plan

---

## 1. Context

PAW is live and publicly reachable on Render with two **shared** logins (one
`coach`, one `player`) used by the whole LMU Baseball team — roughly 30–50
students and staff. A small group of young interns will start contributing
code. The user asked for two things: standard security protocols on the site,
and a GitHub setup that lets interns develop without breaking the app.

Two constraints shape every decision below:

- **Do not add friction for users.** Players and coaches must reach PAW as
  fast as they do today.
- **Do not add friction for the owner.** The user pushes directly to `main`
  and wants to keep doing so. Interns must not be able to.

## 2. Audit findings

A full read of the codebase against the seven concerns the user raised.

### Already safe — no work needed

| Concern | Finding |
|---|---|
| Session survives a copy-pasted link | Not possible. Flask-Login stores the session in a signed cookie, never in the URL. |
| SQL injection via dynamic conditions | Clean. Every module in `app/data/` uses SQLAlchemy `text()` with bound `:params`. The f-strings interpolate only internal constants — table names, column lists, `IN (…)` placeholder counts, and dates computed in code. No request value reaches SQL as a string. |
| Server fetches arbitrary URLs (SSRF) | Not present. The only outbound fetch is `scripts/scrape_roster_media.py:31`, an offline script with a hardcoded `ROSTER_URL`. No route accepts a URL. |
| Stored XSS | Very low. Zero `dangerously_allow_html`; Dash/React escapes text children (coach notes render via `html.Div(text)`, `notes_ui.py:32`). Jinja autoescape on; the only `\|safe` is our own trusted CSS blob. |
| Wide-open CORS | No CORS config exists, which is the secure default. |
| Secrets in the repo | Clean. `git grep` and `git log --all -S` for the RDS password return zero hits in tracked files and in history. `.env`, `src/`, `instance/*` gitignored. `pipeline-cron.yml` uses `secrets.*` with `permissions: contents: read`. |
| Backend over-fetching | By design, not a leak. `User.can_view_player` (`models.py:53`) returns `True` for everyone — the team-transparent view model is deliberate. Writes are gated separately and re-checked server-side in every write callback. |

### Gaps to close

1. `SECRET_KEY` falls back to the hardcoded `"dev-only-change-me"`
   (`config.py:52`). If unset in production, anyone reading this public repo
   can forge a session cookie for any account. **Most serious finding.**
2. No session-cookie hardening: no `SECURE`, `HTTPONLY`, `SAMESITE`, or
   lifetime anywhere.
3. No `ProxyFix`. Render terminates TLS at its edge and forwards plain HTTP,
   so Flask believes every request is insecure.
4. No rate limiting on `/login`. Brute force is unthrottled, which matters
   more than usual because the password is shared.
5. No security headers (HSTS, nosniff, frame options, referrer policy).
6. Dash callback POSTs have no CSRF protection.
7. `/logout` is a GET (`auth/routes.py:76`), so any page can force a logout.
8. Repo is **public** with **no branch protection and no rulesets**. Only
   collaborators are `bradhaskell` (admin) and `beckettyee` (read).
9. No CI. An intern PR gets zero automated checks.
10. Org defaults are risky: 2FA not required, `members_can_delete_repositories:
    true`, `members_can_change_repo_visibility: true`, secret-scanning push
    protection off.

## 3. Decisions

| Question | Decision |
|---|---|
| Account model | Keep the two shared logins this season; harden around them. Individual accounts later. Do not force strong random passwords. |
| Repo visibility | Stay **public**. The org is on the free plan, where rulesets are free on public repos but unavailable on private ones. Privacy would cost the exact PR enforcement the user asked for. |
| Owner's workflow | Keep direct pushes to `main` via a ruleset **bypass actor** for repository admins. |
| Intern access | **Write** access, branch → PR → CI + review → squash merge. |
| Session lifetime | **30 days, sliding.** Refreshed on every request, so regular users are never logged out. |
| Intern process | Kept deliberately simple — no rebasing, no linear-history requirement, a short copy-paste guide. |

## 4. Part A — Application hardening

All of Part A is application code and config, so it moves unchanged to AWS.

### A1. Require a real `SECRET_KEY` in production

`config.py` resolves the key as:

1. `SECRET_KEY` env var if set — use it.
2. Else, if production — raise `RuntimeError` at boot.
3. Else — the dev default, with a logged warning.

**Production is signalled by `PAW_ENV=production`**, an explicit host-agnostic
variable, with Render's auto-set `RENDER` as a fallback so the current
deployment stays correct if the variable is forgotten. Keying off `RENDER`
alone would silently disable every production behavior after the AWS move.

**Deployment order matters:** `SECRET_KEY` must be set in Render's environment
*before* this merges, or the next deploy fails to boot.

### A2. `ProxyFix`

Wrap `server.wsgi_app` in `ProxyFix(x_for=1, x_proto=1, x_host=1)` in
`create_app`. Without it Flask sees plain HTTP behind both Render's edge and
the nginx config in `docs/DEPLOY.md:213`, which silently disables secure
cookies and gives the rate limiter the proxy's IP instead of the client's.
**Must land before A3 and A5 or neither works.**

### A3. Session cookie hardening

New config keys:

- `SESSION_COOKIE_SECURE = True` in production only
- `SESSION_COOKIE_HTTPONLY = True`
- `SESSION_COOKIE_SAMESITE = "Lax"`
- `PERMANENT_SESSION_LIFETIME = 30 days`, with sessions marked permanent and
  `SESSION_REFRESH_EACH_REQUEST = True` for the sliding window
- The same treatment for the remember cookie

`SameSite=Lax` is also what closes the Dash callback CSRF hole — see
"Deliberately NOT done: global CSRF" below.

### A4. Security headers

One `after_request` hook in a new `app/security.py`:

- `Strict-Transport-Security` — production only
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- A minimal `Permissions-Policy`

### A5. Rate-limit `/login`

Add `Flask-Limiter`, applied to the login POST only.

**Known limitation, deliberately accepted:** the default in-memory storage is
per-process, and `gunicorn.conf.py` runs 3 workers, so the effective limit is
about 3× the configured value. That still removes ~99% of brute-force
throughput. An exact limit needs Redis, which costs money. This matters *more*
after the AWS move, since a bare VM has none of Render's edge protection.

### A6. CSP as Report-Only first

Dash injects inline scripts and Plotly writes inline styles, so an enforced
`Content-Security-Policy` breaks all seven dashboards. Ship
`Content-Security-Policy-Report-Only` first, observe what it flags, then
tighten in a follow-up. Shipping an enforced policy blind would take the site
down.

### A7. `/logout` becomes POST-only

Currently a GET, so any page can log a user out with an `<img>` tag. Becomes a
small POST form.

### Deliberately NOT done: global CSRF

Wrapping the app in Flask-WTF's `CSRFProtect` would break every Dash callback,
because Dash does not send CSRF tokens. `SameSite=Lax` from A3 is what actually
closes the cross-site POST hole. This must be documented in `app/security.py`
so it is not "fixed" later.

### AWS migration note

`SESSION_COOKIE_SECURE = True` means a browser will refuse to store the session
cookie over plain HTTP. `docs/DEPLOY.md:243` currently suggests launching on
`http://LIGHTSAIL_IP` before obtaining a certificate — with this change, login
would appear to do nothing and bounce back to the login page. On AWS, either
obtain the certificate first or leave `PAW_ENV` unset until it is in place.
This warning goes into `DEPLOY.md`.

### Testing

Every item above gets a regression test in a new `tests/test_security.py`.
That file must be **DB-free**, so it doubles as the first CI-safe test file.

## 5. Part B — GitHub governance

### B1. CI workflow

`.github/workflows/ci.yml`, running on every PR.

**Constraint:** most of the 75 test files touch the live RDS, and on a public
repo, database secrets must never be exposed to PR workflows — a malicious PR
could exfiltrate them. CI v1 therefore runs `ruff` lint, `compileall`, and the
DB-free test subset (starting with `tests/test_security.py`). Running the full
suite in CI requires an offline/live test split, which is separate work and is
explicitly out of scope here.

### B2. Ruleset on `main`

Require a pull request, ≥1 approving review, dismissal of stale approvals on
new pushes, passing CI, and resolved conversations. Block force-pushes and
branch deletion.

**`Repository admin` is configured as a bypass actor**, so the user keeps
direct pushes. Interns with `write` cannot bypass.

**Not required — deliberately:** linear history and signed commits. Both force
interns to learn rebasing and commit signing for no benefit here. Squash-merge
keeps history clean without asking anything of them.

### B3. `CODEOWNERS`

`* @bradhaskell`, so every PR automatically requests the user's review.

### B4. PR template + `CONTRIBUTING.md`

Written for beginners: exact copy-paste commands, branch naming, "never push to
`main`", how to run tests, and never commit `.env`. Short — a wall of
checkboxes would be ignored.

### B5. Dependabot

`.github/dependabot.yml` for `pip` and `github-actions`.

### B6. Repo settings

Via `gh`: enable secret scanning and push protection, allow squash-merge only,
auto-delete merged branches.

### B7. Org settings — owner action required

Cannot be set with the current token scopes. The user must, in the GitHub UI:

- Require 2FA for all org members
- Set `members_can_delete_repositories` to false
- Restrict who can change repository visibility

Today an intern added as an org member could delete a repository.

### B8. Intern access model

Outside collaborators with **`write`**, never admin. Branch → PR → CI + review
→ squash merge.

## 6. Out of scope

- **RDS credential rotation.** The password is plaintext in the local `src/` R
  files and possibly in the original R repo. Verified *not* in PAW's git
  history. This is an AWS console task for the user (standing item, memory §4).
- **Individual user accounts.** Deferred by decision; revisit before next
  season.
- **Enforced CSP.** Follow-up after Report-Only data comes in.
- **Offline/live test split** to run the full suite in CI.
- **Redis-backed exact rate limiting.**

## 7. Rollout order

1. User sets `SECRET_KEY` and `PAW_ENV=production` in Render. *(blocks A1)*
2. Part A implemented, tested, PR'd.
3. Part B: CI workflow merged first, so the ruleset has a status check to require.
4. Ruleset, CODEOWNERS, templates, Dependabot, repo settings.
5. User applies the org settings in B7.
6. Interns added with `write`.
