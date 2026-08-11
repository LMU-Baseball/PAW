"""Competitive Cauldron scoreboard visual: branded header renders the
wordmark, scoreboard table groups rows by team with per-player/per-team
totals."""
import pandas as pd

from app.dashboards.cauldron import visual as V


def _fixture():
    scoring = pd.DataFrame([
        {"metric": "strike_pct", "label": "Strike%", "sort_order": 1, "is_manual": False},
        {"metric": "k_pct", "label": "K%", "sort_order": 2, "is_manual": False},
        {"metric": "barrel", "label": "Barrel", "sort_order": 3, "is_manual": False},
    ])
    teams = pd.DataFrame([
        {"player_id": 1, "team": "Crimson"},
        {"player_id": 2, "team": "Crimson"},
        {"player_id": 3, "team": "Blue"},
    ])
    daily = pd.DataFrame([
        {"player_id": 1, "play_date": "2026-08-01", "metric": "strike_pct", "points": 20, "source": "auto"},
        {"player_id": 1, "play_date": "2026-08-01", "metric": "k_pct", "points": -10, "source": "auto"},
        {"player_id": 2, "play_date": "2026-08-01", "metric": "strike_pct", "points": -10, "source": "auto"},
        {"player_id": 2, "play_date": "2026-08-01", "metric": "barrel", "points": 20, "source": "auto"},
        {"player_id": 3, "play_date": "2026-08-01", "metric": "strike_pct", "points": 20, "source": "auto"},
        {"player_id": 3, "play_date": "2026-08-01", "metric": "k_pct", "points": 20, "source": "auto"},
    ])
    roster_names = {1: "Aaron, Bo", 2: "Cruz, Dan", 3: "Ellis, Finn"}
    return daily, teams, scoring, roster_names


def test_cauldron_header_has_wordmark():
    s = str(V.cauldron_header())
    assert "Competitive Cauldron" in s or "COMPETITIVE CAULDRON" in s


def test_scoreboard_view_groups_by_team_with_totals():
    daily, teams, scoring, roster_names = _fixture()
    view = V.scoreboard_view(daily, teams, scoring, roster_names)
    s = str(view)

    # Team names render as group headers.
    assert "Crimson" in s and "Blue" in s
    # Player display names (mapped via roster_names) render.
    assert "Aaron, Bo" in s
    assert "Cruz, Dan" in s
    assert "Ellis, Finn" in s
    # Metric column labels render.
    assert "Strike%" in s and "K%" in s and "Barrel" in s
    # A team-total line/row appears somewhere.
    assert "Total" in s


def test_scoreboard_view_handles_empty_df():
    empty_daily = pd.DataFrame(columns=["player_id", "play_date", "metric", "points", "source"])
    empty_teams = pd.DataFrame(columns=["player_id", "team"])
    empty_scoring = pd.DataFrame(columns=["metric", "label", "sort_order", "is_manual"])
    view = V.scoreboard_view(empty_daily, empty_teams, empty_scoring, {})
    assert view is not None
    assert "No" in str(view)


def test_scoreboard_view_without_roster_names_falls_back_to_id():
    daily, teams, scoring, _ = _fixture()
    view = V.scoreboard_view(daily, teams, scoring, None)
    s = str(view)
    assert "1" in s and "2" in s and "3" in s
