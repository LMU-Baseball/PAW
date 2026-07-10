"""Report download routes."""
from flask import Blueprint, Response, abort
from flask_login import current_user, login_required

from app.auth.access import can_view_pitcher_report
from app.reports.pitcher_postgame import ReportDataError, build_pitcher_postgame

report_bp = Blueprint("reports", __name__, url_prefix="/reports")


@report_bp.route("/pitcher/<int:game_id>/<int:pitcher_id>.pdf")
@login_required
def pitcher_pdf(game_id: int, pitcher_id: int):
    if not can_view_pitcher_report(current_user, pitcher_id):
        abort(403)
    try:
        pdf = build_pitcher_postgame(game_id, pitcher_id)
    except ReportDataError:
        abort(404)
    return Response(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="pitcher_{pitcher_id}_game_{game_id}.pdf"'},
    )
