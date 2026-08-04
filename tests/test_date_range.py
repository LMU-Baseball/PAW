from datetime import date

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


def test_season_block_spring_and_fall():
    assert dr.season_block("2026-05-13") == (date(2026, 1, 1), date(2026, 5, 13))
    assert dr.season_block(date(2025, 11, 4)) == (date(2025, 7, 1), date(2025, 11, 4))
    # boundaries
    assert dr.season_block("2026-06-30")[0] == date(2026, 1, 1)
    assert dr.season_block("2026-07-01")[0] == date(2026, 7, 1)


def test_preset_range_windows():
    a = date(2026, 5, 13)
    assert dr.preset_range("season", a) == (date(2026, 1, 1), a)
    assert dr.preset_range("week", a) == (date(2026, 5, 6), a)
    assert dr.preset_range("month", a) == (date(2026, 4, 13), a)
    assert dr.preset_range("3months", a) == (date(2026, 2, 12), a)
    assert dr.preset_range("6months", a) == (date(2025, 11, 13), a)
    assert dr.preset_range("year", a) == (date(2025, 5, 13), a)
    assert dr.preset_range("custom", a) is None


def test_preset_options_shape_and_order():
    opts = dr.preset_options()
    assert opts[0] == {"label": "This Season", "value": "season"}
    assert opts[-1] == {"label": "Custom Range", "value": "custom"}
    assert {o["value"] for o in opts} == {"season", "week", "month", "3months",
                                          "6months", "year", "custom"}


def test_date_control_ids_and_hidden_calendar():
    comp = dr.date_control("pit", "2026-05-13")
    s = str(comp)
    assert "pit-date-preset" in s and "pit-daterange" in s and "pit-cal-wrap" in s
    # calendar hidden by default (season preset)
    assert "none" in s
