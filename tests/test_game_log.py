"""Hitting Game Log: pure transforms on a synthetic pitch frame (no live DB),
plus app mounting / hub card."""
import pandas as pd
import pytest

from app import create_app
from app.data import game_log
from config import Config


def _p(no, inning, half, pa, pip, batter, call, *, korbb="Undefined", play="Undefined",
       hit=None, side=0.0, height=2.5, ev=None, la=None, dist=None, bearing=None,
       balls=0, strikes=0):
    return {"PitchUID": f"u{no}", "PitchNo": no, "Inning": inning, "half": half, "Outs": 0,
            "Balls": balls, "Strikes": strikes, "PAofInning": pa, "PitchofPA": pip,
            "Batter": batter, "BatterId": 1, "BatterSide": "Right", "Pitcher": "Arm, Big",
            "PitcherThrows": "Right", "TaggedPitchType": "Fastball", "PitchCall": call,
            "KorBB": korbb, "TaggedHitType": hit, "PlayResult": play, "RunsScored": 0,
            "OutsOnPlay": 0, "RelSpeed": 90.04, "SpinRate": 2200, "InducedVertBreak": 16.0,
            "HorzBreak": 8.0, "VertApprAngle": -5.0, "PlateLocSide": side,
            "PlateLocHeight": height, "ExitSpeed": ev, "Angle": la, "Distance": dist,
            "Bearing": bearing, "HangTime": None, "GameID": "G1"}


def _raw():
    return pd.DataFrame([
        # PA 1 (Top 1): chase whiff, then a line-drive double
        _p(1, 1, "Top", 1, 1, "Doe, Jon", "StrikeSwinging", side=1.6, height=0.8),
        _p(2, 1, "Top", 1, 2, "Doe, Jon", "InPlay", hit="LineDrive", play="Double",
           ev=101.0, la=14, dist=280, bearing=10, strikes=1),
        # PA 2 (Top 1): called-strike strikeout
        _p(3, 1, "Top", 2, 1, "Roe, Ann", "StrikeCalled", korbb="Strikeout", strikes=2),
        # Bottom 1, same PAofInning=1 as above -- must stay a separate PA
        _p(4, 1, "Bottom", 1, 1, "Poe, Al", "BallCalled", korbb="Walk", side=2.0, balls=3),
    ])


def test_label_pitches_pa_keys_codes_and_flags():
    df = game_log.label_pitches(_raw())
    assert df["pa_seq"].tolist() == [1, 1, 2, 3]
    assert df["is_pa_end"].tolist() == [False, True, True, True]
    assert df["PA"].tolist() == ["", "LD-2B", "K-Look", "BB"]
    assert df["Result"].tolist() == ["Swing & Miss", "LD-2B", "K-Look", "BB"]
    assert df["is_chase"].tolist() == [True, False, False, False]
    assert df["is_barrel"].tolist() == [False, True, False, False]   # 101 mph at 14 deg
    assert df["decision"].tolist()[:2] == ["Chase", "Heart swing"]
    assert df["InnLabel"].tolist() == ["1▲", "1▲", "1▲", "1▼"]
    assert df["Velo"].iloc[0] == 90.0


def test_pa_result_codes():
    assert game_log.pa_result({"KorBB": "Strikeout", "PitchCall": "StrikeSwinging"}) == "K-Swing"
    assert game_log.pa_result({"PitchCall": "HitByPitch"}) == "HBP"
    assert game_log.pa_result({"PitchCall": "InPlay", "TaggedHitType": "GroundBall",
                               "PlayResult": "Out"}) == "GB-OUT"
    assert game_log.pa_result({"PitchCall": "InPlay", "TaggedHitType": None,
                               "PlayResult": "Undefined"}) == "In Play"
    assert game_log.pa_result({"PitchCall": "BallCalled"}) == ""


def test_filter_pitches_show_only_is_and():
    df = game_log.attach_video(game_log.label_pitches(_raw()), {"u2": {"HomeRight": "/v"}})
    assert len(game_log.filter_pitches(df, show_only=["swing"])) == 2
    assert game_log.filter_pitches(df, show_only=["swing", "bip"])["PitchUID"].tolist() == ["u2"]
    assert game_log.filter_pitches(df, show_only=["video"])["PitchUID"].tolist() == ["u2"]
    assert game_log.filter_pitches(df, batter="Roe, Ann")["PitchUID"].tolist() == ["u3"]
    assert len(game_log.filter_pitches(df, innings=[2])) == 0


def test_attach_video_url_columns():
    df = game_log.attach_video(game_log.label_pitches(_raw()), {"u2": {"HomeRight": "/v"}})
    assert df.loc[df["PitchUID"] == "u2", "url_homeright"].iloc[0] == "/v"
    assert df["Vid"].tolist() == ["", "🎥", "", ""]
    assert df["batter_side"].tolist() == ["Right"] * 4


def test_summary_and_batter_line():
    df = game_log.label_pitches(_raw())
    s = game_log.summary(df)
    assert (s["PA"], s["H"], s["XBH"], s["BB"], s["K"]) == ("3", "1", "1", "1", "1")
    assert s["QAB%"] == "67%"           # double + walk
    assert s["Chase%"] == "50%"         # 1 swing of 2 out-of-zone pitches
    assert s["Whiff%"] == "50%"
    assert game_log.batter_line(df, "Doe, Jon") == "1-for-1 · LD-2B"
    assert game_log.batter_line(df, "Poe, Al") == "0-for-0 · BB"


def test_game_pitches_picks_up_newly_uploaded_angles(monkeypatch):
    from app.data import cache
    cache.clear_all()
    monkeypatch.setattr(game_log, "query_df", lambda *a, **k: _raw())
    uploaded = {"u2": {"HomeBehind": "/b"}}
    monkeypatch.setattr(game_log.videodata, "clip_urls", lambda uids: uploaded)
    assert game_log.game_pitches("G1").loc[1, "url_broadcast"] is None
    uploaded["u2"]["Broadcast"] = "/cf"
    assert game_log.game_pitches("G1").loc[1, "url_broadcast"] == "/cf"
    cache.clear_all()


def test_game_pitches_without_video_skips_the_url_lookup(monkeypatch):
    from app.data import cache
    cache.clear_all()
    monkeypatch.setattr(game_log, "query_df", lambda *a, **k: _raw())

    def boom(uids):
        raise AssertionError("clip_urls should not run")
    monkeypatch.setattr(game_log.videodata, "clip_urls", boom)
    df = game_log.game_pitches("G1", with_video=False)
    assert len(df) == len(_raw()) and "url_broadcast" not in df
    cache.clear_all()


def test_zone13_grid_and_chase_corners():
    assert game_log.zone13(0.6, 3.3) == 1        # top row, +side
    assert game_log.zone13(0.0, 2.5) == 5
    assert game_log.zone13(-0.6, 1.7) == 9
    assert game_log.zone13(1.5, 3.0) == 10       # out of zone: up, +side
    assert game_log.zone13(-1.5, 3.0) == 11
    assert game_log.zone13(1.5, 1.0) == 12
    assert game_log.zone13(-0.2, 0.5) == 13
    assert game_log.zone13(None, 2.0) is None


def test_zone_words_follow_the_hitter():
    # +PlateLocSide is away from a righty, in on a lefty
    assert game_log.zone_word(1, "Right") == "Up & Away"
    assert game_log.zone_word(1, "Left") == "Up & In"
    assert game_log.zone_word(5, "Right") == "Middle"
    assert game_log.zone_word(8, "Left") == "Down"
    assert game_log.zone_word(6, "Right") == "In"
    assert game_log.zone_word(10, "Right") == "Chase Up & Away"
    assert game_log.zone_word(13, "Right") == "Chase Down & In"
    assert game_log.zone_word(None, "Right") == ""
    assert {game_log.zone_word(z, s) for z in range(1, 14) for s in ("Right", "Left")}         == set(game_log.ZONE_WORDS)


def test_filter_by_zone_words():
    df = game_log.label_pitches(_raw())
    assert df["Z"].tolist() == [12, 5, 5, 10]
    assert df["ZoneWord"].tolist() == ["Chase Down & Away", "Middle", "Middle", "Chase Up & Away"]
    assert game_log.filter_pitches(df, zones=["Middle"])["PitchUID"].tolist() == ["u2", "u3"]


def test_empty_frames_are_safe():
    assert game_log.label_pitches(pd.DataFrame()).empty
    assert game_log.summary(None)["PA"] == "—"


def test_play_detail_and_log_render():
    from app.dashboards.game_log import layout, tables
    df = game_log.attach_video(game_log.label_pitches(_raw()), {})
    assert layout.EMPTY_DETAIL in str(layout.play_detail(df, None))
    out = str(layout.play_detail(df, "u3"))
    assert "K-Look" in out and "Roe, Ann" in out
    log = tables.pitch_log(df)
    assert log.id == tables.TABLE_ID and len(log.data) == 4
    assert {"url_homeright", "batter_side", "pitcher_side", "PitchUID"} <= set(log.data[0])
    assert [c["id"] for c in log.columns][-1] == "Z"


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_game_log_route_requires_login(server):
    assert any(r.rule.startswith("/dash/game-log/") for r in server.url_map.iter_rules())
    rv = server.test_client().get("/dash/game-log/")
    assert rv.status_code == 302 and "/login" in rv.headers.get("Location", "")


def test_hitting_hub_has_game_log_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="glhub@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    client = server.test_client()
    client.post("/login", data={"email": "glhub@lmu.edu", "password": "x"})
    body = client.get("/hitting").get_data(as_text=True)
    assert "Game Log" in body and "/dash/game-log/" in body
