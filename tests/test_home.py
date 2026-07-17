"""Home/landing page: marquee hero + module cards, role-aware copy."""
import pytest

from app import create_app
from app.extensions import db
from app.auth.models import User
from config import Config


@pytest.fixture
def app_ctx(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    app = create_app(TestConfig)
    with app.app_context():
        for email, role, name in [("c@lmu.edu", "coach", "Coach C"),
                                   ("p@lmu.edu", "player", "Player P")]:
            u = User(email=email, name=name, role=role)
            u.set_password("x")
            db.session.add(u)
        db.session.commit()
    return app


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "x"},
                       follow_redirects=True)


def test_home_shows_hero_and_module_cards(app_ctx):
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    body = client.get("/").get_data(as_text=True)
    assert "THE PAW" in body                              # marquee
    assert "/static/brand/lions-arch.png" in body         # hero wordmark
    assert "/static/brand/palms.png" in body              # palms motif
    assert "/dash/hitting/" in body                       # Hitting module
    assert "/reports/pitching" in body                    # Pitching module
    assert "Coming soon" in body                          # Catching disabled
    assert "coach" in body                                # role copy


def test_home_player_sees_player_copy(app_ctx):
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    body = client.get("/").get_data(as_text=True)
    assert "player" in body
    assert "Player P" in body
