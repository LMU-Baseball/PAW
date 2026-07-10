"""Dash dashboards mounted on the Flask server, protected by Flask-Login.

For now this is a minimal placeholder that proves the Flask + Dash + auth
integration. The real hitting UI (strike-zone scatter, spray chart, radial,
heatmap, tables) will be built here on top of app/data/hitting.py once the
www/ asset images are available.
"""
from flask import redirect, request, url_for
from flask_login import current_user


def register_dashboards(server):
    _protect_dash_routes(server)
    from app.dashboards.hitting import build_hitting_dash
    build_hitting_dash(server)


def _protect_dash_routes(server):
    """Require a logged-in user for anything under /dash/."""
    @server.before_request
    def _require_login_for_dash():
        if request.path.startswith("/dash/") and not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
