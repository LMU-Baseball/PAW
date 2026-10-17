"""Catching Game Log: pure transforms on a synthetic pitch frame (no live DB;
the called-strike model is stubbed), plus app mounting / hub card."""
import pandas as pd
import pytest

from app import create_app
from app.data import called_strike, catcher_game_log as cgl, game_log
from config import Config


def _p(no, pa, pip, call, *, side=0.0, height=2.5, play="Undefined", catcher="Lyall, Jake",
       pop=None, korbb="Undefined", balls=0, strikes=0):
    return {"PitchUID": f"u{no}", "PitchNo": no, "Inning": 1, "half": "Top", "Outs": 0,
            "Balls": balls, "Strikes": strikes, "PAofInning": pa, "PitchofPA": pip,
            "Batter": "Doe, Jon", "BatterId": 1, "BatterSide": "Right", "Pitcher": "Arm, Big",
            "PitcherThrows": "Right", "TaggedPitchType": "Fastball", "PitchCall": call,
            "KorBB": korbb, "TaggedHitType": None, "PlayResult": play, "RunsScored": 0,
            "OutsOnPlay": 0, "RelSpeed": 90.0, "SpinRate": 2200, "InducedVertBreak": 16.0,
            "HorzBreak": 8.0, "VertApprAngle": -5.0, "PlateLocSide": side,
            "PlateLocHeight": height, "ExitSpeed": None, "Angle": None, "Distance": None,
            "Bearing": None, "HangTime": None, "GameID": "G1", "Catcher": catcher,
            "CatcherId": 1, "PopTime": pop, "ExchangeTime": None, "ThrowSpeed": None}


@pytest.fixture
def df(monkeypatch):
    # stub model: 0.9 strike chance in the box, 0.1 outside
    monkeypatch.setattr(called_strike, "expected_called_strikes",
                        lambda d, lookup=None: pd.Series(
                            [0.9 if abs(s) <= 0.83 and 1.5 <= h <= 3.5 else 0.1
                             for s, h in zip(d["plate_loc_side"], d["plate_loc_height"])],
                            index=d.index))
    raw = pd.DataFrame([
        _p(1, 1, 1, "StrikeCalled", side=1.2, height=2.5),          # stolen (off the plate)
        _p(2, 1, 2, "BallCalled", side=0.0, height=2.5, strikes=1),  # lost (middle)
        _p(3, 1, 3, "StrikeSwinging", strikes=1, play="CaughtStealing", pop=1.98),
        _p(4, 1, 4, "BallinDirt", side=0.1, height=0.5, balls=1, strikes=2),
        _p(5, 2, 1, "StrikeCalled", catcher="Marucci, Luca"),        # correct call
    ])
    d = cgl.add_receiving(game_log.label_pitches(raw).assign(
        Catcher=lambda x: x["Catcher"]))
    return game_log.attach_video(d, {})


def test_framing_flags(df):
    assert df["Frame"].tolist() == ["Stolen", "Lost", "", "", ""]
    assert df["Steal"].tolist() == ["", "", "CS", "", ""]
    # a ball in the dirt isn't a take to the called-strike model, same as SLAA on the dashboard
    assert df["is_take_scored"].tolist() == [True, True, False, False, True]
    assert df["xK"].tolist() == ["10%", "90%", None, None, "90%"]
    assert round(df.loc[0, "strikes_added"], 2) == 0.9


def test_summary_receiving_and_throwing(df):
    s = cgl.summary(df[df["Catcher"] == "Lyall, Jake"])
    assert (s["P"], s["Taken"], s["Called K"], s["Stolen"], s["Lost"], s["Net"]) == \
        ("4", "2", "1", "1", "1", "+0")
    assert s["SLAA"] == "+0.0"           # 1 called strike vs 1.0 expected
    assert s["SL+"] == "—"               # too few takes for SL+
    assert (s["SB"], s["CS"], s["CS%"], s["Avg Pop"], s["Dirt"]) == ("0", "1", "100%", "1.98", "1")


def test_filters(df):
    assert cgl.filter_pitches(df, show_only=["stolen"])["PitchUID"].tolist() == ["u1"]
    assert cgl.filter_pitches(df, show_only=["steal"])["PitchUID"].tolist() == ["u3"]
    assert cgl.filter_pitches(df, catcher="Marucci, Luca")["PitchUID"].tolist() == ["u5"]
    assert cgl.filter_pitches(df, show_only=["take", "called_strike"])["PitchUID"].tolist() \
        == ["u1", "u5"]


def test_catcher_line(df):
    assert cgl.catcher_line(df, "Lyall, Jake") == "4 P · SLAA +0.0 · 1 stolen / 1 lost · 1 CS / 0 SB"


def test_detail_and_log_render(df):
    from app.dashboards.catcher_game_log import layout, tables
    assert layout.EMPTY_DETAIL in str(layout.play_detail(df, None))
    out = str(layout.play_detail(df, "u3"))
    assert "Caught stealing" in out and "Pop Time" in out
    assert "Stolen" in str(layout.play_detail(df, "u1"))
    log = tables.pitch_log(df)
    assert log.id == tables.TABLE_ID and len(log.data) == 5
    assert [c["id"] for c in log.columns][-1] == "Z"


def test_empty_is_safe():
    assert cgl.summary(None)["SLAA"] == "—"


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_route_requires_login(server):
    assert any(r.rule.startswith("/dash/catcher-game-log/") for r in server.url_map.iter_rules())
    rv = server.test_client().get("/dash/catcher-game-log/")
    assert rv.status_code == 302 and "/login" in rv.headers.get("Location", "")


def test_catching_hub_has_game_log_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="cglhub@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    client = server.test_client()
    client.post("/login", data={"email": "cglhub@lmu.edu", "password": "x"})
    body = client.get("/catching").get_data(as_text=True)
    assert "Game Log" in body and "/dash/catcher-game-log/" in body
