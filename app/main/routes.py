"""Home / landing page (the app shell that links to the dashboards)."""
import io
import re

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


@main_bp.route("/bullpen-video/<path:play_id>/download")
@login_required
def bullpen_video_download(play_id: str):
    """LMU-branded downloadable clip: pitch type/velo/break, a strike-zone
    box, and a movement chart burned onto the raw Edgertronic video
    (2026-09-23, Brad: players want to download their best pitches to
    share with recruiters). Generated on demand, not cached -- a real
    ffmpeg re-encode (not the streaming route's `-c copy` remux), so this
    takes noticeably longer than a normal play; fine for an occasional
    manual download, not something hit in a loop."""
    from app.data import bullpen as B
    from app.data import bullpen_video as BV
    from app.reports.bullpen_video_overlay import build_overlay_png, composite_overlay

    clip = BV.get_clip(play_id)
    if clip is None or clip.get("data") is None:
        abort(404)
    pitch = BV.pitch_row_by_play_id(play_id)
    if pitch is None:
        abort(404)
    session_df = BV.session_pitch_video_df(pitch["pitcher_id"], pitch["date"])
    player_name = B.pitcher_name(pitch["pitcher_id"]) or "Player"
    # "Pitch X/Y" is this pitch's position WITHIN the session (1-based), not
    # BULLPEN's own PitchNo -- that's a running count that does NOT reset
    # per session, so it can be well past the session's own pitch total
    # (confirmed live: PitchNo 81 in a 16-pitch session read as "81/16").
    # session_df is already ordered by PitchNo (session_pitch_video_df), so
    # its row position is exactly that rank.
    play_ids = list(session_df["play_id"])
    pitch_index = play_ids.index(play_id) + 1 if play_id in play_ids else 1

    overlay_png = build_overlay_png(
        pitch, session_df, player_name=player_name, date=pitch["date"],
        pitch_index=pitch_index, pitch_count=len(session_df),
        width=int(clip.get("width") or 1280), height=int(clip.get("height") or 720))
    composited = composite_overlay(clip["data"], overlay_png)

    safe_name = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]", "_", player_name)).strip("_")
    download_name = f"{safe_name}_{pitch.get('pitch_type') or 'pitch'}_{pitch['date']}.mp4"
    return send_file(io.BytesIO(composited), mimetype="video/mp4",
                     as_attachment=True, download_name=download_name)
