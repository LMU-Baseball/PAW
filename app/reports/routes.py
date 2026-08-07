"""Report download routes."""
import io
import re
import zipfile

from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required

from app.auth.access import can_view_pitcher_report, can_view_bullpen
from app.data import pitching_caps
from app.data import bullpen as BULL
from app.reports.pitcher_postgame import ReportDataError, build_pitcher_postgame
from app.reports.bullpen_report import build_bullpen_report

report_bp = Blueprint("reports", __name__, url_prefix="/reports")


def _safe(text: str) -> str:
    """Filesystem-safe slug for a filename fragment."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(text)).strip("_") or "report"


@report_bp.route("/pitching")
@login_required
def pitching_landing():
    """Pick a recent game, then download any of that game's pitcher reports."""
    games = pitching_caps.recent_games(limit=25)
    game_id = request.args.get("game_id", type=int)
    sort = request.args.get("sort", "pitch")
    if sort not in ("pitch", "alpha"):
        sort = "pitch"

    selected = None
    pitchers = None
    if game_id is not None:
        match = games[games["game_id"] == game_id]
        if not match.empty:
            selected = match.iloc[0].to_dict()
        pitchers = pitching_caps.pitchers_for_game(game_id, sort=sort).to_dict("records")

    return render_template(
        "reports/pitching_landing.html",
        games=games.to_dict("records"),
        game_id=game_id,
        selected_game=selected,
        pitchers=pitchers,
        sort=sort,
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
                 f'attachment; filename="pitcher_{pitcher_id}_game_{game_id}.pdf"'},
    )


@report_bp.route("/pitching/<int:game_id>/all.zip")
@login_required
def pitching_all_zip(game_id: int):
    """Download every viewable LMU pitcher report for a game as one ZIP.

    Uses the same LMU-only picker list and the same per-pitcher access gate as
    the individual downloads, so a coach gets the whole game and a player gets
    only their own outing. Reports build one at a time (cached after the first
    build), so the first "Download All" for a game can take several seconds.
    """
    sort = request.args.get("sort", "pitch")
    if sort not in ("pitch", "alpha"):
        sort = "pitch"

    pitchers = pitching_caps.pitchers_for_game(game_id, sort=sort).to_dict("records")
    viewable = [p for p in pitchers
                if can_view_pitcher_report(current_user, p["player_id"])]
    if not viewable:
        abort(404)

    buf = io.BytesIO()
    used_names: set[str] = set()
    written = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in viewable:
            try:
                pdf = build_pitcher_postgame(game_id, p["player_id"])
            except ReportDataError:
                continue  # skip non-LMU / no-data pitchers rather than failing all
            name = f"{_safe(p['display_name'])}.pdf"
            if name in used_names:  # dedupe identical display names
                name = f"{_safe(p['display_name'])}_{p['player_id']}.pdf"
            used_names.add(name)
            zf.writestr(name, pdf)
            written += 1

    if written == 0:
        abort(404)

    # Friendly zip name: LMU_pitching_<date>_vs_<opp>.zip when context is available.
    zip_name = f"LMU_pitching_reports_game_{game_id}.zip"
    try:
        ctx = pitching_caps.game_context(game_id)
        opp = ctx["away_team"] if ctx["lmu_is_home"] else ctx["home_team"]
        zip_name = f"LMU_pitching_{_safe(ctx['game_date'])}_vs_{_safe(opp)}.zip"
    except Exception:  # noqa: BLE001 -- name is cosmetic; never fail the download
        pass

    buf.seek(0)
    return Response(
        buf.getvalue(), mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@report_bp.route("/bullpen")
@login_required
def bullpen_landing():
    """Pick an LMU pitcher, then download a bullpen session report.

    Coaches see all LMU pitchers; a player sees only their own (self-only,
    matching the PDF gate) — no roster/session enumeration for players.
    """
    pitchers = BULL.lmu_bullpen_pitchers()
    if getattr(current_user, "role", None) != "coach":
        tm = current_user.trackman_id
        pitchers = (pitchers[pitchers["pitcher_id"].astype(str) == str(tm)]
                    if tm is not None else pitchers.iloc[0:0])
    pid = request.args.get("pitcher_id", type=int)
    sessions = None
    selected = None
    if pid is not None and can_view_bullpen(current_user, pid):
        match = pitchers[pitchers["pitcher_id"] == pid]
        if not match.empty:
            selected = match.iloc[0].to_dict()
        sessions = BULL.sessions_for(pid).to_dict("records")
    return render_template(
        "reports/bullpen_landing.html",
        pitchers=pitchers.to_dict("records"), pitcher_id=pid,
        selected=selected, sessions=sessions,
        data_max_date=BULL.bullpen_data_max_date(),
    )


@report_bp.route("/bullpen/<int:pitcher_id>/<date>.pdf")
@login_required
def bullpen_pdf(pitcher_id: int, date: str):
    if not can_view_bullpen(current_user, pitcher_id):
        abort(403)
    try:
        pdf = build_bullpen_report(pitcher_id, date)
    except ReportDataError:
        abort(404)
    return Response(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="bullpen_{pitcher_id}_{_safe(date)}.pdf"'},
    )
