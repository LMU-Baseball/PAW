"""The Forge: channel permissions, messaging, unread badges, season filter,
the direct-to-S3 upload handshake, and the 720p transcode worker.

Runs entirely against a throwaway SQLite app DB with S3 faked out -- no shared
database rows and no AWS calls.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.auth.models import User
from app.data import forge as F
from app.data import forge_storage as S
from app.extensions import db
from config import Config

PITCHER_A = "Adam Behrens"
PITCHER_B = "Ryan Bresaw"
HITTER = "Cam Casado"


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.completed = []
        self.aborted = []
        self.deleted = []

    def install(self, monkeypatch):
        monkeypatch.setattr(S, "configured", lambda: True)
        monkeypatch.setattr(S, "start_multipart",
                            lambda key, ctype, size: ("up-1", [f"https://s3/{key}?part={n}"
                                                               for n in range(1, S.part_count(size) + 1)]))
        monkeypatch.setattr(S, "complete_multipart",
                            lambda key, upload_id, parts: self.completed.append((key, parts)))
        monkeypatch.setattr(S, "abort_multipart",
                            lambda key, upload_id: self.aborted.append(key))
        monkeypatch.setattr(S, "view_url", lambda key, ctype=None: f"https://signed/{key}")
        monkeypatch.setattr(S, "download", lambda key, path: shutil.copy(self.objects[key], path))
        monkeypatch.setattr(S, "upload", self._upload)
        monkeypatch.setattr(S, "delete", lambda key: self.deleted.append(key))

    def _upload(self, path, key, ctype):
        fd, keep = tempfile.mkstemp(suffix=os.path.splitext(path)[1])
        os.close(fd)
        shutil.copy(path, keep)
        self.objects[key] = keep


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.delenv("FORGE_S3_BUCKET", raising=False)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    application = create_app(TestConfig)
    with application.app_context():
        for email, name, role, kind in (("coach@lmu.edu", "Sean Coach", "coach", None),
                                        ("a@lmu.edu", PITCHER_A, "player", "pitcher"),
                                        ("b@lmu.edu", PITCHER_B, "player", "both"),
                                        ("h@lmu.edu", HITTER, "player", "position")):
            u = User(email=email, name=name, role=role, player_type=kind)
            u.set_password("password123")
            db.session.add(u)
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass


@pytest.fixture()
def s3(monkeypatch):
    fake = FakeS3()
    fake.install(monkeypatch)
    return fake


class Client:
    """Logged-in test client that sends the page's CSRF token like forge.js."""

    def __init__(self, app, email):
        self.c = app.test_client()
        self.c.post("/login", data={"email": email, "password": "password123"})
        page = self.c.get("/forge/")
        assert page.status_code == 200
        cfg = re.search(rb'id="forge-config" type="application/json">(.*?)</script>', page.data, re.S)
        self.cfg = json.loads(cfg.group(1))
        self.h = {"X-CSRFToken": self.cfg["csrf"]}

    def get(self, url):
        return self.c.get(url)

    def post(self, url, body=None):
        return self.c.post(url, json=body or {}, headers=self.h)

    def delete(self, url):
        return self.c.delete(url, headers=self.h)

    def patch(self, url, body=None):
        return self.c.patch(url, json=body or {}, headers=self.h)


def _uid(app, email):
    with app.app_context():
        return User.query.filter_by(email=email).one().id


def _chan(app, email_or_name):
    """Channel id for a player's account email, or for a channel name."""
    with app.app_context():
        F.sync_channels()
        if "@" in email_or_name:
            uid = User.query.filter_by(email=email_or_name).one().id
            return F.ForgeChannel.query.filter_by(user_id=uid).one().id
        return F.ForgeChannel.query.filter_by(name=email_or_name).one().id


def _say(client, channel, body, parent=None):
    r = client.post(f"/forge/api/channels/{channel}/posts", {"body": body, "parent_id": parent})
    assert r.status_code == 201, r.json
    return r.json["post"]


# --- page + channels ---

def test_forge_requires_login(app):
    r = app.test_client().get("/forge/")
    assert r.status_code in (302, 401)


def test_pitching_hub_links_forge_not_cauldron(app):
    c = Client(app, "a@lmu.edu")
    html = c.get("/pitching").data
    assert b"The Forge" in html and b"/forge/" in html
    assert b"Cauldron" not in html
    assert c.get("/dash/cauldron/").status_code == 404


def test_channels_are_pitcher_accounts_named_for_the_account(app):
    c = Client(app, "coach@lmu.edu")
    chans = c.get("/forge/api/channels").json["channels"]
    assert [(ch["name"], ch["joined"]) for ch in chans] == [
        (F.SANDBOX_NAME, True), (PITCHER_A, True), (PITCHER_B, True)]


def test_sync_is_idempotent(app):
    with app.app_context():
        first = [c.id for c in F.sync_channels()]
        assert [c.id for c in F.sync_channels()] == first
        assert F.ForgeChannel.query.filter(F.ForgeChannel.name_key != F.SANDBOX_KEY).count() == 2


def test_renamed_account_renames_its_channel(app):
    chan = _chan(app, "a@lmu.edu")
    with app.app_context():
        User.query.filter_by(email="a@lmu.edu").one().name = "Ace Behrens"
        db.session.commit()
    names = {ch["id"]: ch["name"] for ch in
             Client(app, "coach@lmu.edu").get("/forge/api/channels").json["channels"]}
    assert names[chan] == "Ace Behrens"


def test_position_player_gets_no_channel_and_cannot_upload_anywhere(app, s3):
    h = Client(app, "h@lmu.edu")
    names = [ch["name"] for ch in h.get("/forge/api/channels").json["channels"]]
    assert HITTER not in names
    assert h.post(f"/forge/api/channels/{_chan(app, 'a@lmu.edu')}/uploads",
                  {"name": "x.mov", "size": 10}).status_code == 403


def test_deactivated_account_drops_off_list_but_keeps_history(app):
    chan = _chan(app, "b@lmu.edu")
    with app.app_context():
        User.query.filter_by(email="b@lmu.edu").one().is_active = False
        db.session.commit()
    c = Client(app, "coach@lmu.edu")
    assert PITCHER_B not in [ch["name"] for ch in c.get("/forge/api/channels").json["channels"]]
    assert c.get(f"/forge/api/channels/{chan}/posts").json["channel"]["joined"] is False


def test_unknown_channel_is_404(app):
    c = Client(app, "a@lmu.edu")
    assert c.get("/forge/api/channels/9999/posts").status_code == 404


# --- messaging permissions ---

def test_player_can_read_and_comment_in_another_pitchers_channel(app):
    a, b = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu")
    chan_a = _chan(app, "a@lmu.edu")
    top = _say(a, chan_a, "Threw 40 today")
    _say(b, chan_a, "nice", parent=top["id"])
    posts = b.get(f"/forge/api/channels/{chan_a}/posts").json["posts"]
    assert [(p["body"], p["parent_id"]) for p in posts] == [("Threw 40 today", None),
                                                           ("nice", top["id"])]


def test_writes_need_csrf_token(app):
    a = Client(app, "a@lmu.edu")
    r = a.c.post(f"/forge/api/channels/{_chan(app, 'a@lmu.edu')}/posts", json={"body": "hi"})
    assert r.status_code == 400


def test_empty_and_oversized_messages_rejected(app):
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    assert a.post(f"/forge/api/channels/{chan}/posts", {"body": "   "}).status_code == 400
    assert a.post(f"/forge/api/channels/{chan}/posts",
                  {"body": "x" * (F.MAX_BODY_CHARS + 1)}).status_code == 400


def test_reply_must_target_a_top_level_post_in_the_same_channel(app):
    a = Client(app, "a@lmu.edu")
    chan_a, chan_b = _chan(app, "a@lmu.edu"), _chan(app, "b@lmu.edu")
    top = _say(a, chan_a, "top")
    reply = _say(a, chan_a, "reply", parent=top["id"])
    assert a.post(f"/forge/api/channels/{chan_b}/posts",
                  {"body": "x", "parent_id": top["id"]}).status_code == 400
    assert a.post(f"/forge/api/channels/{chan_a}/posts",
                  {"body": "x", "parent_id": reply["id"]}).status_code == 400


def test_delete_own_or_as_coach_only(app):
    a, b, coach = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu"), Client(app, "coach@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    p1 = _say(a, chan, "mine")
    p2 = _say(a, chan, "also mine")
    assert b.delete(f"/forge/api/posts/{p1['id']}").status_code == 403
    assert a.delete(f"/forge/api/posts/{p1['id']}").status_code == 200
    assert coach.delete(f"/forge/api/posts/{p2['id']}").status_code == 200
    posts = b.get(f"/forge/api/channels/{chan}/posts").json["posts"]
    assert all(p["deleted"] and p["body"] == "" for p in posts)
    with app.app_context():
        assert db.session.get(F.ForgePost, p1["id"]).body == "mine"


# --- unread ---

def test_unread_badges_count_others_posts_until_read(app):
    a, coach = Client(app, "a@lmu.edu"), Client(app, "coach@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    _say(a, chan, "my own post")
    _say(coach, chan, "looked good")
    _say(coach, chan, "check the 2:10 rep")

    def badge(client):
        return {ch["id"]: ch["unread"] for ch in client.get("/forge/api/channels").json["channels"]}[chan]

    assert badge(a) == 2
    assert badge(coach) == 0
    assert a.post(f"/forge/api/channels/{chan}/read").status_code == 200
    assert badge(a) == 0


# --- season filter ---

def test_season_filter_keeps_threads_together(app):
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    old = _say(a, chan, "last winter")
    _say(a, chan, "late reply", parent=old["id"])
    _say(a, chan, "this winter")
    with app.app_context():
        db.session.get(F.ForgePost, old["id"]).created_at = datetime(2025, 12, 1)
        db.session.commit()
    this = a.get(f"/forge/api/channels/{chan}/posts?season={a.cfg['season']}").json
    assert [p["body"] for p in this["posts"]] == ["this winter"]
    last = a.get(f"/forge/api/channels/{chan}/posts?season=2025/2026").json
    assert [p["body"] for p in last["posts"]] == ["last winter", "late reply"]
    assert "2025/2026" in this["channel"]["seasons"]


# --- uploads ---

def test_uploads_disabled_without_bucket(app):
    a = Client(app, "a@lmu.edu")
    assert a.cfg["uploads_enabled"] is False
    r = a.post(f"/forge/api/channels/{_chan(app, 'a@lmu.edu')}/uploads",
               {"name": "pen.mov", "size": 1000})
    assert r.status_code == 503


def test_only_channel_owner_or_coach_can_upload(app, s3):
    a, b, coach = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu"), Client(app, "coach@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    body = {"name": "pen.mov", "size": 1000, "duration": 60}
    assert b.post(f"/forge/api/channels/{chan}/uploads", body).status_code == 403
    assert a.post(f"/forge/api/channels/{chan}/uploads", body).status_code == 201
    assert coach.post(f"/forge/api/channels/{chan}/uploads", body).status_code == 201
    assert b.get(f"/forge/api/channels/{chan}/posts").json["channel"]["can_upload"] is False
    assert a.get(f"/forge/api/channels/{chan}/posts").json["channel"]["can_upload"] is True


def test_upload_size_and_length_limits(app, s3):
    a = Client(app, "a@lmu.edu")
    url = f"/forge/api/channels/{_chan(app, 'a@lmu.edu')}/uploads"
    assert a.post(url, {"name": "x.mov", "size": F.MAX_UPLOAD_BYTES + 1}).status_code == 400
    assert a.post(url, {"name": "x.mov", "size": 1000,
                        "duration": F.MAX_DURATION_SEC + 120}).status_code == 400
    assert a.post(url, {"name": "x.mov", "size": 0}).status_code == 400


def test_upload_handshake_queues_video_and_posts_it(app, s3):
    a, b = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    size = S.PART_SIZE * 2 + 5
    start = a.post(f"/forge/api/channels/{chan}/uploads",
                   {"name": "IMG_0001.MOV", "size": size, "type": "video/quicktime",
                    "duration": 900}).json
    assert len(start["urls"]) == 3
    vid = start["video_id"]
    done_url = f"/forge/api/uploads/{vid}/complete"
    assert b.post(done_url, {"parts": []}).status_code == 404
    assert a.post(done_url, {"parts": [{"n": 1, "etag": "e1"}]}).status_code == 400
    parts = [{"n": n, "etag": f"e{n}"} for n in (1, 2, 3)]
    r = a.post(done_url, {"parts": parts, "note": "felt late at 2:31"})
    assert r.status_code == 201
    post = r.json["post"]
    assert post["video"]["status"] == "queued" and post["body"] == "felt late at 2:31"
    assert s3.completed == [(f"forge/{chan}/{vid}/original.mov", parts)]
    assert a.post(done_url, {"parts": parts}).status_code == 404


def test_abort_cancels_upload(app, s3):
    a = Client(app, "a@lmu.edu")
    vid = a.post(f"/forge/api/channels/{_chan(app, 'a@lmu.edu')}/uploads",
                 {"name": "x.mp4", "size": 10}).json["video_id"]
    assert a.post(f"/forge/api/uploads/{vid}/abort").status_code == 200
    assert s3.aborted == [f"forge/{_chan(app, 'a@lmu.edu')}/{vid}/original.mp4"]
    with app.app_context():
        assert db.session.get(F.ForgeVideo, vid).status == "failed"


def _ready_video(app, s3, client, chan):
    vid = client.post(f"/forge/api/channels/{chan}/uploads",
                      {"name": "x.mp4", "size": 10}).json["video_id"]
    post = client.post(f"/forge/api/uploads/{vid}/complete",
                       {"parts": [{"n": 1, "etag": "e"}]}).json["post"]
    return vid, post


def test_play_redirects_only_when_ready_and_not_deleted(app, s3):
    a, b = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    vid, post = _ready_video(app, s3, a, chan)
    assert b.get(f"/forge/video/{vid}/play").status_code == 404
    with app.app_context():
        F.set_video(db.session.get(F.ForgeVideo, vid), status="ready",
                    playback_key="k/720p.mp4", thumb_key="k/thumb.jpg")
    r = b.get(f"/forge/video/{vid}/play")
    assert r.status_code == 302 and r.headers["Location"] == "https://signed/k/720p.mp4"
    assert b.get(f"/forge/video/{vid}/thumb").headers["Location"] == "https://signed/k/thumb.jpg"
    a.delete(f"/forge/api/posts/{post['id']}")
    assert b.get(f"/forge/video/{vid}/play").status_code == 404


def test_polling_reports_video_status_changes(app, s3):
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    vid, post = _ready_video(app, s3, a, chan)
    with app.app_context():
        F.set_video(db.session.get(F.ForgeVideo, vid), status="ready")
    d = a.get(f"/forge/api/channels/{chan}/posts?after={post['id']}&videos={vid},999").json
    assert d["posts"] == [] and d["videos"][str(vid)]["status"] == "ready"


# --- transcode worker ---

def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _queued_from_file(app, s3, client, chan, path, name):
    vid, _ = _ready_video(app, s3, client, chan)
    with app.app_context():
        v = db.session.get(F.ForgeVideo, vid)
        key = S.original_key(chan, vid, name)
        F.set_video(v, original_key=key)
    s3.objects[key] = path
    return vid, key


def test_transcode_makes_720p_portrait_safe_copy_and_drops_original(app, s3, tmp_path):
    from app.forge import transcode
    src = str(tmp_path / "pen.mp4")
    subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=1080x1920:rate=30:duration=3", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", "-shortest", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", src], check=True)
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    vid, key = _queued_from_file(app, s3, a, chan, src, "pen.mp4")
    with app.app_context():
        assert transcode.run_once() == 1
        v = db.session.get(F.ForgeVideo, vid)
        assert v.status == "ready", v.error
        assert (v.width, v.height) == (720, 1280)
        assert 2.5 < v.duration_sec < 3.5
        assert v.playback_key == f"forge/{chan}/{vid}/720p.mp4"
    assert S.playback_key(chan, vid) in s3.objects and S.thumb_key(chan, vid) in s3.objects
    assert s3.deleted == [key]


def test_transcode_marks_non_video_failed(app, s3, tmp_path):
    from app.forge import transcode
    junk = tmp_path / "notes.mov"
    junk.write_bytes(b"not a video at all")
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    vid, key = _queued_from_file(app, s3, a, chan, str(junk), "notes.mov")
    with app.app_context():
        transcode.run_once()
        v = db.session.get(F.ForgeVideo, vid)
        assert v.status == "failed" and v.error == "not a video file"
    assert s3.deleted == []


def test_stale_uploads_expire_and_interrupted_requeue(app, s3):
    from app.forge import transcode
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    stale = a.post(f"/forge/api/channels/{chan}/uploads", {"name": "x.mp4", "size": 10}).json["video_id"]
    with app.app_context():
        v = db.session.get(F.ForgeVideo, stale)
        F.set_video(v, created_at=F._now() - timedelta(hours=F.STALE_UPLOAD_HOURS + 1))
        stuck = F.ForgeVideo(channel_id=chan, uploader_id=chan, status="processing")
        db.session.add(stuck)
        db.session.commit()
        assert transcode.expire_stale_uploads() == 1
        assert db.session.get(F.ForgeVideo, stale).status == "failed"
        assert transcode.reset_interrupted() == 1
        assert db.session.get(F.ForgeVideo, stuck.id).status == "queued"


# --- coach-only test channel ---

def _sandbox_id(app):
    with app.app_context():
        return F.sandbox_channel().id


def test_test_channel_is_coach_only(app, s3):
    coach, a = Client(app, "coach@lmu.edu"), Client(app, "a@lmu.edu")
    sid = _sandbox_id(app)
    assert F.SANDBOX_NAME not in [ch["name"] for ch in a.get("/forge/api/channels").json["channels"]]
    assert a.get(f"/forge/api/channels/{sid}/posts").status_code == 404
    assert a.post(f"/forge/api/channels/{sid}/posts", {"body": "hi"}).status_code == 404
    first = coach.get("/forge/api/channels").json["channels"][0]
    assert first["id"] == sid and first["sandbox"] and first["joined"]
    _say(coach, sid, "testing an upload")
    body = {"name": "pen.mov", "size": 1000, "duration": 60}
    assert coach.post(f"/forge/api/channels/{sid}/uploads", body).status_code == 201


def test_test_channel_video_hidden_from_players(app, s3):
    coach, a = Client(app, "coach@lmu.edu"), Client(app, "a@lmu.edu")
    vid, _ = _ready_video(app, s3, coach, _sandbox_id(app))
    with app.app_context():
        F.set_video(db.session.get(F.ForgeVideo, vid), status="ready", playback_key="k/720p.mp4")
    assert coach.get(f"/forge/video/{vid}/play").status_code == 302
    assert a.get(f"/forge/video/{vid}/play").status_code == 404


def test_test_channel_not_in_unread_badges_for_players(app):
    coach, a = Client(app, "coach@lmu.edu"), Client(app, "a@lmu.edu")
    _say(coach, _sandbox_id(app), "only coaches see this")
    assert all(ch["unread"] == 0 for ch in a.get("/forge/api/channels").json["channels"])


# --- remove audio ---

def test_ensure_columns_adds_strip_audio_to_existing_table_with_rows(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.db").replace("\\", "/"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE forge_videos (id INTEGER PRIMARY KEY, status VARCHAR(16))"))
        conn.execute(text("INSERT INTO forge_videos (id, status) VALUES (7, 'ready')"))
    F.ensure_columns(engine)
    F.ensure_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("forge_videos")}
    assert "strip_audio" in cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id, status, strip_audio FROM forge_videos")).all() == [
            (7, "ready", 0)]
    engine.dispose()


def test_upload_records_remove_audio_choice(app, s3):
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    url = f"/forge/api/channels/{chan}/uploads"
    muted = a.post(url, {"name": "x.mov", "size": 10, "strip_audio": True}).json["video_id"]
    loud = a.post(url, {"name": "y.mov", "size": 10}).json["video_id"]
    with app.app_context():
        assert db.session.get(F.ForgeVideo, muted).to_dict()["muted"] is True
        assert db.session.get(F.ForgeVideo, loud).to_dict()["muted"] is False


@pytest.mark.parametrize("strip", [True, False])
def test_transcode_drops_audio_only_when_asked(app, s3, tmp_path, strip):
    from app.forge import transcode
    src = str(tmp_path / "pen.mp4")
    subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=640x360:rate=30:duration=2", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", src], check=True)
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    vid, _ = _queued_from_file(app, s3, a, chan, src, "pen.mp4")
    with app.app_context():
        F.set_video(db.session.get(F.ForgeVideo, vid), strip_audio=strip)
        transcode.run_once()
        assert db.session.get(F.ForgeVideo, vid).status == "ready"
    out = subprocess.run([_ffmpeg(), "-hide_banner", "-i", s3.objects[S.playback_key(chan, vid)]],
                         capture_output=True, text=True).stderr
    assert ("Audio:" in out) is (not strip)


# --- position player / pitcher / both, picked at sign-up ---

def _signup(app, monkeypatch, name, email, player_type):
    for var in ("PAW_TEAM_CODE", "PAW_COACH_CODE", "PAW_COACH_EMAILS"):
        monkeypatch.delenv(var, raising=False)
    c = app.test_client()
    c.post("/register", data={"name": name, "email": email, "password": "password123",
                              "confirm": "password123", "team_code": "",
                              "player_type": player_type})
    return c


def test_pitcher_signup_gets_a_channel_under_their_account_name(app, monkeypatch, s3):
    _signup(app, monkeypatch, "Big Jake", "jake@lmu.edu", "both")
    j = Client(app, "jake@lmu.edu")
    mine = [ch for ch in j.get("/forge/api/channels").json["channels"] if ch["mine"]]
    assert [ch["name"] for ch in mine] == ["Big Jake"]
    assert j.post(f"/forge/api/channels/{mine[0]['id']}/uploads",
                  {"name": "pen.mov", "size": 1000, "duration": 60}).status_code == 201
    names = [ch["name"] for ch in Client(app, "coach@lmu.edu").get("/forge/api/channels").json["channels"]]
    assert "Big Jake" in names


def test_position_player_signup_gets_no_channel(app, monkeypatch):
    _signup(app, monkeypatch, "Cam Hitter", "cam@lmu.edu", "position")
    with app.app_context():
        u = User.query.filter_by(email="cam@lmu.edu").one()
        assert u.player_type == "position" and F.channel_of(u) is None


def _legacy(app, email, name):
    with app.app_context():
        u = User(email=email, name=name, role="player")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        return u.id


def test_linked_legacy_account_is_tagged_pitcher_and_channel_shows_account_name(app):
    uid = _legacy(app, "will@lmu.edu", "Will")
    with app.app_context():
        db.session.add(F.ForgeChannel(name_key="kaczynski will", name="Will Kaczynski", user_id=uid))
        db.session.commit()
        chans = {c.user_id: c.name for c in F.sync_channels()}
        assert chans[uid] == "Will"
        assert db.session.get(User, uid).player_type == "pitcher"


def test_unlinked_roster_channel_from_before_is_hidden_not_deleted(app):
    with app.app_context():
        db.session.add(F.ForgeChannel(name_key="newcomb jake", name="Jake Newcomb"))
        db.session.commit()
        assert "Jake Newcomb" not in [c.name for c in F.sync_channels()]
        assert F.ForgeChannel.query.filter_by(name="Jake Newcomb").count() == 1


def test_legacy_unlinked_account_is_asked_on_the_forge_once(app):
    _legacy(app, "old@lmu.edu", "Old Timer")
    o = Client(app, "old@lmu.edu")
    assert o.cfg["ask_player_type"] is True
    assert Client(app, "a@lmu.edu").cfg["ask_player_type"] is False
    assert Client(app, "h@lmu.edu").cfg["ask_player_type"] is False
    assert Client(app, "coach@lmu.edu").cfg["ask_player_type"] is False
    r = o.post("/forge/api/player-type", {"player_type": "pitcher"})
    chan = r.json["channel_id"]
    assert chan and chan == _chan(app, "old@lmu.edu")
    assert Client(app, "old@lmu.edu").cfg["ask_player_type"] is False
    again = o.post("/forge/api/player-type", {"player_type": "position"})
    assert again.status_code == 400 and "already has an answer" in again.json["error"]


def test_set_player_type_cli_moves_a_player_on_and_off_the_list(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["set-player-type", "--email", "h@lmu.edu", "--type", "pitcher"])
    assert r.exit_code == 0, r.output
    with app.app_context():
        assert HITTER in [c.name for c in F.sync_channels()]
    runner.invoke(args=["set-player-type", "--email", "h@lmu.edu", "--type", "position"])
    with app.app_context():
        assert HITTER not in [c.name for c in F.sync_channels()]


def test_ensure_columns_adds_player_type_and_edited_at_to_tables_with_rows(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.auth.models import ensure_columns as ensure_user_columns
    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.db").replace("\\", "/"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(255))"))
        conn.execute(text("INSERT INTO users (id, name) VALUES (3, 'Old Account')"))
        conn.execute(text("CREATE TABLE forge_posts (id INTEGER PRIMARY KEY, body TEXT)"))
        conn.execute(text("INSERT INTO forge_posts (id, body) VALUES (9, 'hi')"))
    for _ in range(2):
        ensure_user_columns(engine)
        F.ensure_columns(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id, name, player_type FROM users")).all() == [
            (3, "Old Account", None)]
        assert conn.execute(text("SELECT id, body, edited_at FROM forge_posts")).all() == [
            (9, "hi", None)]
    assert "player_type" in {c["name"] for c in inspect(engine).get_columns("users")}
    engine.dispose()


# --- editing your own message ---

def test_author_edits_own_message_and_others_see_it_on_next_poll(app):
    a, b = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    p = _say(a, chan, "typo heer")
    first = b.get(f"/forge/api/channels/{chan}/posts").json
    assert first["posts"][0]["can_edit"] is False
    assert first["posts"][0]["edited"] is False
    r = a.patch(f"/forge/api/posts/{p['id']}", {"body": "typo here"})
    assert r.status_code == 200 and r.json["post"]["edited"] is True
    poll = b.get(f"/forge/api/channels/{chan}/posts?after={p['id']}&since={first['now']}").json
    assert [(x["id"], x["body"], x["edited"]) for x in poll["posts"]] == [(p["id"], "typo here", True)]
    quiet = b.get(f"/forge/api/channels/{chan}/posts?after={p['id']}&since={poll['now']}").json
    assert quiet["posts"] == []


def test_only_the_author_can_edit_not_even_a_coach(app):
    a, b, coach = Client(app, "a@lmu.edu"), Client(app, "b@lmu.edu"), Client(app, "coach@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    p = _say(a, chan, "mine")
    c = _say(coach, chan, "coach note")
    assert b.patch(f"/forge/api/posts/{p['id']}", {"body": "hacked"}).status_code == 403
    assert coach.patch(f"/forge/api/posts/{p['id']}", {"body": "hacked"}).status_code == 403
    assert coach.patch(f"/forge/api/posts/{c['id']}", {"body": "coach note, fixed"}).status_code == 200
    with app.app_context():
        assert db.session.get(F.ForgePost, p["id"]).body == "mine"


def test_edit_rejects_empty_text_and_deleted_posts(app):
    a = Client(app, "a@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    p = _say(a, chan, "keep me")
    assert a.patch(f"/forge/api/posts/{p['id']}", {"body": "   "}).status_code == 400
    a.delete(f"/forge/api/posts/{p['id']}")
    assert a.patch(f"/forge/api/posts/{p['id']}", {"body": "back"}).status_code == 404


def test_poll_picks_up_a_delete_by_someone_else(app):
    a, coach = Client(app, "a@lmu.edu"), Client(app, "coach@lmu.edu")
    chan = _chan(app, "a@lmu.edu")
    p = _say(a, chan, "remove me")
    first = a.get(f"/forge/api/channels/{chan}/posts").json
    coach.delete(f"/forge/api/posts/{p['id']}")
    poll = a.get(f"/forge/api/channels/{chan}/posts?after={p['id']}&since={first['now']}").json
    assert [x["deleted"] for x in poll["posts"]] == [True]
