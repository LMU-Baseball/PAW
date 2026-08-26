"""LIVE browser regression test: a coach's Save on the Velo Board and the
Competitive Cauldron actually persists to the DB and reads back correctly for
a genuinely fresh session.

Every other test for these two dashboards (`tests/test_velo_board.py`,
`tests/test_cauldron.py`, `tests/test_velo_board_grid.py` /
`tests/test_cauldron_grid.py`) calls `save_board`/`save_grid` directly with a
hand-built row dict -- none of them exercise a REAL rendered
`dash_table.DataTable` + a REAL simulated cell edit through the browser. The
one thing those tests can't prove is whether the hidden `pitcher_id`/
`player_id` column on each row actually survives the round trip through the
browser (DataTable serializes/deserializes the whole row dict on every edit),
so a coach's save could in principle land on the wrong row, or silently
no-op, without any existing test catching it. This test closes that gap by
driving the ACTUAL page: log in as a coach, edit one cell through the real
DataTable UI (a real click + real keystrokes, not a JS-injected value), Save,
then load the page again in a brand-new browser context (fresh cookies, no
JS state carried over -- not a soft reload) and confirm the edited value is
still there.

Like `tests/test_hitting.py`, this is a plain module that talks to the live
DB directly (no `lookup=` mocking) -- but it ALSO needs a live Dash dev
server + a real Chromium instance (Playwright, already in
requirements.txt), which `test_hitting.py` doesn't. CI only ever runs
`tests/test_security.py` (see `.github/workflows/ci.yml`), so this file
never runs there either way; the module-level skip below additionally makes
a *local* `python -m pytest` run degrade gracefully (skip, not fail) when no
dev server happens to be up, while staying fully runnable on demand:

    PYTHONIOENCODING=utf-8 python run.py &          # start the dev server
    python -m pytest tests/test_velo_cauldron_save_live.py -v

Demo coach/player credentials are the ones documented in
`memory/MEMORY.md` §7 (seeded into the gitignored `instance/paw_app.db`);
override via env vars if a given machine's seed differs.
"""
from __future__ import annotations

import os
import random
import urllib.request

import pytest

BASE_URL = os.environ.get("PAW_LIVE_TEST_BASE_URL", "http://127.0.0.1:8050")
COACH_EMAIL = os.environ.get("PAW_TEST_COACH_EMAIL", "coach@lmu.edu")
COACH_PASSWORD = os.environ.get("PAW_TEST_COACH_PASSWORD", "paw2026")
PLAYER_EMAIL = os.environ.get("PAW_TEST_PLAYER_EMAIL", "hitter@lmu.edu")
PLAYER_PASSWORD = os.environ.get("PAW_TEST_PLAYER_PASSWORD", "paw2026")

# A CLOSED past season (not the live current one) so this test's writes never
# collide with a coach actually using the board this week -- 2025/2026 has a
# real 19-pitcher roster with GAMES history, safely in the past.
SEASON = "2025/2026"
PITCHER_NAME = "Schneider, Maxwell"

CAULDRON_ENTRY_DATE = "2026-05-01"          # inside the 2025/2026 season bounds
CAULDRON_PLAYER_NAME = "Behrens, Adam"
CAULDRON_METRIC = "mod_command"             # a MANUAL metric: no auto baseline
                                             # to fight with, blank until a
                                             # coach types a value


def _server_reachable(url: str, timeout: float = 1.5) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


_SERVER_UP = _server_reachable(f"{BASE_URL}/login")

pytestmark = pytest.mark.skipif(
    not _SERVER_UP,
    reason=(
        f"live dev server not reachable at {BASE_URL} -- start it first: "
        "`PYTHONIOENCODING=utf-8 python run.py`"
    ),
)

# playwright is only imported once we know we're actually going to run.
if _SERVER_UP:
    from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


# --------------------------- shared DOM helpers -----------------------------

def _login(page, email: str, password: str) -> None:
    page.goto(f"{BASE_URL}/login")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, f"login failed for {email!r} -- still on {page.url}"


def _select_dropdown(page, dropdown_id: str, option_text: str) -> None:
    """Open a Dash `dcc.Dropdown` (rendered as a button + a `role=listbox`
    popup of `label.dash-dropdown-option`s in this Dash version) and pick the
    option whose visible text matches `option_text`."""
    page.click(f"#{dropdown_id}")
    page.click(f'label.dash-dropdown-option:has-text("{option_text}")')
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)   # client-side re-render after the XHR settles


def _edit_cell(page, cell, value) -> None:
    """Click a DataTable cell (must already be `editable`) and type a new
    value through its real `<input>`, replacing whatever was there."""
    cell.click()
    page.wait_for_timeout(150)
    inp = cell.query_selector("input")
    assert inp is not None, (
        "cell did not enter an editable input on click -- the grid may not "
        "actually be unlocked (Edit didn't fire, or the coach re-check failed)"
    )
    inp.fill("")
    inp.type(str(value))
    page.keyboard.press("Enter")
    page.wait_for_timeout(150)


# ================================ VELO BOARD =================================

def test_velo_board_save_persists_across_fresh_session(browser):
    """Coach edits Velo Goal for one pitcher through the real DataTable,
    Saves, and a BRAND NEW browser context (fresh cookies, fresh page load --
    not a soft reload) reads back the exact value, both as the same coach and
    as a different (player) account viewing the same shared table."""
    new_value = round(random.uniform(130.0, 149.9), 1)

    # ---- Session 1: coach edits + saves --------------------------------
    ctx1 = browser.new_context()
    page = ctx1.new_page()
    _login(page, COACH_EMAIL, COACH_PASSWORD)
    page.goto(f"{BASE_URL}/dash/velo_board/")
    page.wait_for_load_state("networkidle")
    _select_dropdown(page, "velo-season", SEASON)
    page.wait_for_selector('#velo-grid td[data-dash-column="pitcher_name"]', timeout=10000)

    row_cell = page.query_selector(
        f'#velo-grid td[data-dash-column="pitcher_name"]:has-text("{PITCHER_NAME}")')
    assert row_cell is not None, (
        f"expected pitcher {PITCHER_NAME!r} not found on the {SEASON} velo board -- "
        "roster may have changed; pick a different pitcher fixture")
    row_idx = row_cell.get_attribute("data-dash-row")
    goal_cell = page.query_selector(
        f'#velo-grid td[data-dash-row="{row_idx}"][data-dash-column="velo_goal"]')
    before_value = goal_cell.inner_text()

    page.click("#velo-edit")
    page.wait_for_selector("#velo-save-status:has-text('Editing')", timeout=5000)
    _edit_cell(page, goal_cell, new_value)
    page.click("#velo-save")
    # Save is genuinely slow in this repo (leaderboard recompute over the whole
    # season is not cached across the write) -- observed ~16s locally.
    page.wait_for_selector("#velo-save-status:has-text('Saved.')", timeout=30000)

    # Same-request round trip: `_on_save` re-reads from the DB and re-renders
    # the (still-visible, re-locked) table in the SAME response.
    goal_cell_now = page.query_selector(
        f'#velo-grid td[data-dash-row="{row_idx}"][data-dash-column="velo_goal"]')
    assert float(goal_cell_now.inner_text()) == pytest.approx(new_value, abs=0.05), (
        f"grid did not reflect the saved value within the same request/response: "
        f"wrote {new_value}, table shows {goal_cell_now.inner_text()!r}")
    ctx1.close()   # entirely tear down session 1 -- no cookies/JS state carried forward

    # ---- Session 2: a GENUINELY fresh context, SAME coach --------------
    ctx2 = browser.new_context()
    page2 = ctx2.new_page()
    _login(page2, COACH_EMAIL, COACH_PASSWORD)
    page2.goto(f"{BASE_URL}/dash/velo_board/")
    page2.wait_for_load_state("networkidle")
    _select_dropdown(page2, "velo-season", SEASON)
    page2.wait_for_selector('#velo-grid td[data-dash-column="pitcher_name"]', timeout=10000)

    row_cell2 = page2.query_selector(
        f'#velo-grid td[data-dash-column="pitcher_name"]:has-text("{PITCHER_NAME}")')
    row_idx2 = row_cell2.get_attribute("data-dash-row")
    goal_cell2 = page2.query_selector(
        f'#velo-grid td[data-dash-row="{row_idx2}"][data-dash-column="velo_goal"]')
    reloaded_value = goal_cell2.inner_text()
    ctx2.close()

    assert float(reloaded_value) == pytest.approx(new_value, abs=0.05), (
        f"Velo Board save did NOT persist across a fresh session: wrote {new_value} "
        f"(before-edit value was {before_value!r}), but a brand-new coach session "
        f"reads back {reloaded_value!r}")

    # ---- Session 3: a DIFFERENT account (player), same shared table -----
    ctx3 = browser.new_context()
    page3 = ctx3.new_page()
    _login(page3, PLAYER_EMAIL, PLAYER_PASSWORD)
    page3.goto(f"{BASE_URL}/dash/velo_board/")
    page3.wait_for_load_state("networkidle")
    assert page3.query_selector("#velo-edit") is None, (
        "a player account unexpectedly sees the coach Edit control")
    _select_dropdown(page3, "velo-season", SEASON)
    page3.wait_for_selector('#velo-grid td[data-dash-column="pitcher_name"]', timeout=10000)

    row_cell3 = page3.query_selector(
        f'#velo-grid td[data-dash-column="pitcher_name"]:has-text("{PITCHER_NAME}")')
    row_idx3 = row_cell3.get_attribute("data-dash-row")
    goal_cell3 = page3.query_selector(
        f'#velo-grid td[data-dash-row="{row_idx3}"][data-dash-column="velo_goal"]')
    player_view_value = goal_cell3.inner_text()
    ctx3.close()

    assert float(player_view_value) == pytest.approx(new_value, abs=0.05), (
        f"Velo Board value differs by viewing account: expected {new_value}, "
        f"a player session reads back {player_view_value!r}")


# ================================ CAULDRON ===================================

def test_cauldron_save_persists_across_fresh_session(browser):
    """Coach edits a manual scoring cell for one player/day through the real
    DataTable, Saves (which hides + re-locks the grid -- Cauldron does NOT
    re-render the grid in place the way Velo Board does), and a BRAND NEW
    browser context reads back the exact value as the same coach."""
    new_value = random.randint(300, 999)   # well outside real scoring's -10..20 range

    def _open_grid_to(page):
        """Coach login -> Cauldron -> pick the season -> Edit (reveals +
        unlocks) -> set the entry date -> wait for the roster to render."""
        page.goto(f"{BASE_URL}/dash/cauldron/")
        page.wait_for_load_state("networkidle")
        _select_dropdown(page, "cauldron-season", SEASON)
        page.click("#cauldron-edit")
        page.wait_for_selector("#cauldron-save-status:has-text('Editing')", timeout=5000)
        date_input = page.query_selector("#cauldron-date")
        date_input.click()
        date_input.fill("")
        date_input.type(CAULDRON_ENTRY_DATE)
        page.keyboard.press("Enter")
        page.wait_for_selector('#cauldron-grid td[data-dash-column="player"]', timeout=10000)

    # ---- Session 1: coach edits + saves --------------------------------
    ctx1 = browser.new_context()
    page = ctx1.new_page()
    _login(page, COACH_EMAIL, COACH_PASSWORD)
    _open_grid_to(page)

    player_cell = page.query_selector(
        f'#cauldron-grid td[data-dash-column="player"]:has-text("{CAULDRON_PLAYER_NAME}")')
    assert player_cell is not None, (
        f"expected player {CAULDRON_PLAYER_NAME!r} not found on the {SEASON} "
        f"cauldron roster for {CAULDRON_ENTRY_DATE} -- roster may have changed; "
        "pick a different player fixture")
    row_idx = player_cell.get_attribute("data-dash-row")
    metric_cell = page.query_selector(
        f'#cauldron-grid td[data-dash-row="{row_idx}"][data-dash-column="{CAULDRON_METRIC}"]')
    before_value = metric_cell.inner_text()

    _edit_cell(page, metric_cell, new_value)
    page.click("#cauldron-save")
    page.wait_for_selector("#cauldron-save-status:has-text('Saved.')", timeout=30000)

    # Cauldron's Save hides + re-locks the grid instead of re-rendering it in
    # place (the scoreboard re-reads instead) -- confirm that contract, then
    # rely on the fresh-session reload below for the actual persistence proof.
    wrap_style = page.eval_on_selector("#cauldron-grid-wrap", "el => el.getAttribute('style')")
    assert "display: none" in (wrap_style or ""), (
        f"expected the grid wrapper to re-hide after Save, got style={wrap_style!r}")
    ctx1.close()

    # ---- Session 2: a GENUINELY fresh context, SAME coach --------------
    ctx2 = browser.new_context()
    page2 = ctx2.new_page()
    _login(page2, COACH_EMAIL, COACH_PASSWORD)
    _open_grid_to(page2)

    player_cell2 = page2.query_selector(
        f'#cauldron-grid td[data-dash-column="player"]:has-text("{CAULDRON_PLAYER_NAME}")')
    row_idx2 = player_cell2.get_attribute("data-dash-row")
    metric_cell2 = page2.query_selector(
        f'#cauldron-grid td[data-dash-row="{row_idx2}"][data-dash-column="{CAULDRON_METRIC}"]')
    reloaded_value = metric_cell2.inner_text()
    ctx2.close()

    assert reloaded_value == str(new_value), (
        f"Cauldron save did NOT persist across a fresh session: wrote {new_value} "
        f"(before-edit value was {before_value!r}), but a brand-new coach session "
        f"reads back {reloaded_value!r}")
