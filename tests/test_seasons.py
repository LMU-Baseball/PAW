"""Academic-year season helpers."""
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
    assert S.current_season() == seasons[0]                   # latest season with data
