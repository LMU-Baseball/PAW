"""Home / landing page (the app shell that links to the dashboards)."""
import io

from flask import Blueprint, abort, render_template, send_file
from flask_login import current_user, login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    return render_template("main/index.html", user=current_user)


@main_bp.route("/pitching")
@login_required
def pitching():
    return render_template("main/pitching_hub.html", user=current_user)


@main_bp.route("/hitting")
@login_required
def hitting():
    return render_template("main/hitting_hub.html", user=current_user)


@main_bp.route("/catching")
@login_required
def catching():
    return render_template("main/catching_hub.html", user=current_user)


@main_bp.route("/splash-video/<int:video_id>")
@login_required
def splash_video(video_id: int):
    """Streams one Splash Report video's bytes (Recovery/Gas Station titled
    links -- see app.data.splash_report). Login-gated like every other page
    in the app; not otherwise access-controlled (same team-transparent
    model as the rest of Splash Report -- any signed-in coach or player can
    view any clip)."""
    from app.data import splash_report as SR
    video = SR.get_video(video_id)
    if video is None:
        abort(404)
    return send_file(io.BytesIO(video["data"]), mimetype=video["mimetype"],
                     download_name=video["title"], as_attachment=False)
