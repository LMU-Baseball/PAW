"""Unit tests for HitTrax practice transforms (synthetic — no DB)."""
import pandas as pd

from app.data import practice as P


def _pitches():
    return pd.DataFrame([
        {"player_name": "Doe, John", "session_id": 1, "result": -4,
         "px": 0.0, "py": 2.5, "exit_velocity": None, "distance_feet": None,
         "zone_section": 5, "play_timestamp": "2026-04-01 10:00:00",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": False},
        {"player_name": "Doe, John", "session_id": 1, "result": 1,
         "px": 0.1, "py": 2.4, "exit_velocity": 88.0, "distance_feet": 220.0,
         "zone_section": 5, "play_timestamp": "2026-04-01 10:00:05",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": True},
        {"player_name": "Doe, John", "session_id": 1, "result": -4,
         "px": 1.2, "py": 3.8, "exit_velocity": None, "distance_feet": None,
         "zone_section": 11, "play_timestamp": "2026-04-01 10:00:10",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": False},
        {"player_name": "Doe, John", "session_id": 1, "result": 2,
         "px": 1.1, "py": 3.7, "exit_velocity": 92.0, "distance_feet": 280.0,
         "zone_section": 11, "play_timestamp": "2026-04-01 10:00:15",
         "play_date": "2026-04-01", "session_type": 1, "session_tag": "BP",
         "session_display": "Hitting — BP", "is_contact": True},
    ])


def test_trim_to_first_contact_drops_leading_takes():
    d = P.trim_to_first_contact(_pitches())
    # First row is a take before first contact — dropped
    assert len(d) == 3
    assert d.iloc[0]["is_contact"]


def test_contact_summary():
    s = P.contact_summary(_pitches())
    assert s["pitches"] == 4
    assert s["contacts"] == 2
    assert s["contact_pct"] == 50.0


def test_swing_decision_score():
    s = P.swing_decision_score(_pitches())
    assert s["in_zone_pct"] is not None
    assert s["chase_pct"] is not None
    assert s["score"] == round(s["in_zone_pct"] - s["chase_pct"], 1)


def test_zone_contact_table():
    z = P.zone_contact_table(_pitches())
    assert set(z["Zone"]) >= {5, 11}
    assert {"Pitches", "Contacts", "Contact%"} <= set(z.columns)


def test_heatmap_shape():
    z, xe, ye = P.heatmap_contact_rate(_pitches(), bins=10)
    assert z.shape == (10, 10)
    assert len(xe) == 11 and len(ye) == 11


def test_apply_filters_player_and_session():
    d = _pitches()
    out = P.apply_filters(d, player="Doe, John", start=None, end=None,
                          session="Hitting — BP")
    assert len(out) == 4
    out2 = P.apply_filters(d, player="Nobody", start=None, end=None, session=None)
    assert out2.empty


def test_hit_type_counts():
    plays = pd.DataFrame({"hit_type": [0, 1, 2, 2, 3]})
    c = P.hit_type_counts(plays)
    assert "Line Drive" in set(c["Hit Type"])
