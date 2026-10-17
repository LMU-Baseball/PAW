"""Pitching Game Log: pure transforms on a synthetic pitch frame (no live DB),
plus app mounting / hub card."""
import pandas as pd
import pytest

from app import create_app
from app.data import game_log, pitcher_game_log as pgl
from config import Config


def _p(no, inning, half, pa, pip, batter, pitcher, call, *, ptype="Fastball", korbb="Undefined",
       play="Undefined", outs_on_play=0, ev=None, side=0.0, height=2.5, balls=0, strikes=0,
       hb=8.0, ivb=16.0, velo=90.0):
    return {"PitchUID": f"u{no}", "PitchNo": no, "Inning": inning, "half": half, "Outs": 0,
            "Balls": balls, "Strikes": strikes, "PAofInning": pa, "PitchofPA": pip,
            "Batter": batter, "BatterId": 1, "BatterSide": "Right", "Pitcher": pitcher,
            "PitcherThrows": "Right", "TaggedPitchType": ptype, "PitchCall": call,
            "KorBB": korbb, "TaggedHitType": "GroundBall" if call == "InPlay" else None,
            "PlayResult": play, "RunsScored": 0, "OutsOnPlay": outs_on_play, "RelSpeed": velo,
            "SpinRate": 2200.4, "InducedVertBreak": ivb, "HorzBreak": hb, "VertApprAngle": -5.0,
            "PlateLocSide": side, "PlateLocHeight": height, "ExitSpeed": ev, "Angle": None,
            "Distance": None, "Bearing": None, "HangTime": None, "GameID": "G1",
            "RelSide": -1.8, "RelHeight": 5.9, "Extension": 6.2}


def _df():
    raw = pd.DataFrame([
        # Top 1, Arm: called strike, swinging K on 0-1... (2-pitch strikeout for the test)
        _p(1, 1, "Top", 1, 1, "Doe, Jon", "Arm, Big", "StrikeCalled"),
        _p(2, 1, "Top", 1, 2, "Doe, Jon", "Arm, Big", "StrikeSwinging", korbb="Strikeout",
           ptype="Slider", hb=-4.0, ivb=2.0, velo=82.0, strikes=2),
        # Top 1, Arm: first-pitch ground out
        _p(3, 1, "Top", 2, 1, "Roe, Ann", "Arm, Big", "InPlay", play="Out", outs_on_play=1, ev=88.0),
        # Bottom 1 (intrasquad), same PAofInning -- a different pitcher, must stay separate
        _p(4, 1, "Bottom", 1, 1, "Poe, Al", "Lefty, Lou", "BallCalled", side=2.0),
        _p(5, 1, "Bottom", 1, 2, "Poe, Al", "Lefty, Lou", "InPlay", play="Single", ev=101.0,
           balls=1),
    ])
    df = game_log.label_pitches(raw)
    df["is_strike"] = ~df["PitchCall"].isin(pgl._BALL_CALLS)
    df["is_ball"] = df["PitchCall"].isin(pgl._BALL_CALLS)
    df["is_first"] = df["PitchofPA"] == 1
    df["Spin"], df["IVB"], df["HB"] = 2200, df["InducedVertBreak"], df["HorzBreak"]
    return game_log.attach_video(df, {"u2": {"Broadcast": "/cf"}})


def test_summary_uses_coaches_kpis():
    s = pgl.summary(_df()[lambda d: d["Pitcher"] == "Arm, Big"])
    assert (s["IP"], s["P"], s["BF"], s["K"], s["BB"], s["H"]) == ("0.2", "3", "2", "1", "0", "0")
    assert s["Strike%"] == "100%" and s["FPS%"] == "100%"
    assert s["E+A%"] == "100%"            # K on pitch 2 + first-pitch out
    assert s["Max Velo"] == "90.0"


def test_summary_keeps_intrasquad_halves_apart():
    s = pgl.summary(_df())
    assert s["BF"] == "3" and s["H"] == "1"


def test_pitcher_line_and_same_type():
    df = _df()
    assert pgl.pitcher_line(df, "Arm, Big").startswith("0.2 IP · 3 P · 1 K")
    assert pgl.same_type(df, "Arm, Big", "Fastball")["PitchUID"].tolist() == ["u1", "u3"]


def test_filter_strikes_balls_first_pitch():
    df = _df()
    assert pgl.filter_pitches(df, show_only=["ball"])["PitchUID"].tolist() == ["u4"]
    assert pgl.filter_pitches(df, show_only=["first", "strike"])["PitchUID"].tolist() == ["u1", "u3"]
    assert pgl.filter_pitches(df, pitcher="Lefty, Lou", show_only=["bip"])["PitchUID"].tolist() == ["u5"]
    assert pgl.filter_pitches(df, show_only=["video"])["PitchUID"].tolist() == ["u2"]


def test_empty_is_safe():
    assert pgl.summary(None)["IP"] == "—"


def test_detail_log_and_charts_render():
    from app.dashboards.pitcher_game_log import charts, layout, tables
    df = _df()
    assert layout.EMPTY_DETAIL in str(layout.play_detail(df, None))
    out = str(layout.play_detail(df, "u1"))
    assert "Arm, Big vs Doe, Jon" in out and "Extension" in out
    log = tables.pitch_log(df)
    assert log.id == tables.TABLE_ID and len(log.data) == 5
    assert {"pitcher_side", "url_broadcast", "Z"} <= set(log.data[0])
    same = pgl.same_type(df, "Arm, Big", "Fastball")
    mv = charts.movement_fig(same, "u1", "Fastball")
    assert any(getattr(t.marker, "symbol", None) == "star" for t in mv.data)
    rel = charts.release_fig(same, "u1", "Fastball")
    assert rel.layout.yaxis.scaleanchor == "x"


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_route_requires_login(server):
    assert any(r.rule.startswith("/dash/pitcher-game-log/") for r in server.url_map.iter_rules())
    rv = server.test_client().get("/dash/pitcher-game-log/")
    assert rv.status_code == 302 and "/login" in rv.headers.get("Location", "")


def test_pitching_hub_has_game_log_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="pglhub@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    client = server.test_client()
    client.post("/login", data={"email": "pglhub@lmu.edu", "password": "x"})
    body = client.get("/pitching").get_data(as_text=True)
    assert "Game Log" in body and "/dash/pitcher-game-log/" in body
