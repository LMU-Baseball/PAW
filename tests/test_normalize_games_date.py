import pytest
from app.ingest.normalize_games_date import iso_date

@pytest.mark.parametrize("raw,expected", [
    ("2024-05-03", "2024-05-03"),   # already ISO -> unchanged
    ("5/3/24", "2024-05-03"),       # US m/d/yy
    ("5/3/2024", "2024-05-03"),     # US m/d/yyyy
    ("12/31/25", "2025-12-31"),
    ("2026-05-16", "2026-05-16"),
])
def test_iso_date_converts_known_formats(raw, expected):
    assert iso_date(raw) == expected

@pytest.mark.parametrize("raw", ["", "   ", None, "not-a-date"])
def test_iso_date_unparseable_returns_none(raw):
    assert iso_date(raw) is None
