"""Academic-year season helpers."""
from datetime import date

import pandas as pd

from app.data import cache
from app.data import seasons as S


def test_season_math():
    assert S.season_bounds("2025/2026") == ("2025-08-01", "2026-07-31")
    assert S.season_label_for("2025-11-22") == "2025/2026"   # Nov -> that Aug-Jul year
    assert S.season_label_for("2026-05-16") == "2025/2026"   # May -> prior Aug's year
    assert S.season_label_for("2026-08-01") == "2026/2027"   # Aug -> new academic year
    assert S.season_label_for("2026-07-31") == "2025/2026"   # Jul 31 still prior year


def test_available_and_current_live():
    seasons = S.available_seasons()
    assert seasons == sorted(seasons, reverse=True)           # newest first
    assert all(len(s) == 9 and s[4] == "/" for s in seasons)  # 'YYYY/YYYY' labels
    # current_season() now always returns today's calendar academic-year label
    # (see test_current_season_now_always_todays_calendar_season), which
    # available_seasons() also always includes -- so current_season() is
    # always the newest entry in available_seasons().
    assert S.current_season() in seasons
    assert S.current_season() <= seasons[0]


def test_current_season_now_always_todays_calendar_season(monkeypatch):
    """current_season() now ALWAYS returns today's calendar academic-year
    label, regardless of what GAMES contains -- the roster-placeholder union
    (app.data.lmu_roster) means the season view is no longer blank just
    because GAMES has zero rows for it yet, so the old "only fall back if
    GAMES is entirely empty" guard is no longer needed."""
    cache.clear_all()
    monkeypatch.setattr(S, "query_df", lambda sql, params=None:
                         pd.DataFrame({"Date": ["2024-11-01"]}))  # GAMES has OLDER data only
    try:
        assert S.current_season() == S.season_label_for(date.today().isoformat())
        assert S.current_season() != "2024/2025"
    finally:
        cache.clear_all()


def test_available_seasons_always_includes_current_calendar_season(monkeypatch):
    """Even with zero GAMES rows for the current academic year, available_seasons()
    must still include today's calendar season label. Without this, the Season
    dropdown has a hard ceiling: once the last labeled season ends, no later
    season is ever selectable until a GAMES row for it exists."""
    cache.clear_all()
    monkeypatch.setattr(S, "query_df", lambda sql, params=None: pd.DataFrame({"Date": []}))
    try:
        seasons = S.available_seasons()
        assert S.season_label_for(date.today().isoformat()) in seasons
    finally:
        cache.clear_all()
