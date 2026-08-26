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

import pandas as pd
import pytest

from app.data import cauldron as CD
from app.data import pitching_caps as PC
from app.data import velo_board as VB

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
CAULDRON_METRIC_LABEL = "Mod Command"       # this metric's cauldron_scoring label --
                                             # the scoreboard table keys columns by this
                                             # text, not the `mod_command` id


def _server_reachable(url: str, timeout: float = 1.5) -> bool:
    """Only proves GET /login answers without raising -- NOT a full health
    check. A server that's up but broken somewhere downstream of that one
    page (e.g. a DB connection failure on a dashboard route) would still
    pass this and only get caught later by `_login()`'s own hard assert."""
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


# ------------------------ direct data-layer teardown -------------------------
#
# Every test below edits a real row through the live browser UI. Whatever it
# touches MUST be restored via a plain, fast, deterministic direct write to
# the data layer in a `finally` block -- regardless of whether the rest of
# the test passed or failed -- so this file can never leave production data
# altered. See `docs/superpowers/plans/2026-08-25-post-slaa-fixes.md` finding
# #1 (the incident this fixes: an earlier version of this file had no
# teardown at all).


def _isna(v) -> bool:
    """None/NaN/NaT -> True, matching `velo_board._clean`/`cauldron._clean`'s
    own notion of 'no value' (a plain `v is None` check would miss a NaN read
    back from a nullable numeric DB column via pandas)."""
    return v is None or (isinstance(v, float) and pd.isna(v))


def _velo_pitcher_id(season: str, pitcher_name: str) -> int:
    board = VB.board_rows(season, VB.default_week_for(season))
    match = board[board["pitcher_name"] == pitcher_name]
    assert not match.empty, (
        f"expected pitcher {pitcher_name!r} not found on the {season} velo board -- "
        "roster may have changed; pick a different pitcher fixture")
    return int(match.iloc[0]["pitcher_id"])


def _velo_entry_row(season: str, week_start: str, pitcher_id: int) -> dict | None:
    """The full `velo_board_entries` row (as a dict) for one pitcher/week, or
    `None` if no row exists yet -- so a restore can tell "never had a row"
    apart from "had a row with a blank field"."""
    entries = VB.read_entries(season, week_start)
    if entries.empty:
        return None
    match = entries[entries["pitcher_id"].astype(int) == pitcher_id]
    return match.iloc[0].to_dict() if not match.empty else None


def _restore_velo_entry(season: str, week_start: str, pitcher_id: int,
                        pitcher_name: str, orig_row: dict | None) -> None:
    """Write `orig_row` back verbatim (the direct data-layer write this
    teardown promises), or -- if no row existed before this test ever
    touched it -- write velo_goal/assessment back to None (absent), per
    `velo_board.py`'s own contract that a None field means 'no value', not a
    literal placeholder value."""
    if orig_row is not None:
        restore = {**orig_row, "pitcher_id": pitcher_id,
                   "season_label": season, "week_start": week_start}
    else:
        restore = {"pitcher_id": pitcher_id, "pitcher_name": pitcher_name,
                   "season_label": season, "week_start": week_start,
                   "velo_goal": None, "assessment": None}
    VB.upsert_entries([restore])

    # Prove the restore actually worked -- re-read the row directly via the
    # data layer immediately after writing it, so a future regression in
    # this teardown itself is caught here, not just trusted.
    after = _velo_entry_row(season, week_start, pitcher_id)
    if orig_row is None:
        assert after is None or _isna(after.get("velo_goal")), (
            f"teardown failed to restore velo_goal to absent: {after!r}")
    else:
        assert after is not None, "teardown failed to restore the velo_board_entries row at all"
        want = orig_row.get("velo_goal")
        got = after.get("velo_goal")
        if _isna(want):
            assert _isna(got), f"teardown failed to restore velo_goal to {want!r}, got {got!r}"
        else:
            assert got is not None and float(got) == pytest.approx(float(want), abs=1e-6), (
                f"teardown failed to restore velo_goal: wanted {want!r}, got {got!r}")


def _cauldron_player_id(season: str, player_name: str) -> int:
    roster = PC.lmu_pitchers(season)
    match = roster[roster["Pitcher"] == player_name]
    assert not match.empty, (
        f"expected player {player_name!r} not found on the {season} cauldron "
        "roster -- roster may have changed; pick a different player fixture")
    return int(match.iloc[0]["PitcherId"])


def _cauldron_daily_row(play_date: str, player_id: int, metric: str) -> dict | None:
    """The full `cauldron_daily` row (as a dict) for one player/date/metric,
    or `None` if no row exists yet."""
    daily = CD.read_daily(play_date=play_date, player_id=player_id)
    if daily.empty:
        return None
    match = daily[daily["metric"] == metric]
    return match.iloc[0].to_dict() if not match.empty else None


def _restore_cauldron_daily(play_date: str, player_id: int, metric: str,
                            orig_row: dict | None) -> None:
    """Write `orig_row` back verbatim, or -- if no row existed before this
    test ever touched it -- write raw_value/points/source back to None
    (absent), matching `cauldron.py`'s own None-means-no-value contract."""
    if orig_row is not None:
        restore = {**orig_row, "player_id": player_id,
                   "play_date": play_date, "metric": metric}
    else:
        restore = {"player_id": player_id, "play_date": play_date, "metric": metric,
                   "raw_value": None, "points": None, "source": None}
    CD.upsert_daily([restore])

    after = _cauldron_daily_row(play_date, player_id, metric)
    if orig_row is None:
        assert after is None or _isna(after.get("points")), (
            f"teardown failed to restore cauldron points to absent: {after!r}")
    else:
        assert after is not None, "teardown failed to restore the cauldron_daily row at all"
        want = orig_row.get("points")
        got = after.get("points")
        if _isna(want):
            assert _isna(got), f"teardown failed to restore points to {want!r}, got {got!r}"
        else:
            assert got is not None and float(got) == pytest.approx(float(want), abs=1e-6), (
                f"teardown failed to restore points: wanted {want!r}, got {got!r}")


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


def _scoreboard_metric_text(page, player_name: str, metric_label: str) -> str | None:
    """Read one player's points cell for one metric out of the Cauldron's
    `cauldron-scoreboard` table -- the ONLY surface a player account can see
    (the coach grid, `cauldron-grid`, is entirely absent from a player's
    component tree; `layout.py` only renders `cauldron-coach-section` when
    `is_coach`). Not a `dash_table.DataTable` (no `data-dash-column`
    attributes to key off), so this locates the column by its header text and
    the row by the player's display name instead. Returns `None` if the
    player isn't found in the currently-selected week's scoreboard."""
    table = page.query_selector("#cauldron-scoreboard table")
    if table is None:
        return None
    rows = table.query_selector_all("tr")
    if not rows:
        return None
    header_cells = rows[0].query_selector_all("th, td")
    header_texts = [c.inner_text().strip().lower() for c in header_cells]
    if metric_label.strip().lower() not in header_texts:
        return None
    col_idx = header_texts.index(metric_label.strip().lower())
    for row in rows[1:]:
        cells = row.query_selector_all("td")
        # Team-header/team-total rows use a single colSpan cell (or blanks) --
        # only a real player row's first cell has the player's name AND enough
        # cells to index into.
        if len(cells) <= col_idx:
            continue
        if player_name in cells[0].inner_text():
            return cells[col_idx].inner_text()
    return None


# ================================ VELO BOARD =================================

def test_velo_board_save_persists_across_fresh_session(browser):
    """Coach edits Velo Goal for one pitcher through the real DataTable,
    Saves, and a BRAND NEW browser context (fresh cookies, fresh page load --
    not a soft reload) reads back the exact value, both as the same coach and
    as a different (player) account viewing the same shared table.

    The edit is made against a real `velo_board_entries` row, so this test
    captures that row's PRE-edit state via the data layer up front and
    restores it in a `finally` block no matter how the test exits (pass,
    assertion failure, or an unrelated exception) -- this is a LIVE
    production DB, and a coach's real numbers must never be left overwritten
    by a test run. See `_restore_velo_entry` above."""
    new_value = round(random.uniform(130.0, 149.9), 1)

    week = VB.default_week_for(SEASON)
    pitcher_id = _velo_pitcher_id(SEASON, PITCHER_NAME)
    orig_row = _velo_entry_row(SEASON, week, pitcher_id)

    ctx1 = ctx2 = ctx3 = None
    try:
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
        ctx1 = None

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
        ctx2 = None

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
        ctx3 = None

        assert float(player_view_value) == pytest.approx(new_value, abs=0.05), (
            f"Velo Board value differs by viewing account: expected {new_value}, "
            f"a player session reads back {player_view_value!r}")
    finally:
        # Close any browser context left open by an assertion failure/exception
        # above, then unconditionally restore the DB row via the data layer --
        # NOT through the browser -- regardless of how the test exited.
        for ctx in (ctx1, ctx2, ctx3):
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
        _restore_velo_entry(SEASON, week, pitcher_id, PITCHER_NAME, orig_row)


# ================================ CAULDRON ===================================

def test_cauldron_save_persists_across_fresh_session(browser):
    """Coach edits a manual scoring cell for one player/day through the real
    DataTable, Saves (which hides + re-locks the grid -- Cauldron does NOT
    re-render the grid in place the way Velo Board does), and a BRAND NEW
    browser context reads back the exact value -- as the same coach, and (via
    the week-bounded scoreboard, the only surface a player account can see;
    Cauldron has no shared table the way Velo Board does) as a different
    (player) account too.

    The edit is made against a real `cauldron_daily` row, so this test
    captures that row's PRE-edit state via the data layer up front and
    restores it in a `finally` block no matter how the test exits (pass,
    assertion failure, or an unrelated exception) -- this is a LIVE
    production DB, and a real week's Cauldron scoreboard total must never be
    left corrupted by a test run. See `_restore_cauldron_daily` above."""
    new_value = random.randint(300, 999)   # well outside real scoring's -10..20 range

    player_id = _cauldron_player_id(SEASON, CAULDRON_PLAYER_NAME)
    orig_row = _cauldron_daily_row(CAULDRON_ENTRY_DATE, player_id, CAULDRON_METRIC)

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

    ctx1 = ctx2 = ctx3 = None
    try:
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
        ctx1 = None

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
        ctx2 = None

        assert reloaded_value == str(new_value), (
            f"Cauldron save did NOT persist across a fresh session: wrote {new_value} "
            f"(before-edit value was {before_value!r}), but a brand-new coach session "
            f"reads back {reloaded_value!r}")

        # ---- Session 3: a DIFFERENT account (player) -----------------------
        # Unlike Velo Board, Cauldron has no shared table -- `cauldron-coach-
        # section` (which contains `cauldron-grid`/`cauldron-edit`/`cauldron-save`)
        # is entirely absent from a player's component tree (`layout.py` only
        # renders it `if is_coach`), confirmed live: `#cauldron-grid` does not
        # exist at all on a player's rendered page. The ONLY place a player can
        # see this value is the week-bounded `cauldron-scoreboard` table, which
        # pivots points by player x metric -- so this session selects the same
        # season AND snaps the shared Week picker onto the entry date's week
        # (season selection alone does not do this; the week auto-snaps to the
        # season's own default week instead) before reading the cell back.
        ctx3 = browser.new_context()
        page3 = ctx3.new_page()
        _login(page3, PLAYER_EMAIL, PLAYER_PASSWORD)
        page3.goto(f"{BASE_URL}/dash/cauldron/")
        page3.wait_for_load_state("networkidle")
        assert page3.query_selector("#cauldron-edit") is None, (
            "a player account unexpectedly sees the coach Edit control")

        _select_dropdown(page3, "cauldron-season", SEASON)
        # Extra settle time beyond `_select_dropdown`'s own wait: typing into the
        # week picker too soon after the season change races its own async
        # `cauldron-week.date` snap-back response and gets silently overwritten.
        page3.wait_for_timeout(1200)
        week_input = page3.query_selector("#cauldron-week")
        week_input.click()
        week_input.fill("")
        week_input.type(CAULDRON_ENTRY_DATE)
        page3.keyboard.press("Enter")
        page3.wait_for_load_state("networkidle")
        page3.wait_for_timeout(1500)   # scoreboard re-render after the XHR settles

        player_view_text = _scoreboard_metric_text(page3, CAULDRON_PLAYER_NAME, CAULDRON_METRIC_LABEL)
        ctx3.close()
        ctx3 = None

        assert player_view_text is not None, (
            f"could not find {CAULDRON_PLAYER_NAME!r} / {CAULDRON_METRIC_LABEL!r} in the "
            "player's scoreboard view -- selectors may need updating")
        assert player_view_text == f"+{new_value}", (
            f"Cauldron value differs by viewing account: expected +{new_value}, "
            f"a player session's scoreboard reads back {player_view_text!r}")
    finally:
        # Close any browser context left open by an assertion failure/exception
        # above, then unconditionally restore the DB row via the data layer --
        # NOT through the browser -- regardless of how the test exited.
        for ctx in (ctx1, ctx2, ctx3):
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
        _restore_cauldron_daily(CAULDRON_ENTRY_DATE, player_id, CAULDRON_METRIC, orig_row)
