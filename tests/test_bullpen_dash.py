"""Tests for the Dash bullpen dashboard (selectors, layout, tabs, build)."""
import pandas as pd
import pytest

from app import create_app
from config import Config

GEIS = 824645


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_resolve_pitcher_player_is_self_only():
    from app.dashboards.bullpen import selectors
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=555) == 555
    assert selectors.resolve_pitcher(999, is_coach=True, own_trackman_id=None) == 999


def test_pitcher_options_coach_nonempty():
    from app.dashboards.bullpen import selectors
    opts = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])


def test_session_dropdown_options_labels():
    from app.dashboards.bullpen import selectors
    df = pd.DataFrame({"date": ["2026-05-13", "2026-05-06"], "pitches": [18, 17]})
    opts = selectors.session_dropdown_options(df)
    assert opts[0] == {"label": "2026-05-13 (18)", "value": "2026-05-13"}
    assert selectors.session_dropdown_options(pd.DataFrame(columns=["date", "pitches"])) == []
