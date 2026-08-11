"""Dash dashboards mounted on the Flask server, protected by Flask-Login.

Hitting (game + HitTrax practice), pitching, and catching Dash modules are
registered here. All /dash/* routes require login.
"""
from flask import redirect, request, url_for
from flask_login import current_user


def register_dashboards(server):
    _protect_dash_routes(server)
    from app.dashboards.hitting import build_hitting_dash
    build_hitting_dash(server)
    from app.dashboards.pitching import build_pitching_dash
    build_pitching_dash(server)
    from app.dashboards.catching import build_catching_dash
    build_catching_dash(server)
    from app.dashboards.hitting_practice import build_hitting_practice_dash
    build_hitting_practice_dash(server)
    from app.dashboards.bullpen.index import build_bullpen_dash
    build_bullpen_dash(server)
    from app.dashboards.velo_board.index import build_velo_board_dash
    build_velo_board_dash(server)
    from app.dashboards.cauldron.index import build_cauldron_dash
    build_cauldron_dash(server)


def _protect_dash_routes(server):
    """Require a logged-in user for anything under /dash/."""
    @server.before_request
    def _require_login_for_dash():
        if request.path.startswith("/dash/") and not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
