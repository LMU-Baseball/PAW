"""The Forge: one Slack-style channel per rostered pitcher for offseason video
and back-and-forth with the coaches.

Channels come from the season's reviewed roster file (RHP/LHP), so every
pitcher has one whether or not they've made a PAW account yet. A channel is
keyed by the pitcher's normalized name and links to their account
(`user_id`) automatically once an account with a matching name exists.
Anyone signed in can read and comment in any channel; only the linked player
(or a coach) can post video there. Video bytes never live in this database -- they sit in a
private S3 bucket (app.data.forge_storage); `ForgeVideo` holds only the keys and
processing state. Posts are soft-deleted so a removed message can be recovered.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func

from app.auth.models import User
from app.data.roster_media import _norm_name
from app.data.seasons import season_bounds, season_label_for
from app.extensions import db

MAX_UPLOAD_BYTES = 4 * 1024 ** 3
MAX_DURATION_SEC = 20 * 60
MAX_BODY_CHARS = 4000
# Uploads that never finished (tab closed mid-upload) are given up on after this.
STALE_UPLOAD_HOURS = 24

VIDEO_STATUSES = ("uploading", "queued", "processing", "ready", "failed")

_ROSTER_DIR = Path(__file__).resolve().parents[2] / "data" / "rosters"
# A coach-only channel for trying uploads without touching a real pitcher's
# history. Its key can't collide with a normalized name (those are only a-z0-9).
SANDBOX_KEY = "__coach_test__"
SANDBOX_NAME = "Test Channel"
_PITCHER_TOKENS = {"RHP", "LHP"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ForgeChannel(db.Model):
    __tablename__ = "forge_channels"

    id = db.Column(db.Integer, primary_key=True)
    name_key = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)

    user = db.relationship(User, lazy="joined")

    @property
    def is_sandbox(self) -> bool:
        return self.name_key == SANDBOX_KEY

    @property
    def joined(self) -> bool:
        return self.is_sandbox or (self.user is not None and self.user.is_active)


class ForgeVideo(db.Model):
    __tablename__ = "forge_videos"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("forge_channels.id"), nullable=False, index=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="uploading", index=True)
    original_name = db.Column(db.String(255))
    original_size = db.Column(db.BigInteger)
    original_key = db.Column(db.String(512))
    upload_id = db.Column(db.String(512))
    playback_key = db.Column(db.String(512))
    thumb_key = db.Column(db.String(512))
    playback_size = db.Column(db.BigInteger)
    duration_sec = db.Column(db.Float)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    error = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    processed_at = db.Column(db.DateTime)

    def to_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "duration_sec": self.duration_sec,
                "width": self.width, "height": self.height, "error": self.error,
                "name": self.original_name}


class ForgePost(db.Model):
    """A channel message. `parent_id` set = a comment under a video post."""
    __tablename__ = "forge_posts"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("forge_channels.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("forge_posts.id"), index=True)
    video_id = db.Column(db.Integer, db.ForeignKey("forge_videos.id"))
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=_now, index=True)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.Integer)

    author = db.relationship(User, foreign_keys=[author_id], lazy="joined")
    video = db.relationship(ForgeVideo, lazy="joined")


class ForgeRead(db.Model):
    """How far each user has read in each channel, for unread badges."""
    __tablename__ = "forge_reads"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("forge_channels.id"), primary_key=True)
    last_read_post_id = db.Column(db.Integer, nullable=False, default=0)


# --- permissions ---

def can_upload(user, channel: ForgeChannel) -> bool:
    return bool(user.is_authenticated and
                (user.is_coach or (channel.joined and channel.user_id == user.id)))


def can_delete(user, post: ForgePost) -> bool:
    return bool(user.is_authenticated and (user.is_coach or user.id == post.author_id))


# --- channels ---

def _roster_pitchers(season: str) -> list[str]:
    """"First Last" for each RHP/LHP in the season's reviewed roster file
    (empty when there's no file for that season)."""
    path = _ROSTER_DIR / f"{season.replace('/', '-')}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        players = json.load(fh)
    names = []
    for p in players:
        tokens = set(re.split(r"[/,&\s]+", (p.get("position") or "").upper()))
        if tokens & _PITCHER_TOKENS:
            names.append(f"{p['first_name']} {p['last_name']}".strip())
    return names


def _current_season() -> str:
    return season_label_for(_now().date().isoformat())


def sync_channels(season: str | None = None) -> list[ForgeChannel]:
    """Make sure every rostered pitcher has a channel, link any channel still
    waiting on an account to a newly matching player account, and return the
    season's channels. Idempotent; a channel is never deleted, so a pitcher who
    leaves the roster keeps their history (just drops off the list)."""
    names = _roster_pitchers(season or _current_season())
    keys = {}
    for name in names:
        keys.setdefault(_norm_name(name), name)
    existing = {c.name_key: c for c in
                ForgeChannel.query.filter(ForgeChannel.name_key.in_(list(keys))).all()} if keys else {}
    for key, name in keys.items():
        if key not in existing:
            existing[key] = ForgeChannel(name_key=key, name=name)
            db.session.add(existing[key])
    waiting = {c.name_key: c for c in existing.values() if c.user_id is None}
    if waiting:
        linked = {uid for (uid,) in db.session.query(ForgeChannel.user_id)
                  .filter(ForgeChannel.user_id.isnot(None)).all()}
        for u in (User.query.filter_by(role="player", is_active=True)
                  .order_by(User.id).all()):
            ch = waiting.get(_norm_name(u.name))
            if ch is not None and ch.user_id is None and u.id not in linked:
                ch.user_id = u.id
                linked.add(u.id)
    db.session.commit()
    return sorted(existing.values(), key=lambda c: c.name.lower())


def sandbox_channel() -> ForgeChannel:
    ch = ForgeChannel.query.filter_by(name_key=SANDBOX_KEY).first()
    if ch is None:
        ch = ForgeChannel(name_key=SANDBOX_KEY, name=SANDBOX_NAME)
        db.session.add(ch)
        db.session.commit()
    return ch


def can_view(user, channel: ForgeChannel) -> bool:
    return bool(user.is_authenticated and (user.is_coach or not channel.is_sandbox))


def get_channel(channel_id: int) -> ForgeChannel | None:
    return db.session.get(ForgeChannel, channel_id)


def channels_for(viewer, season: str | None = None) -> list[dict]:
    """The season's pitcher channels, with the coach-only test channel first
    for coaches."""
    channels = sync_channels(season)
    if viewer.is_coach:
        channels = [sandbox_channel()] + channels
    unread = unread_counts(viewer.id)
    return [{"id": c.id, "name": c.name, "joined": c.joined, "sandbox": c.is_sandbox,
             "unread": unread.get(c.id, 0),
             "mine": c.user_id is not None and c.user_id == viewer.id}
            for c in channels]


# --- posts ---

def _post_dict(post: ForgePost, viewer) -> dict:
    deleted = post.deleted_at is not None
    return {
        "id": post.id,
        "parent_id": post.parent_id,
        "author": post.author.name if post.author else "Unknown",
        "author_id": post.author_id,
        "author_is_coach": bool(post.author and post.author.is_coach),
        "body": "" if deleted else post.body,
        "deleted": deleted,
        "created_at": post.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "video": None if (deleted or post.video is None) else post.video.to_dict(),
        "can_delete": (not deleted) and can_delete(viewer, post),
    }


def list_posts(channel_id: int, viewer, season: str | None = None,
               after_id: int = 0) -> list[dict]:
    """A channel's posts, oldest first, as a flat list (comments carry
    `parent_id`). `season` limits top-level posts to that academic year, and
    their comments come along whenever they were written. `after_id` (polling)
    returns everything newer than the client's last post, season aside."""
    base = ForgePost.query.filter(ForgePost.channel_id == channel_id)
    if after_id:
        return [_post_dict(p, viewer) for p in
                base.filter(ForgePost.id > after_id).order_by(ForgePost.id).all()]
    top = base.filter(ForgePost.parent_id.is_(None))
    if season:
        start, end = season_bounds(season)
        top = top.filter(ForgePost.created_at >= datetime.fromisoformat(start),
                         ForgePost.created_at < datetime.fromisoformat(end) + timedelta(days=1))
    top_posts = top.order_by(ForgePost.id).all()
    ids = [p.id for p in top_posts]
    comments = (base.filter(ForgePost.parent_id.in_(ids)).order_by(ForgePost.id).all()
                if ids else [])
    posts = sorted(top_posts + comments, key=lambda p: p.id)
    return [_post_dict(p, viewer) for p in posts]


def channel_seasons(channel_id: int) -> list[str]:
    rows = db.session.query(ForgePost.created_at).filter(
        ForgePost.channel_id == channel_id).all()
    labels = {season_label_for(r[0].date().isoformat()) for r in rows}
    labels.add(season_label_for(_now().date().isoformat()))
    return sorted(labels, reverse=True)


def add_post(channel_id: int, author, body: str, parent_id: int | None = None,
             video_id: int | None = None) -> ForgePost:
    body = (body or "").strip()
    if len(body) > MAX_BODY_CHARS:
        raise ValueError(f"Messages are limited to {MAX_BODY_CHARS} characters.")
    if not body and video_id is None:
        raise ValueError("Type a message first.")
    if parent_id is not None:
        parent = db.session.get(ForgePost, parent_id)
        if parent is None or parent.channel_id != channel_id or parent.parent_id is not None:
            raise ValueError("That post can't be replied to.")
    post = ForgePost(channel_id=channel_id, author_id=author.id, body=body,
                     parent_id=parent_id, video_id=video_id)
    db.session.add(post)
    db.session.commit()
    mark_read(author.id, channel_id, post.id)
    return post


def delete_post(post: ForgePost, user) -> None:
    post.deleted_at = _now()
    post.deleted_by = user.id
    db.session.commit()


# --- unread ---

def mark_read(user_id: int, channel_id: int, post_id: int | None = None) -> None:
    if post_id is None:
        post_id = db.session.query(func.max(ForgePost.id)).filter(
            ForgePost.channel_id == channel_id).scalar() or 0
    row = db.session.get(ForgeRead, (user_id, channel_id))
    if row is None:
        db.session.add(ForgeRead(user_id=user_id, channel_id=channel_id,
                                 last_read_post_id=post_id))
    elif post_id > row.last_read_post_id:
        row.last_read_post_id = post_id
    db.session.commit()


def unread_counts(user_id: int) -> dict[int, int]:
    """Unread posts per channel, not counting the user's own or deleted ones."""
    reads = {r.channel_id: r.last_read_post_id
             for r in ForgeRead.query.filter_by(user_id=user_id).all()}
    rows = (db.session.query(ForgePost.channel_id, ForgePost.id)
            .filter(ForgePost.author_id != user_id, ForgePost.deleted_at.is_(None)).all())
    counts: dict[int, int] = {}
    for channel_id, post_id in rows:
        if post_id > reads.get(channel_id, 0):
            counts[channel_id] = counts.get(channel_id, 0) + 1
    return counts


def total_unread(user_id: int) -> int:
    return sum(unread_counts(user_id).values())


# --- videos ---

def create_video(channel_id: int, uploader, name: str, size: int) -> ForgeVideo:
    video = ForgeVideo(channel_id=channel_id, uploader_id=uploader.id,
                       original_name=(name or "video")[:255], original_size=size,
                       status="uploading")
    db.session.add(video)
    db.session.commit()
    return video


def video_states(channel_id: int, ids_csv: str) -> dict[str, dict]:
    """Current state of the listed videos in a channel, so a client showing
    "Processing..." learns when one becomes ready."""
    ids = [int(x) for x in ids_csv.split(",") if x.strip().isdigit()][:50]
    if not ids:
        return {}
    rows = ForgeVideo.query.filter(ForgeVideo.channel_id == channel_id,
                                   ForgeVideo.id.in_(ids)).all()
    return {str(v.id): v.to_dict() for v in rows}


def set_video(video: ForgeVideo, **fields) -> None:
    for k, v in fields.items():
        setattr(video, k, v)
    db.session.commit()
