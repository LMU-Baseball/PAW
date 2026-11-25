"""The Forge: one Slack-style channel per rostered pitcher for offseason video
and back-and-forth with the coaches.

Channels come from the season's reviewed roster file (RHP/LHP), so every
pitcher has one whether or not they've made a PAW account yet. A channel is
keyed by the pitcher's normalized name and links to their account
(`user_id`) when they pick it at sign-up -- or, for accounts made before
sign-up asked, automatically once an account with a matching name exists. A
pitcher who isn't on the roster file gets a channel of their own, named for
their account.
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

from sqlalchemy import func, or_, text

from app.auth.models import PITCHER_TYPES, PLAYER_TYPES, User
from app.data.roster_media import _name_parts, _norm_name
from app.data.seasons import season_bounds, season_label_for
from app.extensions import add_missing_columns, db

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
# Channels for pitchers who aren't on the roster file are keyed by account,
# which (like the sandbox key) can't collide with a normalized name.
_OWN_PREFIX = "__user_"
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
    def is_own(self) -> bool:
        return self.name_key.startswith(_OWN_PREFIX)

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


def _single_first_name(name: str) -> str:
    tokens = re.findall(r"[a-z]+", (name or "").lower())
    return tokens[0] if len(tokens) == 1 else ""


def _link_accounts(channels: list[ForgeChannel], accounts: list) -> None:
    """Link channels waiting on an account to player accounts whose sign-up
    name doesn't exactly match the roster -- players type nicknames ("Charles"
    for Charlie, "Matt" for Matthew) or only a first name ("Will"). Looser
    passes run only after stricter ones, and a pass links a channel only when
    it and the account pick each other uniquely, so an ambiguous name stays
    unlinked rather than handing one pitcher's channel to another player."""
    roster_firsts = [_name_parts(c.name)[0] for c in channels]

    def exact(ch, u):
        return _norm_name(u.name) == ch.name_key

    def last_and_initial(ch, u):
        cf, cl = _name_parts(ch.name)
        uf, ul = _name_parts(u.name)
        return bool(cl) and ul == cl and uf[:1] == cf[:1]

    def first_name_only(ch, u):
        first = _single_first_name(u.name)
        cf = _name_parts(ch.name)[0]
        return bool(first) and first == cf and roster_firsts.count(cf) == 1

    for ch in channels:
        picks = [u for u in accounts if exact(ch, u)]
        if picks:
            ch.user_id = picks[0].id
            accounts.remove(picks[0])
    for matches in (last_and_initial, first_name_only):
        open_chans = [c for c in channels if c.user_id is None]
        for ch in open_chans:
            picks = [u for u in accounts if matches(ch, u)]
            if len(picks) != 1:
                continue
            u = picks[0]
            if sum(1 for c in open_chans if c.user_id is None and matches(c, u)) == 1:
                ch.user_id = u.id
                accounts.remove(u)


def sync_channels(season: str | None = None) -> list[ForgeChannel]:
    """Make sure every rostered pitcher has a channel, link any channel still
    waiting on an account to a newly matching player account, and return the
    season's channels plus every active off-roster pitcher's own channel.
    Idempotent; a channel is never deleted, so a pitcher who leaves the roster
    keeps their history (just drops off the list).

    Only accounts that never answered "position player / pitcher / both" are
    matched by name: anyone who answered picked their channel themselves, so a
    position player is never handed a pitcher's channel because the names look
    alike. A linked account that never answered is tagged a pitcher."""
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
    waiting = [c for c in existing.values() if c.user_id is None]
    if waiting:
        linked = {uid for (uid,) in db.session.query(ForgeChannel.user_id)
                  .filter(ForgeChannel.user_id.isnot(None)).all()}
        accounts = [u for u in User.query.filter_by(role="player", is_active=True,
                                                    player_type=None)
                    .order_by(User.id).all() if u.id not in linked]
        _link_accounts(waiting, accounts)
    own = (ForgeChannel.query.join(User, ForgeChannel.user_id == User.id)
           .filter(ForgeChannel.name_key.startswith(_OWN_PREFIX), User.is_active.is_(True))
           .all())
    channels = list(existing.values()) + own
    for c in channels:
        u = db.session.get(User, c.user_id) if c.user_id else None
        if u is not None and u.role == "player" and u.player_type is None:
            u.player_type = "pitcher"
    db.session.commit()
    return sorted(channels, key=lambda c: c.name.lower())


def channel_of(user) -> ForgeChannel | None:
    return ForgeChannel.query.filter_by(user_id=user.id).first()


def claimable_channels(season: str | None = None) -> list[dict]:
    """The season's rostered pitchers no account has claimed yet, for the
    "which pitcher are you?" pick."""
    return [{"id": c.id, "name": c.name} for c in sync_channels(season)
            if c.user_id is None and not c.is_own]


def needs_claim(user) -> bool:
    """A player account that never said whether it pitches and has no channel
    yet -- made before sign-up asked, under a name that didn't match."""
    return bool(user.is_authenticated and user.role == "player"
                and user.player_type is None and channel_of(user) is None)


def claim(user, player_type: str, channel_id: int | None = None) -> ForgeChannel | None:
    """Record whether `user` is a position player, pitcher or both, and give a
    pitcher their channel: the unclaimed roster channel they picked, or (when
    they're not on the roster) one of their own named for their account.
    Returns the channel, or None for a position player."""
    if player_type not in PLAYER_TYPES:
        raise ValueError("Pick position player, pitcher, or both.")
    if user.role != "player":
        raise ValueError("Only player accounts pick a position.")
    if channel_of(user) is not None:
        raise ValueError("Your account already has a Forge channel -- ask a coach to change it.")
    channel = None
    if player_type in PITCHER_TYPES:
        if channel_id:
            channel = db.session.get(ForgeChannel, int(channel_id))
            if channel is None or channel.is_sandbox or channel.is_own:
                raise ValueError("That pitcher isn't on the roster.")
            if channel.user_id is not None:
                raise ValueError(f"{channel.name} is already linked to another account -- "
                                 "ask a coach if that's wrong.")
        else:
            channel = ForgeChannel(name_key=f"{_OWN_PREFIX}{user.id}__", name=user.name)
            db.session.add(channel)
        channel.user_id = user.id
    user.player_type = player_type
    db.session.commit()
    return channel


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
