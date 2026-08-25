"""Response security headers.

DELIBERATELY NOT HERE: a global Flask-WTF `CSRFProtect`. Dash's callback
endpoint (`/dash/<name>/_dash-update-component`) is a POST that sends no CSRF
token, so enabling CSRFProtect app-wide breaks every dashboard. The protection
that actually closes that hole is `SESSION_COOKIE_SAMESITE = "Lax"` in
config.py, which stops a third-party site from sending the session cookie on a
cross-site POST at all. Do not "fix" this by adding CSRFProtect.
"""
import config

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
        if config.is_production():
            # Only meaningful over HTTPS, and actively harmful on a plain-HTTP
            # host: a browser that caches HSTS will refuse http:// afterwards.
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp
