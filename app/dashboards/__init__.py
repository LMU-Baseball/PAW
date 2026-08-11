"""Dash dashboards mounted on the Flask server, protected by Flask-Login.

Hitting (game + HitTrax practice), pitching, and catching Dash modules are
registered here. All /dash/* routes require login.
"""
import logging

from flask import redirect, request, url_for
from flask_login import current_user

log = logging.getLogger(__name__)


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

    # Best-effort: seed cauldron_scoring so a fresh deploy's board isn't inert
    # (empty scoring config -> no grid columns, score_day is a no-op). The
    # seed is idempotent (ON DUPLICATE KEY UPDATE metric=metric), so calling
    # it on every boot never clobbers a coach's tuned thresholds/points -- it
    # only fills in metrics that are missing. Wrapped so a DB hiccup at boot
    # (e.g. RDS briefly unreachable) never crashes app startup, mirroring
    # warmup.py's swallow-and-log-lazily posture.
    try:
        from app.data import cauldron
        cauldron.ensure_tables()
        cauldron.seed_default_scoring()
    except Exception:
        log.warning("cauldron scoring seed failed at startup", exc_info=True)


def _protect_dash_routes(server):
    """Require a logged-in user for anything under /dash/."""
    @server.before_request
    def _require_login_for_dash():
        if request.path.startswith("/dash/") and not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
