"""Report download routes."""
from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required

from app.auth.access import can_view_pitcher_report
from app.data import pitching as P
from app.reports.pitcher_postgame import ReportDataError, build_pitcher_postgame

report_bp = Blueprint("reports", __name__, url_prefix="/reports")


@report_bp.route("/pitching")
@login_required
def pitching_landing():
    """Pick a recent game, then download any of that game's pitcher reports."""
    games = P.recent_games(limit=25)
    game_id = request.args.get("game_id", type=int)

    selected = None
    pitchers = None
    if game_id is not None:
        match = games[games["game_id"] == game_id]
        if not match.empty:
            selected = match.iloc[0].to_dict()
        pitchers = P.pitchers_for_game(game_id).to_dict("records")

    return render_template(
        "reports/pitching_landing.html",
        games=games.to_dict("records"),
        game_id=game_id,
        selected_game=selected,
        pitchers=pitchers,
    )


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
