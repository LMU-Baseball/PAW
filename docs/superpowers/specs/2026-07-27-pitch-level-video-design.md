# Design: Shared Pitch-Level Video Tab (Sub-project V)

**Date:** 2026-07-27
**Branch:** `feat/pitch-level-video` (off `main` @ `6030ff3`)
**Status:** Approved for implementation (user, 2026-07-27)
**Part of:** a 4-sub-project effort to finish the deferred dashboard tabs — **V (this)** → H (hitting analytical tabs: Last 27 PA, Spray/Radial) → P (pitching analytical tabs: Counts, Heatmaps) → D (hitting Dev Plans). Each gets its own spec → plan → build cycle. V is first because it is a single shared component that delivers a deferred tab in **three** dashboards at once.

---

## 1. Motivation

Three dashboards each have a deferred video tab from their legacy R apps:
- **Hitting** — "Video" tab (old `src/app 1`).
- **Pitching** — "Pitch Level" tab (old `src/app 4`).
- **Catching** — "Pitch Level" tab (old `src/app.R`): a clickable pitch table that loaded two videos (Center Field + batter-side Home Plate).

The modern warehouse now has abundant pitch video: `vw_pitch_video` holds **38,055 rows (Spring 2026)** with public S3 `.mp4` URLs across **four camera angles** — `HomeBehind`, `HomeRight`, `HomeLeft`, `Broadcast` — most pitches having 3–4 angles. This sub-project builds one reusable video tab and wires it into all three dashboards.

## 2. Goals

1. A single shared component: a clickable **pitch table** + a **single video player** with an **angle-toggle** button row (chosen from the confirmed layout options during brainstorming).
2. Wired into Hitting (**Video**), Pitching (**Pitch Level**), Catching (**Pitch Level**), each scoped to the already-selected subject and game.
3. Role scoping inherited from each dashboard's existing selector (coach = anyone, player = self only) — no new access logic.
4. Works for a single selected game **and** the existing "All games in range" selection.
5. Graceful empty states where a game/season has no video (only 37 games have clips; pre-2026 seasons have none).

## 3. Non-goals / Deferred

- Clip download, clip-list/CSV export, multi-pitch playlists.
- Playback controls beyond the native HTML5 `<video>` element (no custom slow-mo/frame-step; native `controls` is enough).
- Video for legacy (pre-2026) games — the warehouse has none.
- Caching. Per-selection query is sub-second (§3h recon); the video table is one lightweight query and clips load only on click.

## 4. Confirmed decisions (from brainstorming)

- **Player layout = single large player + an angle-toggle button row** (`HomeBehind / HomeRight / HomeLeft / Broadcast`). Buttons for angles missing on the selected pitch render disabled/greyed. (Chosen over two-up-legacy and two-up-plus-toggle.)
- **Default angle per dashboard:** Hitting → batter-side Home (RHH → `HomeRight`, LHH → `HomeLeft`); Pitching → `HomeBehind`; Catching → `HomeBehind`. Falls back to any available angle if the preferred one is absent.
- **Video queried on demand** (a tab/selection callback), not stuffed into the shared game-data store — keeps the tab decoupled.
- **"All games in range" is supported** in the table (paginated); clips load only on row-click, so a longer table is cheap.
- Player behaves like the legacy embed: native `controls`, `autoPlay`, `muted`, `loop`.
- S3 URLs are embedded directly (verified public: HTTP 200 + byte-range 206 for seeking). No signing/proxy.

## 5. Architecture

### 5a. Data layer — `app/data/video.py` (new)

```
pitch_video_df(game_id, *, batter_id=None, pitcher_id=None, catcher_id=None) -> pd.DataFrame
```
- Source: `vw_pitch_video v` JOIN `fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid`. The join supplies `catcher_id` (absent from both video views), `rel_speed`, `plate_loc_side/height`, `batter_side`, and the surrogate `game_id` used by the dashboards (verified matching).
- Filter to the game plus whichever subject id is passed. Exactly one of `batter_id / pitcher_id / catcher_id` is expected (module raises/guards otherwise). Subject filtering uses the existing **sibling-id union** helpers so split-id players still union (mirrors `game_pitches_for` / `wh_game_pitches`). `game_id` may be a single id or a list (to support the "All games in range" selection); when a list, all in-range games' pitches are unioned.
- **Angle pivot:** the raw join yields one row per (pitch, angle). Pivot to **one row per `pitch_uid`** with columns `url_homebehind, url_homeright, url_homeleft, url_broadcast` (NaN where an angle is missing).
- **Display columns** (one row per pitch): `pitch_no, inning, count` (`f"{balls}-{strikes}"`), `pitch_type` (`tagged_pitch_type`), `velo` (`rel_speed`, rounded), `result` (a friendly pitch_call/play_result, reusing pitching's `pretty_result` if suitable), `zone` (`izt_zone`), `batter_side`, `game_date`, plus the four url columns and `pitch_uid`.
- Sort: `game_date` desc, then `pitch_no`. Returns an **empty DataFrame with the full column set** when there is no video (so the UI renders a clean empty state, never errors).
- Pure data function (no `current_user`); unit-tested against the live DB (repo convention).

### 5b. Shared UI — `app/dashboards/video/` (new package)

- `constants.py` — `ANGLES = [("homebehind","Behind"), ("homeright","Home R"), ("homeleft","Home L"), ("broadcast","Broadcast")]`; url-column map; `DEFAULT_ANGLE` per module.
- `component.py`:
  - `render(df, *, prefix, default_angle) -> html.Div` — two columns: **left** = pitch `dash_table.DataTable` (native `row_selectable="single"` or `active_cell`, sortable, filterable, paginated ~15/page, styled to match existing tables); **right** = a player panel = an angle-toggle button row (`html.Button` per angle, disabled when that angle's url is missing for the selected pitch) above one `html.Video(controls autoPlay muted loop)`. Empty df → a centered "No video available for this game." Non-empty but no row selected → "Select a pitch to load its video." Component ids namespaced by `prefix` (e.g. `f"{prefix}-video-table"`, `f"{prefix}-video-player"`, `f"{prefix}-video-angle-store"`, `f"{prefix}-video-pitch-store"`, `f"{prefix}-video-angle-btn-{key}"`).
  - `register_callbacks(dash_app, prefix)` — (1) row-select → write the clicked pitch's four urls + `batter_side` into `{prefix}-video-pitch-store` and set the active angle to the resolved default; (2) angle-button click → set `{prefix}-video-angle-store`; (3) (pitch-store, angle-store) → the `<video>` `src` (+ enable/disable angle buttons per availability). Registered once per Dash instance with a unique prefix so the three apps never collide.
- Reason for a `register_callbacks(dash_app, prefix)` entry point: the three dashboards are **separate Dash instances** (`build_hitting_dash` / `build_pitching_dash` / `build_catching_dash`), so a shared component must let each app register its own copy of the callbacks under its own id prefix.

### 5c. Per-dashboard wiring

| Dashboard | Tab label (value) | Scope | Prefix | Default angle |
|---|---|---|---|---|
| Hitting (`app/dashboards/hitting/`) | **Video** (`video`) | `batter_id` = selected hitter | `hit` | batter-side Home |
| Pitching (`app/dashboards/pitching/`) | **Pitch Level** (`pitchlevel`) | `pitcher_id` = selected pitcher | `pit` | HomeBehind |
| Catching (`app/dashboards/catching/`) | **Pitch Level** (`pitchlevel`) | `catcher_id` = selected catcher | `cat` | HomeBehind |

For each: add the tab to the `dcc.Tabs`; add a branch in the dashboard's `_render_tab` that calls `video.pitch_video_df(...)` with the current `selection` store's game_id (single id or in-range list) + subject id, then `video.render(df, prefix=..., default_angle=...)`; call `video.register_callbacks(dash_app, prefix)` once in the dashboard's `build_*`/`register_callbacks`. No changes to the existing selectors — the resolved subject id already respects role scoping.

### 5d. Data flow

The video tab is self-contained: its render branch queries video for `(game_id(s), subject_id)` on tab open, and the row-select/angle callbacks operate purely on the rendered table + local stores. Nothing is added to the shared game-data store. If the selection is "All games in range", the render branch passes the in-range game_id list (already resolvable via the existing range/anchor logic each dashboard uses) to `pitch_video_df`.

## 6. Error handling & edge cases

- No video for the game/season → empty-state card (not an exception).
- A pitch with only some angles → missing-angle buttons disabled; default resolves to the first available angle.
- `rel_speed` / `izt_zone` NaN → rendered as "—" in the table (mirrors existing tables).
- Content-type on S3 is `binary/octet-stream`; the `<video>`/`<source>` sets `type="video/mp4"` so browsers play it.

## 7. Testing

- `tests/test_video.py` (live DB, matching existing `test_*` convention): `pitch_video_df` returns one row per pitch (angle pivot), the four url columns exist, subject filters (batter/pitcher/catcher) work, sibling union unions split ids, an in-range game list unions, and an empty game returns the full-column empty frame.
- Per-dashboard render smoke tests (in each dashboard's existing test file): the new tab value renders a Div containing a DataTable, a video element, and the angle-toggle buttons; empty df renders the empty state without error.

## 8. Rollout / verification

- Full pytest suite green (currently 314).
- Live smoke (both roles, in-process `create_app` per §3b to avoid disturbing any running 8050 server): hitting/pitching/catching each open the new tab, the table lists pitches for a game known to have video (e.g. a Spring 2026 game), row-click sets a playable `src`, angle toggle swaps it. Confirm a no-video game shows the empty state.

## 9. Notes / provisional

- "Result" friendly-label reuse: prefer pitching's existing `pretty_result`; if its mapping doesn't fit hitting/catching contexts, add a small local formatter (docstring'd, provisional).
- Default-angle mapping is a coach-confirmable preference (one constant per module, trivially changed).
- Only 37 games currently carry video; this is expected (S3 pipeline is Spring-2026-onward). The tab degrades gracefully for the rest.
