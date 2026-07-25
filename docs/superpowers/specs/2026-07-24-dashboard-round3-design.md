# Dashboard Round 3 Design

**Date:** 2026-07-24
**Branch:** `feat/dashboard-polish-pass` (continues the polish pass)
**Status:** Design approved; proceeding to plan.

## Summary

A third refinement round from coach review of the running app. One real feature
(per-game coach notes on all three game dashboards) plus four UI tweaks (catching
legends/filters, hitting pitch-color consistency, batted-ball fan sizing).

**Scope:** the three game dashboards (`hitting`, `pitching`, `catching`) + the
HitTrax practice `charts.py`. Adds one app-DB table; no analytics-RDS schema
change; no new dependency.

## Decisions locked with the coach

- Notes live on **all three** game dashboards (hitting + pitching + catching);
  **coach** adds/edits/deletes, **player** reads.
- Notes stored in the **app SQLite DB** (`instance/paw_app.db`), not the analytics
  RDS.
- Hitting's existing in-tab "Coach Note" **moves** to a persistent card above the
  tabs, shared by all three dashboards.
- Static Framing gets the **Stolen/Lost/Correct chips** (filtering all four facet
  plots) and its right-side **legend removed**, mirroring Overall Framing.

## A. Per-game coach notes (shared, all three game dashboards)

### Data model + helpers (`app/data/notes.py`, new)
- `GameNote(db.Model)`: `id` (pk), `module` (str: "hitting"|"pitching"|"catching"),
  `subject_id` (int: the dashboard's player id — batter/pitcher/catcher), `game_id`
  (int, warehouse game id), `text` (Text), `author_id` (int, nullable), `updated_at`
  (DateTime). Unique constraint on `(module, subject_id, game_id)`.
- Helpers: `get_note(module, subject_id, game_id) -> str` (""/absent → ""),
  `upsert_note(module, subject_id, game_id, text, author_id) -> None` (insert or
  update; empty/whitespace text deletes), `delete_note(module, subject_id, game_id)`.
- `create_app` imports `app.data.notes` before `db.create_all()` so the table is
  created (idempotent; matches the existing `from app.auth import models` pattern).

### Shared UI (`app/dashboards/notes_ui.py`, new)
- `note_card(module) -> html.Div` — a container `html.Div(id=f"{module}-note-card")`
  placed once in each layout (populated by callback). Persistent above the tabs.
- `register_note_callbacks(dash_app, module, subject_key)`:
  - **render**: `Input("selection","data")` → `Output(f"{module}-note-card","children")`.
    Reads `subject = sel[subject_key]`, `game = sel["game_id"]`. If `game` is the
    range sentinel (`dr.ALL_IN_RANGE`) or `None`/no subject → a muted hint
    ("Select a single game to add a note."). Otherwise, coach → a labeled
    `dcc.Textarea(id=f"{module}-note-text")` prefilled with `get_note(...)` + Save
    (`{module}-note-save`) + Delete (`{module}-note-delete`) buttons +
    status Div (`{module}-note-status`); player → read-only note text (or "No note
    for this game.").
  - **save**: `Input(save.n_clicks)` + `State(text.value, selection)` →
    coach-gated `upsert_note` → `Output(status,"children")` = "Saved." Ignored (no
    write) when `current_user` is not a coach or game is a range/None.
  - **delete**: `Input(delete.n_clicks)` + `State(selection)` → coach-gated
    `delete_note` → clears the textarea (`Output(text,"value")=""`) + status
    "Deleted."
  - Inner ids are created dynamically by the render callback; the app already runs
    with `suppress_callback_exceptions`, so save/delete callbacks bind fine.
- `module`/`subject_key`: `("hitting","batter_id")`, `("pitching","pitcher_id")`,
  `("catching","catcher_id")`.

### Wiring
- Each `serve_layout` inserts `notes_ui.note_card(module)` between the selector row
  and the tabs; each dashboard's `register_callbacks` (or `build_*`) calls
  `notes_ui.register_note_callbacks(...)`.
- Hitting: `game_level.render` drops its in-tab Coach Note block (and the now-unused
  `note` param usage); `_render_tab` "game" branch no longer passes a note.

## B. Catching — Overall Framing legend off

`charts.framing_scatter` sets `showlegend=False` (chips are the key). No other
change to that tab.

## C. Catching — Static Framing chips + legend off

- `charts.framing_facets` turns its legend off (`fig.update_layout(showlegend=False)`).
- `tabs/static_framing.py`: add a call-type chip row (`static-call-chip` buttons,
  `static-call-active` store, reusing `charts.CALLTYPE_COLORS` and the
  `_CALL_ORDER`), and split render into `body(df, active_calls)` (filters
  `add_framing_cols(df)` by `CallType.isin(active_calls)` before faceting) + a
  `render` that shows the chips + `html.Div(id="static-body", children=body(df))`.
- Catching `register_callbacks`: add `_static_call_toggle`, `_static_body`, and
  `_static_call_styles` (mirror the existing `call-*` trio, prefix `static-call`).

## D. Hitting — pitch-color consistency

- `app/dashboards/hitting/charts.py::color_for` delegates to
  `app.data.pitching.pitch_color` (single source of truth). The local `PITCH_COLORS`
  is repointed to `pitching.PITCH_COLORS` (or removed if unused elsewhere). This
  changes the hitting zone/PA scatter colors to match the pitching palette (e.g.
  ChangeUp orange→purple, Cutter orange→green).
- `app/dashboards/hitting/tables.py::stat_table` gains optional `color_col`
  (default `"TaggedPitchType"`) — when present, adds `style_data_conditional`
  coloring that column's text per `pitching.pitch_color`; no-op when absent. The PA
  table (which carries `TaggedPitchType`) is thus colored to match the scatter.

## E. Batted Ball fan sizing + labels

In `charts.spray_distribution_fan`:
- x-range `[-P.FAN_DISPLAY_MAX, P.FAN_DISPLAY_MAX]` → `[-340, 340]` to match the
  landing scatter's scale (the fan content — max radius 440 at center, ±311 at the
  corners — still fits; y-range unchanged at `[-20, FAN_DISPLAY_MAX+20]`).
- The infield-ring `%` annotations overlap near home plate; floor the label radius
  so they spread outward: `label_r = max((r0+r1)/2, 108.0)` (only affects the
  innermost ring; outer rings' midpoints already exceed the floor).

## Testing

Repo conventions (pure helpers → unit tests; Dash render/UI → render + structural
tests; live-DB tests unguarded).

- **Notes model/helpers:** against a temp SQLite app DB (like `test_auth.py`'s
  fixture): `upsert_note` inserts then updates the same `(module,subject,game)`;
  `get_note` returns "" when absent; empty text deletes; `delete_note` removes.
- **Notes UI:** `note_card` returns a Div with the module-prefixed id;
  `register_note_callbacks` binds without error; coach render yields a Textarea +
  Save/Delete, player render is read-only, range/None game yields the hint.
- **Catching:** `framing_scatter` `showlegend` False; `framing_facets` `showlegend`
  False; `static_framing.body(df, ["Stolen Strike"])` filters and renders; chip row
  present.
- **Hitting:** `color_for("ChangeUp") == pitching.pitch_color("ChangeUp")`;
  `stat_table` colors the `TaggedPitchType` column and no-ops without it.
- **Fan:** `spray_distribution_fan` x-range is `[-340,340]`; an infield-ring
  annotation sits at radius ≥ 108.
- Full suite green (currently 297). All three dashboards still mount. Live smoke
  both roles; restart 8050 by port owner.

## Files touched

- New: `app/data/notes.py`, `app/dashboards/notes_ui.py`.
- `app/__init__.py` — import notes model before `create_all`.
- `app/dashboards/{hitting,pitching,catching}/layout.py` — insert the note card.
- `app/dashboards/{hitting,pitching,catching}/callbacks.py` (or `__init__` build) —
  register note callbacks; catching also gets the static-framing chip callbacks;
  hitting `_render_tab` drops the note arg.
- `app/dashboards/hitting/tabs/game_level.py` — remove in-tab note block.
- `app/dashboards/hitting/charts.py` — `color_for` delegates to pitching.
- `app/dashboards/hitting/tables.py` — colored `TaggedPitchType` column.
- `app/dashboards/catching/charts.py` — `framing_scatter` + `framing_facets`
  legends off.
- `app/dashboards/catching/tabs/static_framing.py` — chips + body split.
- `app/dashboards/hitting_practice/charts.py` — fan x-range + label floor.
- `tests/` — additions per above.

## Non-goals

- Note history/versioning (single current note per game).
- Notes on the range/aggregate ("All games in range") view.
- Rich text (plain text only).
