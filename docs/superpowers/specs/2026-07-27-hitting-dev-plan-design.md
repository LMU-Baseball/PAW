# Design: Hitting Development Plan Tab (Sub-project D)

**Date:** 2026-07-27
**Branch:** `feat/pitch-level-video` (deferred-tabs build; V + H + P already on this branch)
**Status:** Approved for implementation (user, 2026-07-27 — build straight through after specs)
**Part of:** V → H → P → **D (this)** — the final deferred-tab sub-project.

---

## 1. Motivation

The legacy hitter app (`src/app 1`) had a **"PD Plans"** tab that embedded a per-player Google-Sheet/Drive **player-development plan** (URL stored in the old `PLAYERS.PDPlan` column, shown in an iframe). PAW has deliberately moved off the external R-app documents into one unified in-app experience, and it already has a coach-notes system (per-game `GameNote` table + `notes_ui`). The modern equivalent of the PD Plans tab is a **per-player, coach-authored Development Plan stored in the app DB** — coach writes/edits it, player reads it — with no external-document or CSP coupling.

**Decision (recorded):** build the in-app authored plan (not an embedded external Google doc). It reuses the proven notes pattern, keeps everything inside PAW, and avoids embedding third-party iframes. If the coaches specifically want their existing Google-Drive docs surfaced instead, that is a small later pivot (swap the textarea for a stored URL + iframe); noted as the alternative.

## 2. Architecture

### 2a. Data — `app/data/dev_plans.py` (new; mirrors `app/data/notes.py`)
A `DevPlan` app-DB model keyed by **(module, subject_id)** — one plan per player per module (no game_id):
- Columns: `id`, `module` (String16), `subject_id` (Int), `text` (Text, default ""), `author_id` (Int, nullable), `updated_at` (DateTime, nullable); unique constraint on (module, subject_id).
- Functions: `get_plan(module, subject_id) -> str`, `upsert_plan(module, subject_id, text, author_id=None) -> None` (empty/whitespace text deletes), `delete_plan(module, subject_id) -> None`. Same null-guard semantics as `notes.py`.
- Registered for `create_all` by adding `from app.data import dev_plans  # noqa` beside the existing `notes` import in `app/__init__.py` create_app (before `db.create_all()`).

### 2b. Tab — `app/dashboards/hitting/tabs/dev_plan.py` (new; mirrors `notes_ui._render_note`)
`render(subject_id, is_coach) -> html.Div`:
- `subject_id is None` → "Select a hitter." prompt.
- **Coach:** a header, a `dcc.Textarea(id="devplan-text")` prefilled with the current plan, **Save** (`devplan-save`) + **Delete** (`devplan-delete`) buttons, and a status `html.Span(id="devplan-status")`.
- **Player:** a header + the plan text read-only (or "No development plan yet.").
Styled like the coach-note card (crimson header, italic box, Teko).

### 2c. Wiring — `app/dashboards/hitting/{layout,callbacks}.py`
- New tab: `dcc.Tab("Dev Plan", value="devplan")` (after the Last 27 PA tab).
- `_render_tab` branch (top, reads `sel` + `current_user`, like the video branch): `devplan` → `dev_plan.render(sel.get("batter_id"), is_coach)`. Works even when the player has no games loaded (plan is per-player, not per-game).
- Two callbacks in `register_callbacks` (coach-gated, keyed on `selection.batter_id`):
  - `_devplan_save(n, text, sel)` → `upsert_plan("hitting", bid, text, current_user.id)`; returns "Saved."/"Deleted."
  - `_devplan_delete(n, sel)` → `delete_plan(...)`; clears the textarea + status.

## 3. Access model
- Coach: read + write (edit/save/delete). Player: read-only. Enforced by `current_user.is_coach` in `render` and both callbacks (mirrors `notes_ui`). The `subject_id` comes from the already role-scoped `selection` store, so a player only ever sees their own plan.

## 4. Error handling / edge cases
- No plan yet → empty textarea (coach) / "No development plan yet." (player).
- Whitespace-only save → deletes the plan (same as notes).
- `subject_id` None → prompt, no DB call.

## 5. Testing
- `tests/test_dev_plans.py` (app-DB, mirrors `tests/test_notes.py`): get default "", upsert→get, update-in-place (no duplicate row), whitespace deletes, keyed by (module, subject_id), None subject is a no-op.
- `tests/test_hitting_dash.py` additions: the tab appears in `serve_layout`; `dev_plan.render(None, False)` → prompt; coach render contains `devplan-text`/`devplan-save`; player render is read-only (no `devplan-text`).

## 6. Out of scope / deferred
- Embedding external Google-Drive/Sheets documents (the legacy mechanism) — noted as the alternative if coaches request it.
- Rich-text/versioning/attachments — plain text only, matching the notes feature.
- Dev-plan tabs on pitching/catching (hitting only for now; trivial to extend later via the same `dev_plans` module with a different `module` key).
