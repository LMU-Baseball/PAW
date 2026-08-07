# Video Slice — CAPS Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire `app/data/video.py` off the warehouse (`vw_pitch_video ⋈ fact_tm_game_pitch`) onto CAPS (`video_clips ⋈ GAMES` on `PitchUID`), so video is the last module cut over and the `tm_*` warehouse can be dropped in Phase 3.

**Architecture:** `video_clips` (base table — survives the drop) supplies the clip record (`angle`, `s3_url`, `game_date`); `GAMES` supplies every pitch-metadata column, joined on `PitchUID`. The downstream pandas transform in `pitch_video_df` is preserved verbatim by aliasing GAMES CamelCase columns to the snake_case names that transform already consumes (`izt_zone`, `rel_speed`, `batter_side`, etc.). The batter sibling resolver is repointed from the warehouse oracle `hitting_wh._sibling_ids` to `hitting_caps._sibling_ids` (identical signature/return). Pitcher/catcher resolvers already point at `pitching_caps`/`catching_caps`.

**Tech Stack:** Python, SQLAlchemy (`app.db.query_df`, `:named` params), pandas, pytest (live-DB tests).

## Global Constraints

- **Return shapes are the contract.** `pitch_video_df`, `games_with_video`, and `video_game_ids` keep their exact signatures and output columns (`video._ALL_COLS`). Dashboards (hitting/pitching/catching layout+callbacks) call them unchanged.
- **No prod writes.** This slice is read-only code; no DB mutation, no ingest.
- **Join key is `PitchUID`** — GAMES CamelCase `PitchUID` == `video_clips.pitch_uid`. Recon (2026-08-07): all 38,055 clips / 11,562 pitch_uids join GAMES 100%; all carry BatterId/PitcherId/CatcherId.
- **Subject id space is RAW trackman ids** for all three subjects (== `GAMES.BatterId`/`PitcherId`/`CatcherId`), matching the post-cutover dashboards/report.
- **`GAMES.GameID` is a surrogate int stored as TEXT.** Pass game-id filter params as `str` to match; return `int(GameID)`.
- **Keep the full suite green** (669 as of `74c6006`). The one deliberate warehouse dependency left in tests is the Phase-3-scoped parity oracle (Task 1), clearly marked for deletion.

---

### Task 1: Rewrite `video.py` to read CAPS, driven by a source-guard + parity test

**Files:**
- Modify: `app/data/video.py` (module docstring; `_sibling_ids` `given` table; the two SQL blocks in `games_with_video` and `pitch_video_df`; the `games_with_video` return column name)
- Test: `tests/test_video.py` (add `test_video_source_is_caps_only` + `test_parity_caps_matches_warehouse_oracle`; update the 2 `col ==` assertions)

**Interfaces:**
- Consumes: `hitting_caps._sibling_ids(batter_id) -> list[int]` (raw GAMES.BatterId siblings); `pitching_caps._sibling_pitcher_ids(pid) -> list[int]`; `catching_caps._sibling_catcher_ids(cid) -> list[int]` (both already used here). `app.db.query_df`.
- Produces: unchanged public API — `pitch_video_df(game_id, *, batter_id|pitcher_id|catcher_id) -> DataFrame[_ALL_COLS]`; `games_with_video(game_ids, *, subject) -> set[int]`; `video_game_ids(games_df, **subject) -> set`. `_sibling_ids(...)` now returns the GAMES column name (`"BatterId"`/`"PitcherId"`/`"CatcherId"`) instead of the fact column name.

- [ ] **Step 1: Write the failing source-guard test + the parity oracle test**

Append to `tests/test_video.py`:

```python
def test_video_source_is_caps_only():
    """After the CAPS cutover, video.py must not reference any warehouse
    object. This is the Phase-3 unblocker: video is the last module off tm_*."""
    import inspect
    from app.data import video as _v
    src = inspect.getsource(_v)
    for forbidden in ("vw_pitch_video", "fact_tm_game_pitch", "hitting_wh"):
        assert forbidden not in src, f"video.py still references {forbidden}"


def test_parity_caps_matches_warehouse_oracle(sample):
    """CAPS output == the old warehouse path, row-for-row, for each subject.

    The oracle SQL below is the pre-migration query; it is deliberately the
    LAST warehouse dependency in the video tests and is deleted in Phase 3
    together with tm_*/vw_pitch_video.
    """
    import pandas as pd
    from app.db import query_df
    for subj_col, subj_kw, sib_val in [
        ("batter_tm_id", "batter_id", sample["batter_tm_id"]),
        ("pitcher_tm_id", "pitcher_id", sample["pitcher_tm_id"]),
        ("catcher_tm_id", "catcher_id", sample["catcher_tm_id"]),
    ]:
        oracle_uids = set(query_df(
            f"""
            SELECT DISTINCT v.pitch_uid
              FROM vw_pitch_video v
              JOIN fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid
             WHERE f.game_id = :g AND f.{subj_col} = :s
            """,
            {"g": sample["game_id"], "s": sib_val},
        )["pitch_uid"])
        new_df = video.pitch_video_df(sample["game_id"], **{subj_kw: sib_val})
        assert set(new_df["pitch_uid"]) == oracle_uids
```

Also update the two existing regression assertions to the new GAMES column names:
- in `test_sibling_ids_pitcher_uses_raw_column_and_pitching_caps`: `assert col == "PitcherId"`
- in `test_sibling_ids_catcher_uses_raw_column_and_catching_caps`: `assert col == "CatcherId"`

- [ ] **Step 2: Run the tests to verify the guard fails**

Run: `pytest tests/test_video.py::test_video_source_is_caps_only tests/test_video.py::test_sibling_ids_pitcher_uses_raw_column_and_pitching_caps -v`
Expected: `test_video_source_is_caps_only` FAILS (`video.py still references vw_pitch_video`); the pitcher-col test FAILS (`col == "pitcher_tm_id"`, not `"PitcherId"`).

- [ ] **Step 3: Rewrite the module docstring + `_sibling_ids` mapping**

Replace the module docstring (lines 2-7) with:

```python
"""Pitch-level video: one row per pitch with the four camera-angle S3 URLs.

Source = video_clips (base table: pitch_uid/angle/s3_url/game_date, S3 .mp4
urls) joined to GAMES on PitchUID for the pitch metadata (velo, plate zone,
count, result, batter side) and the surrogate GameID. Fully on CAPS -- no
warehouse (vw_pitch_video / fact_tm_game_pitch) dependency, so video survives
the tm_* drop.
"""
```

In `_sibling_ids`, change the `given` table so it returns GAMES column names and resolves the batter branch via `hitting_caps` (not the warehouse oracle `hitting_wh`):

```python
    given = [("BatterId", batter_id, "app.data.hitting_caps", "_sibling_ids"),
             ("PitcherId", pitcher_id, "app.data.pitching_caps", "_sibling_pitcher_ids"),
             ("CatcherId", catcher_id, "app.data.catching_caps", "_sibling_catcher_ids")]
```

Update the `_sibling_ids` docstring lines that say "matched against fact ... RAW `pitcher_tm_id`/`catcher_tm_id` column" to name the GAMES columns (`GAMES.PitcherId`/`GAMES.CatcherId`) instead; drop the surrogate-column caveats (there is no surrogate column anymore).

- [ ] **Step 4: Rewrite the `games_with_video` query**

Replace the `query_df(...)` block in `games_with_video` (currently the `vw_pitch_video v JOIN fact_tm_game_pitch f` SELECT of `f.game_id`) with:

```python
    params = {f"g{i}": str(g) for i, g in enumerate(gids)}
    params.update({f"s{i}": s for i, s in enumerate(sib)})
    df = query_df(
        f"""
        SELECT DISTINCT g.GameID
          FROM video_clips v
          JOIN GAMES g ON g.PitchUID = v.pitch_uid
         WHERE g.GameID IN ({gph}) AND g.{subj_col} IN ({sph})
        """,
        params,
    )
    return set() if df.empty else {int(g) for g in df["GameID"]}
```

(Note: `params` for `g*` now stringifies the game ids to match the TEXT `GameID` column; the return reads column `GameID` instead of `game_id`.)

- [ ] **Step 5: Rewrite the `pitch_video_df` query**

In `pitch_video_df`, change the game-id params to strings and replace the `raw = query_df(...)` block (the `vw_pitch_video v JOIN fact_tm_game_pitch f` SELECT) with:

```python
    params = {f"g{i}": str(g) for i, g in enumerate(gids)}
    params.update({f"s{i}": s for i, s in enumerate(sib)})

    raw = query_df(
        f"""
        SELECT v.pitch_uid, g.PitchNo AS pitch_no, g.Inning AS inning,
               g.Balls AS balls, g.Strikes AS strikes,
               g.TaggedPitchType AS tagged_pitch_type, g.PitchCall AS pitch_call,
               g.PlayResult AS play_result, v.game_date,
               v.angle, v.s3_url,
               g.RelSpeed AS rel_speed, g.Zone AS izt_zone,
               g.BatterSide AS batter_side
          FROM video_clips v
          JOIN GAMES g ON g.PitchUID = v.pitch_uid
         WHERE g.GameID IN ({gph}) AND g.{subj_col} IN ({sph})
        """,
        params,
    )
```

Everything below (`if raw.empty`, the pivot, `meta`, the display-frame build, the sort, `return df[_ALL_COLS]`) is UNCHANGED — the aliases (`izt_zone`, `rel_speed`, `batter_side`, `pitch_no`, `game_date`, `tagged_pitch_type`, `pitch_call`, `play_result`) match the names that block already reads.

- [ ] **Step 6: Run the video suite to verify green**

Run: `pytest tests/test_video.py -v`
Expected: ALL pass — the source-guard, the parity test (CAPS == warehouse oracle for batter/pitcher/catcher), the updated `col ==` assertions, and every pre-existing behavioral test.

- [ ] **Step 7: Commit**

```bash
git add app/data/video.py tests/test_video.py
git commit -m "feat(video-caps): read video_clips ⋈ GAMES; drop warehouse dep (batter siblings → hitting_caps)"
```

---

### Task 2: Repoint the live-DB test fixture off the warehouse

**Files:**
- Test: `tests/test_video.py` (the `sample` fixture, lines 10-32)

**Interfaces:**
- Consumes: `video_clips`, `GAMES`.
- Produces: `sample` dict `{game_id:int, pitcher_tm_id:int, batter_tm_id:int, catcher_tm_id:int}` — same keys as today, so every test consuming `sample` is unaffected. (Keys keep the `_tm_id` names to minimize churn; the values are raw GAMES ids, which they already were.)

- [ ] **Step 1: Verify the fixture is the only remaining warehouse reader in the file (besides the marked parity oracle)**

Run: `grep -n "vw_pitch_video\|fact_tm_game_pitch" tests/test_video.py`
Expected: matches only in the `sample` fixture and in `test_parity_caps_matches_warehouse_oracle`.

- [ ] **Step 2: Rewrite the `sample` fixture to source from CAPS**

Replace the fixture body's `query_df(...)` (the `vw_pitch_video v JOIN fact_tm_game_pitch f` SELECT) with a CAPS query that finds one videoed game with a pitch carrying all three raw subject ids:

```python
    row = query_df(
        """
        SELECT g.GameID AS game_id, g.PitcherId AS pitcher_tm_id,
               g.BatterId AS batter_tm_id, g.CatcherId AS catcher_tm_id
          FROM video_clips v
          JOIN GAMES g ON g.PitchUID = v.pitch_uid
         WHERE g.CatcherId IS NOT NULL AND g.BatterId IS NOT NULL
           AND g.PitcherId IS NOT NULL
         LIMIT 1
        """
    ).iloc[0]
    return dict(game_id=int(row["game_id"]), pitcher_tm_id=int(row["pitcher_tm_id"]),
                batter_tm_id=int(row["batter_tm_id"]), catcher_tm_id=int(row["catcher_tm_id"]))
```

Update the fixture docstring to say it selects from `video_clips ⋈ GAMES` (raw GAMES ids), dropping the vw_pitch_video/fact wording.

- [ ] **Step 3: Run the full video suite**

Run: `pytest tests/test_video.py -v`
Expected: ALL pass (the parity oracle is now the sole warehouse reference remaining, by design).

- [ ] **Step 4: Commit**

```bash
git add tests/test_video.py
git commit -m "test(video-caps): source sample fixture from video_clips ⋈ GAMES (warehouse-free except parity oracle)"
```

---

## Post-plan verification (not a task — the reviewer/executor runs these)

- Full suite: `pytest -q` → expect 671 (669 + the 2 new video tests) green.
- Live both-role smoke: coach + player, all 3 game dashboards → Video / Pitch Level tab renders clips; game dropdown shows the 🎥 marker on videoed games.
- Confirm the ONLY remaining app-code warehouse references are the Phase-3 parity oracles: `grep -rln "vw_pitch_video\|fact_tm_game_pitch\|dim_tm_game\|tm_player\|tm_team" app/` should return only `hitting_wh.py`, `pitching.py`, `catching.py` (the retained oracles) — `video.py` gone from the list. This is the green light for Phase 3.

## Self-review notes

- **Spec coverage:** Program spec rock #1 ("recreate the vw_pitch_video join against GAMES on PitchUID") = Task 1 queries. The memory NEXT-ACTION (a) extra ask — "drop vw_pitch_video/fact dependency so video survives the tm_* drop" — = `test_video_source_is_caps_only` guard + the docstring. Batter-resolver repoint off `hitting_wh` (Phase-3 unblocker surfaced in recon) = Task 1 `given` table.
- **Placeholder scan:** none — all SQL and code is literal.
- **Type consistency:** `_sibling_ids` returns `(col:str, ids:list[int])` throughout; game-id params stringified in both queries; return column `GameID` read consistently.
