import pandas as pd
from app.dashboards import date_range as dr


def _games():
    return pd.DataFrame([
        {"game_id": 10, "GameLabel": "2026-04-02 vs USD"},
        {"game_id": 9, "GameLabel": "2026-04-01 @ ASU"},
    ])


def test_game_options_prepends_sentinel():
    opts = dr.game_options(_games())
    assert opts[0]["value"] == dr.ALL_IN_RANGE
    assert opts[0]["label"] == "All games in range (2)"
    assert [o["value"] for o in opts[1:]] == [10, 9]


def test_game_options_empty():
    assert dr.game_options(pd.DataFrame()) == []


def test_range_scoreboard_text():
    assert dr.range_scoreboard_text(_games(), "2026-04-01", "2026-04-02") == \
        "2026-04-01 – 2026-04-02 · 2 games"
    assert dr.range_scoreboard_text(pd.DataFrame(), "2026-04-01", "2026-04-02") == \
        "2026-04-01 – 2026-04-02 · 0 games"
