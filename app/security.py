"""Response security headers.

DELIBERATELY NOT HERE: a global Flask-WTF `CSRFProtect`. Dash's callback
endpoint (`/dash/<name>/_dash-update-component`) is a POST that sends no CSRF
token, so enabling CSRFProtect app-wide breaks every dashboard. The protection
that actually closes that hole is `SESSION_COOKIE_SAMESITE = "Lax"` in
config.py, which stops a third-party site from sending the session cookie on a
cross-site POST at all. Do not "fix" this by adding CSRFProtect.

Two caveats on that reasoning, so it is not over-trusted:

- `SameSite` is scoped to the browser's notion of a "site" -- the registrable
  domain (e.g. `lmulions.com`), not the origin (`paw.lmulions.com`). A cookie
  marked `SameSite=Lax` is still attached to a POST from ANY host under the
  same registrable domain. On `paw.lmulions.com`, that means any
  attacker-controlled subdomain or app under `lmulions.com` counts as
  same-site and can POST to the Dash callback endpoint with the victim's
  session cookie attached -- `SameSite` alone does not defend against that.
- It is a browser-enforced mitigation, not a server-side control: it relies on
  every visitor's browser correctly implementing and applying the cookie
  attribute, not on this server rejecting anything itself.

If a server-side backstop is ever wanted, `before_request` could reject POSTs
whose `Origin` / `Sec-Fetch-Site` header indicates a cross-site request (Dash
callbacks are same-origin `fetch()` calls, which always send `Origin`, so this
would not break them). Not implemented -- recorded here only as the available
option if the SameSite gap above is ever judged worth closing.
"""
import logging

from flask import flash, render_template, request

import config

logger = logging.getLogger(__name__)

# Report-Only, never enforced. Dash injects inline <script> tags via
# dash_renderer and Plotly writes inline styles, so an enforced policy blanks
# all seven dashboards. This observes what a future enforced policy would
# block; tighten only after reviewing real reports.
#
# NOTE: there is no `report-uri`/`report-to` directive, so violation reports
# only ever reach each individual viewer's own browser devtools console --
# nobody is collecting them centrally. Right now "observing violations" means
# manually opening devtools on each of the seven dashboards and looking. A
# `report-uri` endpoint (a route that accepts and logs the browser's POSTed
# violation reports) would be needed before the promised "tighten after
# reviewing real reports" pass has any actual data to review.
#
# media-src is deliberately as permissive as img-src: pitch video
# (app/dashboards/video/component.py's html.Video/html.Source) is served from
# a cross-origin public S3 bucket (see app/data/video.py), not from this app's
# own origin. A 'self'-only media policy would fall back to default-src and
# report -- and, if this is ever enforced, break -- every single video load.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "media-src 'self' https:; "
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
        if config.is_production():
            # Only meaningful over HTTPS, and actively harmful on a plain-HTTP
            # host: a browser that caches HSTS will refuse http:// afterwards.
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


def register_rate_limit_handler(server) -> None:
    """A throttled `/login` POST otherwise falls through to Werkzeug's bare,
    unstyled 429 page -- no branding, no `Retry-After`, and nothing in the
    logs. Re-render the login form instead, with a flashed message matching
    the app's existing flash style, and log the event so an operator can
    actually see brute-force attempts happening."""
    @server.errorhandler(429)
    def _rate_limited(_error):
        # Local import: app.auth.routes doesn't import app.security, so this
        # is not a real cycle -- but importing at module load time would still
        # run auth/routes.py before app.security finishes defining, since
        # app/__init__.py wires them up in that order.
        from app.auth.routes import LoginForm

        logger.warning("Rate limit exceeded for %s on %s", request.remote_addr, request.path)
        flash("Too many sign-in attempts. Please wait a few minutes and try again.", "error")
        return render_template("auth/login.html", form=LoginForm()), 429
