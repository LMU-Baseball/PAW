"""The Forge: page + JSON API (see app.data.forge for the model)."""
from __future__ import annotations

import logging

from flask import Blueprint, abort, jsonify, redirect, render_template, request
from flask_login import current_user, login_required
from flask_wtf.csrf import CSRFError, generate_csrf, validate_csrf
from wtforms.validators import ValidationError

from app.data import forge as F
from app.data import forge_storage as S
from app.data.seasons import season_label_for
from app.extensions import db, limiter

log = logging.getLogger(__name__)

forge_bp = Blueprint("forge", __name__, url_prefix="/forge")


@forge_bp.before_request
@login_required
def _require_login():
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        try:
            validate_csrf(request.headers.get("X-CSRFToken", ""))
        except (ValidationError, CSRFError):
            abort(400, "Your session expired -- reload the page.")


def _json_error(msg: str, status: int = 400):
    return jsonify({"error": msg}), status


def _channel_or_404(channel_id: int):
    channel = F.get_channel(channel_id)
    if channel is None:
        abort(404)
    return channel


def _payload() -> dict:
    return request.get_json(silent=True) or {}


@forge_bp.route("/")
def index():
    return render_template(
        "forge/index.html",
        forge_config={
            "me": current_user.id,
            "is_coach": bool(current_user.is_coach),
            "csrf": generate_csrf(),
            "uploads_enabled": S.configured(),
            "season": season_label_for(F._now().date().isoformat()),
            "max_bytes": F.MAX_UPLOAD_BYTES,
            "max_duration": F.MAX_DURATION_SEC,
        })


@forge_bp.route("/api/channels")
def api_channels():
    return jsonify({"channels": F.channels_for(current_user, request.args.get("season"))})


@forge_bp.route("/api/channels/<int:channel_id>/posts")
def api_posts(channel_id):
    channel = _channel_or_404(channel_id)
    after = request.args.get("after", type=int) or 0
    season = request.args.get("season") or None
    return jsonify({
        "channel": {"id": channel.id, "name": channel.name,
                    "can_upload": F.can_upload(current_user, channel.id),
                    "seasons": F.channel_seasons(channel.id)},
        "posts": F.list_posts(channel.id, current_user, season=season, after_id=after),
        "videos": F.video_states(channel.id, request.args.get("videos", "")),
    })


@forge_bp.route("/api/channels/<int:channel_id>/posts", methods=["POST"])
@limiter.limit("60 per minute")
def api_add_post(channel_id):
    channel = _channel_or_404(channel_id)
    data = _payload()
    try:
        post = F.add_post(channel.id, current_user, data.get("body", ""),
                          parent_id=data.get("parent_id"))
    except ValueError as e:
        return _json_error(str(e))
    return jsonify({"post": F._post_dict(post, current_user)}), 201


@forge_bp.route("/api/posts/<int:post_id>", methods=["DELETE"])
def api_delete_post(post_id):
    post = db.session.get(F.ForgePost, post_id)
    if post is None or post.deleted_at is not None:
        abort(404)
    if not F.can_delete(current_user, post):
        abort(403)
    F.delete_post(post, current_user)
    return jsonify({"ok": True})


@forge_bp.route("/api/channels/<int:channel_id>/read", methods=["POST"])
def api_mark_read(channel_id):
    _channel_or_404(channel_id)
    F.mark_read(current_user.id, channel_id)
    return jsonify({"ok": True})


@forge_bp.route("/api/channels/<int:channel_id>/uploads", methods=["POST"])
@limiter.limit("30 per hour")
def api_start_upload(channel_id):
    channel = _channel_or_404(channel_id)
    if not F.can_upload(current_user, channel.id):
        abort(403)
    if not S.configured():
        return _json_error("Video uploads aren't set up yet.", 503)
    data = _payload()
    size = int(data.get("size") or 0)
    duration = float(data.get("duration") or 0)
    if size <= 0:
        return _json_error("That file is empty.")
    if size > F.MAX_UPLOAD_BYTES:
        return _json_error("That video is over 4 GB. Trim it in Photos and try again.")
    if duration > F.MAX_DURATION_SEC + 30:
        return _json_error("Videos can be up to 20 minutes. Trim it in Photos and try again.")
    video = F.create_video(channel.id, current_user, data.get("name", ""), size)
    key = S.original_key(channel.id, video.id, video.original_name)
    try:
        upload_id, urls = S.start_multipart(key, data.get("type", ""), size)
    except Exception:
        log.exception("forge: couldn't start upload for video %s", video.id)
        F.set_video(video, status="failed", error="couldn't start upload")
        return _json_error("Couldn't start the upload. Try again in a minute.", 502)
    F.set_video(video, original_key=key, upload_id=upload_id)
    return jsonify({"video_id": video.id, "part_size": S.PART_SIZE, "urls": urls}), 201


def _own_upload_or_404(video_id):
    video = db.session.get(F.ForgeVideo, video_id)
    if video is None or video.status != "uploading" or video.uploader_id != current_user.id:
        abort(404)
    return video


@forge_bp.route("/api/uploads/<int:video_id>/complete", methods=["POST"])
def api_complete_upload(video_id):
    video = _own_upload_or_404(video_id)
    data = _payload()
    parts = data.get("parts") or []
    if len(parts) != S.part_count(video.original_size):
        return _json_error("The upload is missing pieces -- try again.")
    try:
        S.complete_multipart(video.original_key, video.upload_id, parts)
    except Exception:
        log.exception("forge: couldn't complete upload for video %s", video.id)
        return _json_error("Couldn't finish the upload. Try again.", 502)
    F.set_video(video, status="queued", upload_id=None)
    post = F.add_post(video.channel_id, current_user, data.get("note", ""), video_id=video.id)
    return jsonify({"post": F._post_dict(post, current_user)}), 201


@forge_bp.route("/api/uploads/<int:video_id>/abort", methods=["POST"])
def api_abort_upload(video_id):
    video = _own_upload_or_404(video_id)
    try:
        S.abort_multipart(video.original_key, video.upload_id)
    except Exception:
        log.warning("forge: abort failed for video %s", video.id, exc_info=True)
    F.set_video(video, status="failed", error="cancelled", upload_id=None)
    return jsonify({"ok": True})


def _ready_video_or_404(video_id):
    video = db.session.get(F.ForgeVideo, video_id)
    if video is None or video.status != "ready" or F.get_channel(video.channel_id) is None:
        abort(404)
    post = F.ForgePost.query.filter_by(video_id=video.id).first()
    if post is None or post.deleted_at is not None:
        abort(404)
    return video


@forge_bp.route("/video/<int:video_id>/play")
def play(video_id):
    video = _ready_video_or_404(video_id)
    return redirect(S.view_url(video.playback_key, "video/mp4"))


@forge_bp.route("/video/<int:video_id>/thumb")
def thumb(video_id):
    video = _ready_video_or_404(video_id)
    if not video.thumb_key:
        abort(404)
    return redirect(S.view_url(video.thumb_key, "image/jpeg"))
