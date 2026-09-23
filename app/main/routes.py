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
    """Streams one Built on the Bluff video's bytes (Recovery/Gas Station
    titled links -- see app.data.splash_report). Login-gated like every
    other page in the app; not otherwise access-controlled (same
    team-transparent model as the rest of Built on the Bluff -- any
    signed-in coach or player can view any clip)."""
    from app.data import splash_report as SR
    video = SR.get_video(video_id)
    if video is None:
        abort(404)
    return send_file(io.BytesIO(video["data"]), mimetype=video["mimetype"],
                     download_name=video["title"], as_attachment=False)


@main_bp.route("/bullpen-video/<path:play_id>")
@login_required
def bullpen_video(play_id: str):
    """Streams one bullpen pitch's Edgertronic clip bytes out of the
    database (see app.data.bullpen_video's module docstring for why a DB
    BLOB, not local disk/S3). `<path:play_id>` (not `<string:...>`) because
    TrackMan play ids are GUIDs, which never contain a `/`, but `path` costs
    nothing and is a strictly safer converter to default to for an id string
    sourced from an external system. Login-gated + team-transparent, same as
    `/splash-video/<id>` above."""
    from app.data import bullpen_video as BV
    clip = BV.get_clip(play_id)
    if clip is None or clip.get("data") is None:
        abort(404)
    resp = send_file(io.BytesIO(clip["data"]), mimetype=clip.get("mimetype") or "video/mp4",
                     as_attachment=False)
    # Each fetch costs a real DB round-trip for the full blob (~1.5-2s,
    # confirmed live 2026-09-22) -- a play_id's clip is essentially static
    # once downloaded (the loader only overwrites it for a rare TrackMan
    # re-upload, see app.data.bullpen_video.add_clip), so let the browser
    # cache it instead of re-fetching on every seek/replay.
    resp.cache_control.private = True
    resp.cache_control.max_age = 86400
    return resp
