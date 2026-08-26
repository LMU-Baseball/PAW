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
    # current_season() stays GAMES-data-driven (deliberately NOT today's calendar
    # season unless GAMES actually has rows for it) while available_seasons() now
    # always additionally includes today's calendar season label -- so current_season()
    # is always ONE of the available options, but not necessarily the newest-sorted
    # one anymore (today's label can be newer than the latest season with real data).
    assert S.current_season() in seasons
    assert S.current_season() <= seasons[0]


def test_current_season_stays_games_driven_not_todays_calendar_season(monkeypatch):
    """Regression guard for the _games_seasons() split: current_season() must
    return the latest season WITH REAL GAMES DATA, never today's calendar
    season just because available_seasons() now always includes it.

    Mocks GAMES to have rows for an older season ("2024/2025") only -- today's
    real calendar season (whatever date.today() actually is) has zero GAMES
    rows here, matching live reality until real Fall-2026 games are played.
    This must FAIL against the old `current_season() == available_seasons()[0]`
    implementation: since available_seasons() always includes today's label and
    it always sorts newest, that old implementation would incorrectly return
    today's label instead of the older GAMES-backed season."""
    cache.clear_all()
    monkeypatch.setattr(S, "query_df", lambda sql, params=None:
                         pd.DataFrame({"Date": ["2024-11-01"]}))
    try:
        assert S.current_season() == "2024/2025"
        assert S.current_season() != S.season_label_for(date.today().isoformat())
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
