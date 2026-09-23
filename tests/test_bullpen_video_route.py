"""/bullpen-video/<play_id>: login-gated streaming route for downloaded
Edgertronic clips (see app.data.bullpen_video). Mirrors
test_splash_report_dash.py::test_splash_video_route_requires_login_and_streams_bytes's
shape for the sibling /splash-video/<id> route."""
import pytest

from app import create_app
from app.data import bullpen_video as BV
from config import Config

TEST_PLAY_ID = "test-route-play-aaaa1111-0000-0000-0000-000000000099"


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_bullpen_video_route_requires_login_and_streams_bytes(server):
    from app.auth.models import User
    from app.extensions import db
    server.config["WTF_CSRF_ENABLED"] = False
    with server.app_context():
        u = User(email="bullpenvid@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        BV.add_clip(TEST_PLAY_ID, "sess-1", b"fake-bullpen-video-bytes",
                   mimetype="video/mp4", duration_sec=0.8, width=1280,
                   height=1008, framerate=240)

    try:
        client = server.test_client()

        anon = client.get(f"/bullpen-video/{TEST_PLAY_ID}")
        assert anon.status_code == 302 and "/login" in anon.headers.get("Location", "")

        client.post("/login", data={"email": "bullpenvid@lmu.edu", "password": "x"})
        rv = client.get(f"/bullpen-video/{TEST_PLAY_ID}")
        assert rv.status_code == 200 and rv.data == b"fake-bullpen-video-bytes"
        assert rv.mimetype == "video/mp4"

        rv2 = client.get("/bullpen-video/no-such-play-id")
        assert rv2.status_code == 404
    finally:
        from sqlalchemy import text as _text

        from app.db import get_engine
        with get_engine().begin() as conn:
            conn.execute(_text(f"DELETE FROM {BV.TABLE} WHERE play_id = :p"),
                        {"p": TEST_PLAY_ID})
