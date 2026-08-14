"""Competitive Cauldron scoreboard visual: branded header renders the
wordmark, scoreboard table groups rows by team with per-player/per-team
totals."""
import pandas as pd
from dash import html

from app.dashboards.cauldron import visual as V


def _flatten(node):
    """Yield every nested Dash component/string leaf under `node` (depth-first),
    including `node` itself. Used to walk the rendered component tree instead
    of grepping the flattened `str(view)`, so assertions can pin down a
    SPECIFIC cell rather than any substring match anywhere on the page."""
    if node is None:
        return
    if isinstance(node, (list, tuple)):
        for n in node:
            yield from _flatten(n)
        return
    yield node
    children = getattr(node, "children", None)
    if children is not None:
        yield from _flatten(children)


def _cell_text(cell) -> str:
    """Concatenate all string leaves under one Td/Th (or any component)."""
    return "".join(n for n in _flatten(cell) if isinstance(n, str))


def _cells(row: html.Tr) -> list:
    c = row.children
    return list(c) if isinstance(c, (list, tuple)) else [c]


def _rows(view) -> list:
    """All html.Tr rows anywhere in the rendered tree."""
    return [n for n in _flatten(view) if isinstance(n, html.Tr)]


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
    assert "COMPETITIVE" in s and "CAULDRON" in s


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

    # The Crimson team-total row exists AND carries the correctly computed
    # sum -- not just the string "Total" (which the column header already
    # contributes regardless of whether the total row renders or computes
    # right). Crimson's fixture points: player 1 = 20 + -10 = 10; player 2 =
    # -10 + 20 = 10; team total = 20.
    rows = _rows(view)
    total_row = next(r for r in rows if _cell_text(_cells(r)[0]) == "Crimson Total")
    assert _cell_text(_cells(total_row)[-1]) == "+20"


def test_scoreboard_captain_first_with_star():
    scoring = pd.DataFrame([
        {"metric": "strike_pct", "label": "Strike%", "sort_order": 1, "is_manual": False},
    ])
    teams = pd.DataFrame([
        {"player_id": 1, "team": "Crimson", "is_captain": 0},
        {"player_id": 2, "team": "Crimson", "is_captain": 1},
    ])
    daily = pd.DataFrame([
        {"player_id": 1, "play_date": "2026-08-01", "metric": "strike_pct", "points": 30, "source": "auto"},
        {"player_id": 2, "play_date": "2026-08-01", "metric": "strike_pct", "points": 10, "source": "auto"},
    ])
    names = {1: "Aaron, Bo", 2: "Cruz, Dan"}
    view = V.scoreboard_view(daily, teams, scoring, names)
    rows = _rows(view)
    player_rows = [r for r in rows if _cell_text(_cells(r)[0]) in ("Aaron, Bo", "★ Cruz, Dan")]
    # captain (player 2) floats to the top of the team despite FEWER points
    assert _cell_text(_cells(player_rows[0])[0]) == "★ Cruz, Dan"
    assert _cell_text(_cells(player_rows[1])[0]) == "Aaron, Bo"


def test_scoreboard_has_dark_background():
    daily, teams, scoring, roster_names = _fixture()
    teams = teams.assign(is_captain=0)
    view = V.scoreboard_view(daily, teams, scoring, roster_names)
    assert "#161616" in str(view)   # dark table background so white text reads


def test_scoreboard_view_handles_empty_df():
    empty_daily = pd.DataFrame(columns=["player_id", "play_date", "metric", "points", "source"])
    empty_teams = pd.DataFrame(columns=["player_id", "team"])
    empty_scoring = pd.DataFrame(columns=["metric", "label", "sort_order", "is_manual"])
    view = V.scoreboard_view(empty_daily, empty_teams, empty_scoring, {})
    assert view is not None
    assert "No" in str(view)


def test_scoreboard_view_without_roster_names_falls_back_to_id():
    # A distinctive multi-digit id: unlike "1"/"2"/"3" it can't accidentally
    # match a substring of an inline style value (e.g. "10px 14px",
    # "rgba(58,209,111,0.18)"), so this only passes if `_display_name`
    # actually renders the id into the player-name cell.
    scoring = pd.DataFrame([
        {"metric": "strike_pct", "label": "Strike%", "sort_order": 1, "is_manual": False},
    ])
    teams = pd.DataFrame([{"player_id": 8675309, "team": "Crimson"}])
    daily = pd.DataFrame([
        {"player_id": 8675309, "play_date": "2026-08-01", "metric": "strike_pct",
         "points": 20, "source": "auto"},
    ])
    view = V.scoreboard_view(daily, teams, scoring, None)
    rows = _rows(view)
    player_row = next(
        (r for r in rows if _cell_text(_cells(r)[0]) == "8675309"), None)
    assert player_row is not None
