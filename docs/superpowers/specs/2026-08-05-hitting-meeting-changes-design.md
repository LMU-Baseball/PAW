# Hitting-Side Meeting Changes — Design

**Date:** 2026-08-05
**Status:** Approved — build in order (4 → 1 → 2 → 3)
**Type:** Feature batch (cohesive effort; mirrors the prior 2026-07-28 meeting-changes pattern)

---

## Summary

Four independent changes from a hitting-side coaches' meeting, to be built in order:

1. **Item 4 — HitTrax zone-based swing-decision score** (practice dashboard)
2. **Item 1 — Merge Game Level / Plate Appearances / Zone Location into one tab** (hitting)
3. **Item 2 — Video layout + coach-note relocation** (hitting layout + shared video component + shared notes)
4. **Item 3 — Consistent game filters / video availability marking** (all 3 game dashboards)

Build order = 4 → 1 → 2 → 3 (swing-decision first per the meeting's Next Steps; isolated tab
merge next; then video/notes; then the app-wide filter polish that builds on the video work).

---

## Item 4 — HitTrax zone-based swing-decision score

**Problem.** The swing-decision score uses a fixed in-zone definition (HitTrax zones 1–9 = in-zone,
10–13 = chase). It can't express a player-specific target zone — e.g. a hitter told to avoid the
bottom boxes still has those counted as in-zone, so the score doesn't reflect his actual plan.

**Change.** Make the in-zone set **configurable via a zone chip row** (Zones 1–13, styled like the
existing EV/distance `sfz` chips), **default zones 1–9 selected**. Selected zones define in-zone %;
**every deselected zone (including any deselected 1–9) counts as chase %.** Score = in-zone% − chase%.
The Swing Decision Score Trend chart recomputes on chip toggle.

**Scope decision.** The formula itself is unchanged (still contact%-based, `is_contact = result != -4`);
only the in-zone *set* becomes a parameter. Any deeper metric redefinition waits for the coach/Eli sync.
Selection is scoped to the current player/session/date filters, so it is effectively per-player /
per-session as requested.

**Implementation.**
- `app/data/practice.py`:
  - `swing_decision_score(df, in_zones=range(1,10))` — `in_zones` is the set of zone_sections treated
    as in-zone; chase = all other zones with `zone_section > 0` not in `in_zones`. Default reproduces
    current behavior exactly (1–9 in, 10–13 chase).
  - `swing_decision_trend(df, in_zones=range(1,10))` — threads `in_zones` through to per-date scoring.
- `app/dashboards/hitting_practice/tabs/swing_frequency.py`: add a zone chip row + `dcc.Store`
  (`sds-active` for the swing-decision in-zone set, default 1–9) above the trend chart; the trend
  chart body becomes a callback-updated container.
- `app/dashboards/hitting_practice/callbacks.py`: a chip-toggle callback + a trend-recompute callback,
  mirroring the existing `sfz-*` chip pattern (toggle / styles / body). Keep the existing `sfz` EV
  chips independent — this is a *separate* chip set driving the score.

**Tests.** `tests/` unit tests: default `in_zones` reproduces the current score; a custom set
(e.g. only zones 1–3 in-zone) changes in-zone%/chase%/score as expected; `swing_decision_trend`
respects `in_zones`.

---

## Item 1 — Merge Game Level / Plate Appearances / Zone Location

**Change.** One "Game Level" tab stacking the three current bodies in order:
1. batting-line + batted-ball tables (current Game Level)
2. per-PA breakdown dropdown + all-PAs facet (current Plate Appearances)
3. zone-filter dropdown + zone body (current Zone Location)

Same components and callbacks; only the tab structure changes. Resulting tabs:
**Game Level · Video · Balls in Play · Last 27 PA · Dev Plan**.

**Implementation.**
- `app/dashboards/hitting/layout.py`: remove the `pa` and `zone` `dcc.Tab`s; keep `value="game"`.
- `app/dashboards/hitting/callbacks.py`: in `_render_tab`, the `game` branch renders all three bodies
  stacked (reusing `game_level.render`, the PA dropdown + `pa.render_all_pas`, and the zone dropdown +
  `zl` body). The `pa`/`zone` branches are folded in. `_pa_breakdown` and `_zone_body` callbacks stay
  (their component ids still exist within the merged tab).

**Tests.** Render-smoke: the merged Game Level tab contains the batting-line table, the PA dropdown,
and the zone dropdown.

---

## Item 2 — Video layout + coach-note relocation

**Coach note → left column, under KPIs, condensed, still per-game.**
- `app/dashboards/hitting/layout.py`: move `notes_ui.note_card("hitting")` out of the main content
  column and into the **left column as its own persistent container**, placed *below* the `sidebar`
  Div (NOT inside it — the sidebar Div's children are replaced by `_on_selection`, which would clobber
  the note card's own render-callback output). The note stays keyed per-game; all-games range shows the
  existing "pick a single game" prompt.
- Apply the same note-in-sidebar treatment to **pitching and catching** layouts for consistency (shared
  `notes_ui`); the note becomes narrow (left-column width) on every tab automatically.
- Widen the left column modestly (~240px → ~260px) so the note textarea is usable.

**Video tab (shared `app/dashboards/video/component.py`): video is the dominant element.**
- Reorder `render` so the **video player is large and on the left (~60%)** with the angle buttons above
  it and the hint; the **pitch table is compact on the right (~40%)**.
- **Drop the Date column** from the table: remove `"Date"` from `DISPLAY_COLS` in `app/data/video.py`.
  (Minor tradeoff: in an all-games range the per-pitch date is no longer shown; acceptable per coach.)
- Change lands on all three video tabs (hitting Video, pitching Outing Video, catching Pitch Level).

**Tests.** Render-smoke: note card is present in the left column and absent from the main content
column; video render places the player and table (Date column no longer in `DISPLAY_COLS`).

---

## Item 3 — Consistent game filters / video availability marking

**Reality from the code.** `wh_games_for_batter` and the pitching/catching equivalents already list
only games where the player has tracked data, so an empty Game-Level selection basically can't occur.
The real inconsistency is **video**: only ~37 Spring-2026 games have clips, so a valid game can show
data everywhere but be empty on Video.

**Change.**
- Add a helper (in `app/data/video.py`) that returns the set of `game_id`s that have video **for a
  given player** (batter/pitcher/catcher) among a candidate list — a lightweight query against the
  video view.
- **Tag video-having games in the Game dropdown with a 🎥 marker** in the option label. Implemented in
  the game-options builder path used by each dashboard (extend `date_range.game_options` to accept an
  optional `video_game_ids` set, or tag in each layout/callback where options are built).
- Standardize the "No video available for this selection" empty state (already present in the video
  component) across the three dashboards.

**Tests.** Unit test the video-availability helper (games with vs without video); options-builder test
that a game in the video set gets the 🎥 tag and one without does not.

---

## Non-goals / deferred
- No change to the swing-decision *formula* beyond the configurable in-zone set (Eli sync).
- No per-tab game-dropdown switching (rejected in brainstorming as disorienting).
- No caching work (separate pre-deploy task with Griff).
- Video upload workflow / angle alignment (separate group call).

## Rollout notes
- Coach-note relocation and video-layout changes touch shared components → verify all three game
  dashboards render after Item 2.
- Full test suite must stay green after each item (currently 427 passing per project memory).
