"""The Forge: one Slack-style channel per pitcher for offseason video and
back-and-forth with the coaches.

A channel belongs to a player account that said it pitches ("pitcher" or
"both") at sign-up, and is named for that account -- there is no roster
lookup or name matching, so a player sees exactly the name they signed up
with. Accounts linked to a channel before sign-up asked are tagged pitchers.
Anyone signed in can read and comment in any channel; only its owner (or a
coach) can post video there. Video bytes never live in this database -- they
sit in a private S3 bucket (app.data.forge_storage); `ForgeVideo` holds only
the keys and processing state. Posts are soft-deleted so a removed message can
be recovered, and a channel is never deleted, so an account that's turned off
or stops being a pitcher keeps its history (it just drops off the list).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, text

from app.auth.models import PITCHER_TYPES, PLAYER_TYPES, User
from app.data.seasons import season_bounds, season_label_for
from app.extensions import add_missing_columns, db

MAX_UPLOAD_BYTES = 4 * 1024 ** 3
MAX_DURATION_SEC = 20 * 60
MAX_BODY_CHARS = 4000
# Uploads that never finished (tab closed mid-upload) are given up on after this.
STALE_UPLOAD_HOURS = 24

VIDEO_STATUSES = ("uploading", "queued", "processing", "ready", "failed")

# A coach-only channel for trying uploads without touching a real pitcher's
# history. Channels made before accounts owned them were keyed by normalized
# roster name (a-z0-9 only), so neither special key can collide with those.
SANDBOX_KEY = "__coach_test__"
SANDBOX_NAME = "Test Channel"
_ACCOUNT_PREFIX = "__user_"


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
    # Added after forge_videos shipped; ensure_columns() adds it to the live table.
    strip_audio = db.Column(db.Boolean, nullable=False, default=False, server_default=text("0"))

    def to_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "duration_sec": self.duration_sec,
                "width": self.width, "height": self.height, "error": self.error,
                "name": self.original_name, "muted": bool(self.strip_audio)}


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
    edited_at = db.Column(db.DateTime, index=True)

    author = db.relationship(User, foreign_keys=[author_id], lazy="joined")
    video = db.relationship(ForgeVideo, lazy="joined")


class ForgeRead(db.Model):
    """How far each user has read in each channel, for unread badges."""
    __tablename__ = "forge_reads"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("forge_channels.id"), primary_key=True)
    last_read_post_id = db.Column(db.Integer, nullable=False, default=0)


# Columns added to Forge tables after they first shipped: (table, column, DDL).
# create_all() never alters an existing table, so these are added here --
# additive only, skipped when already present, safe to run on every boot.
_ADDED_COLUMNS = (
    ("forge_videos", "strip_audio", "strip_audio BOOLEAN NOT NULL DEFAULT 0"),
    ("forge_posts", "edited_at", "edited_at DATETIME"),
)


def ensure_columns(engine=None) -> None:
    add_missing_columns(engine or db.engine, _ADDED_COLUMNS)


# --- permissions ---

def can_upload(user, channel: ForgeChannel) -> bool:
    return bool(user.is_authenticated and
                (user.is_coach or (channel.joined and channel.user_id == user.id)))


def can_delete(user, post: ForgePost) -> bool:
    return bool(user.is_authenticated and (user.is_coach or user.id == post.author_id))


def can_edit(user, post: ForgePost) -> bool:
    return bool(user.is_authenticated and user.id == post.author_id and post.deleted_at is None)


# --- channels ---

def needs_player_type(user) -> bool:
    """A player account made before sign-up asked position player / pitcher /
    both, and not already linked to a channel (those are tagged pitchers)."""
    return bool(user.is_authenticated and user.role == "player" and user.player_type is None
                and channel_of(user) is None)


def channel_of(user) -> ForgeChannel | None:
    return ForgeChannel.query.filter_by(user_id=user.id).first()


def _ensure_channel(user) -> ForgeChannel:
    channel = channel_of(user)
    if channel is None:
        channel = ForgeChannel(name_key=f"{_ACCOUNT_PREFIX}{user.id}__", name=user.name,
                               user_id=user.id)
        db.session.add(channel)
    return channel


def set_player_type(user, player_type: str) -> ForgeChannel | None:
    """Record whether `user` is a position player, pitcher or both; a pitcher
    gets their channel. Returns the channel, or None for a position player."""
    if player_type not in PLAYER_TYPES:
        raise ValueError("Pick position player, pitcher, or both.")
    if user.role != "player":
        raise ValueError("Only player accounts pick a position.")
    user.player_type = player_type
    channel = _ensure_channel(user) if player_type in PITCHER_TYPES else None
    db.session.commit()
    return channel


def sync_channels() -> list[ForgeChannel]:
    """Every active pitcher account's channel, named for the account (a
    renamed account renames its channel). Tags accounts linked to a channel
    before sign-up asked as pitchers. Idempotent."""
    for channel in ForgeChannel.query.filter(ForgeChannel.user_id.isnot(None)).all():
        if channel.user.role == "player" and channel.user.player_type is None:
            channel.user.player_type = "pitcher"
    pitchers = User.query.filter(User.role == "player", User.is_active.is_(True),
                                 User.player_type.in_(PITCHER_TYPES)).all()
    owned = {c.user_id: c for c in ForgeChannel.query.filter(
        ForgeChannel.user_id.in_([u.id for u in pitchers])).all()} if pitchers else {}
    channels = []
    for user in pitchers:
        channel = owned.get(user.id) or _ensure_channel(user)
        if channel.name != user.name:
            channel.name = user.name
        channels.append(channel)
    db.session.commit()
    return sorted(channels, key=lambda c: c.name.lower())


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


def channels_for(viewer) -> list[dict]:
    """The pitcher channels, with the coach-only test channel first for
    coaches. Coaches get unread badges on every channel; players only on
    their own, so they aren't clicking through teammates' channels just to
    clear badges."""
    channels = sync_channels()
    if viewer.is_coach:
        channels = [sandbox_channel()] + channels
    unread = unread_counts(viewer.id)
    out = []
    for c in channels:
        mine = c.user_id is not None and c.user_id == viewer.id
        badge = unread.get(c.id, 0) if viewer.is_coach or mine else 0
        out.append({"id": c.id, "name": c.name, "joined": c.joined, "sandbox": c.is_sandbox,
                    "unread": badge, "mine": mine})
    return out


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
        "can_edit": can_edit(viewer, post),
        "edited": (not deleted) and post.edited_at is not None,
    }


def list_posts(channel_id: int, viewer, season: str | None = None,
               after_id: int = 0, since: datetime | None = None) -> list[dict]:
    """A channel's posts, oldest first, as a flat list (comments carry
    `parent_id`). `season` limits top-level posts to that academic year, and
    their comments come along whenever they were written. `after_id` (polling)
    returns everything newer than the client's last post, season aside, plus
    any older post edited or deleted since the client's last poll (`since`)."""
    base = ForgePost.query.filter(ForgePost.channel_id == channel_id)
    if after_id:
        changed = ForgePost.id > after_id
        if since is not None:
            changed = or_(changed, ForgePost.edited_at >= since, ForgePost.deleted_at >= since)
        return [_post_dict(p, viewer) for p in
                base.filter(changed).order_by(ForgePost.id).all()]
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


def edit_post(post: ForgePost, body: str) -> ForgePost:
    body = (body or "").strip()
    if len(body) > MAX_BODY_CHARS:
        raise ValueError(f"Messages are limited to {MAX_BODY_CHARS} characters.")
    if not body and post.video_id is None:
        raise ValueError("A message can't be empty -- delete it instead.")
    if body != post.body:
        post.body = body
        post.edited_at = _now()
        db.session.commit()
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

def create_video(channel_id: int, uploader, name: str, size: int,
                 strip_audio: bool = False) -> ForgeVideo:
    video = ForgeVideo(channel_id=channel_id, uploader_id=uploader.id,
                       original_name=(name or "video")[:255], original_size=size,
                       status="uploading", strip_audio=bool(strip_audio))
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
