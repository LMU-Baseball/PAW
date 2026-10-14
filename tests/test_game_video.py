"""app.data.game_video (hand-cut game clips as DB BLOBs) + its /game-video
route. Mirrors test_bullpen_video_route.py: a sandboxed pitch_uid written to
the real table and deleted in `finally`."""
import pytest
from sqlalchemy import text

from app import create_app
from app.data import game_video as GV
from app.db import get_engine
from config import Config

TEST_UID = "test-game-video-uid-0000-0000-0000-000000000099"


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_clip_url_points_at_the_route():
    assert GV.clip_url("abc", "LHP") == "/game-video/abc?angle=LHP"


def test_add_clip_rejects_unknown_angle():
    with pytest.raises(ValueError):
        GV.add_clip(TEST_UID, "Dugout", b"x")


def test_game_video_route_requires_login_and_streams_bytes(server):
    from app.auth.models import User
    from app.extensions import db
    server.config["WTF_CSRF_ENABLED"] = False
    with server.app_context():
        u = User(email="gamevid@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    GV.add_clip(TEST_UID, "RHP", b"fake-game-video-bytes", width=1920, height=1080)
    try:
        assert GV.sizes_by_pitch_uid([TEST_UID]) == {(TEST_UID, "RHP"): 21}
        client = server.test_client()
        anon = client.get(f"/game-video/{TEST_UID}?angle=RHP")
        assert anon.status_code == 302 and "/login" in anon.headers.get("Location", "")

        client.post("/login", data={"email": "gamevid@lmu.edu", "password": "x"})
        rv = client.get(f"/game-video/{TEST_UID}?angle=RHP")
        assert rv.status_code == 200 and rv.data == b"fake-game-video-bytes"
        assert rv.mimetype == "video/mp4"
        assert client.get(f"/game-video/{TEST_UID}?angle=LHP").status_code == 404
        assert client.get(f"/game-video/{TEST_UID}?angle=Dugout").status_code == 404
    finally:
        with get_engine().begin() as conn:
            conn.execute(text(f"DELETE FROM {GV.TABLE} WHERE pitch_uid = :p"), {"p": TEST_UID})
