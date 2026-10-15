# Fixing a wrong/duplicate GAMES load — runbook

Two different problems both look like "the game data is wrong," but need
completely different fixes. Doing the wrong one either does nothing (the
cron silently ignores your fix) or leaves a duplicate that keeps coming back.
Work out which case you're in **first** (see the diagnostic below), then
follow that case's steps.

## Why you can't just re-upload a corrected file via FileZilla

The cron (`flask pipeline-load`, see `docs/pipeline-cron-runbook.md`) walks
the Trackman SFTP `/v3` tree and loads games via `app.ingest.games.load_games`.
That loader is **insert-only** and dedups per row on `PitchUID` (Trackman's
own per-pitch id, assigned at capture time): once a `PitchUID` exists in
`GAMES`, every later cron run just skips it, forever. It never updates or
deletes an existing row.

So if you edit a tag in Excel and upload the corrected CSV back into that
same SFTP tree, the `PitchUID`s haven't changed — cron will see they're
already loaded and skip every row. **Your correction never applies, and
nothing tells you that happened.** Corrections and duplicate removals are
both done as direct, deliberate script runs against the database — never by
putting a file back on the SFTP server and hoping cron does the right thing.

## Diagnostic: which case am I in?

Pull up both versions and compare `PitchUID`s for the game's date:

```sql
SELECT GameID, COUNT(*) AS n, MIN(Date) date_, GameType, HomeTeam, AwayTeam
  FROM GAMES WHERE Date = 'YYYY-MM-DD'
 GROUP BY GameID, GameType, HomeTeam, AwayTeam;
```

- **Same `PitchUID`s, just wrong values in a few columns** (wrong batter/
  pitcher name, wrong pitch type, wrong count/result) → it's the *same*
  pitches, mis-tagged. Go to **Case 1**.
- **Two different `GameID`s with disjoint `PitchUID` sets** for what's
  obviously the same physical game (e.g. one far shorter/incomplete, or no
  `GameType`/no video where the real one has both) → it's a genuine
  *duplicate load* from two different sources (manual upload vs. automated
  SFTP pull, or Trackman re-exporting the session under a new id). Go to
  **Case 2**.

Real example (2026-10-13 scrimmage): `20261013-LoyolaMarymount-Private-3`
(171 pitches, `GameType=Scrimmage`, video on every pitch — the correct
hand-uploaded camera file) and `20261013-LoyolaMarymount-Private-2` (8
pitches, no `GameType`, no video — an incomplete automated pull) had
**completely disjoint `PitchUID`s**. That was Case 2.

## Case 1 — same pitches, wrong tag (fix in Excel)

Safe by construction: cron can never undo this, because it only inserts
missing `PitchUID`s and these already exist.

1. In Excel, only edit the "correctable" columns (see
   `app.ingest.games.CORRECTABLE_COLS`): who threw/batted/caught, inning,
   count, pitch type/call/result. **Never edit `Time` or any
   tracking/velocity/movement column** — Excel can silently mangle a time
   value on save (e.g. `14:32:27.01` → `32:27.0`), and the script below
   deliberately ignores those columns so a bad save there can't corrupt good
   tracking data.
2. Save as CSV, keep it local (never re-upload it to the SFTP server).
3. Dry run (prints what would change, writes nothing):
   ```
   python scripts/load_game_csv.py "C:\path\to\corrected.csv" --correct
   ```
4. If it looks right, apply:
   ```
   python scripts/load_game_csv.py "C:\path\to\corrected.csv" --correct --apply
   ```
   This updates the matching `PitchUID`s' correctable fields in place and
   rebuilds the precalc rollups. Changes show up on the site within ~60s.

If the game hasn't been auto-loaded by cron yet, the same command (with or
without `--correct` — it's a no-op if nothing's loaded yet) just loads your
already-corrected file first; cron's later pull of the same `PitchUID`s is
then skipped as already-loaded, never duplicated.

## Case 2 — genuine duplicate load (different PitchUIDs/GameID)

This needs an actual delete, **plus** telling the loader to never re-insert
it — a delete alone just gets re-filled on the next cron run.

1. Dry run first (never skip this):
   ```
   python scripts/remove_game.py BAD_GAME_ID
   ```
   Confirms the pitch count/date/type you expect before anything is touched.
2. Apply:
   ```
   python scripts/remove_game.py BAD_GAME_ID --apply
   ```
   This deletes that `GameID`'s rows from `GAMES`, rebuilds precalc, **and**
   appends the `GameID` + its exact `PitchUID`s to the committed
   `data/excluded_games.json`. `load_games` checks both lists on every row
   going forward, so neither the main file nor a Trackman **sidecar** file
   for the same game (e.g. `..._playerpositioning_FHC.csv` — fielder
   positions, not pitch metrics, carries the same `PitchUID`s but no
   `GameID` column) can ever bring those rows back. This is why both
   `GameID` *and* `PitchUID` are recorded, not just `GameID`.
3. Commit `data/excluded_games.json` (and anything else the script touched)
   through the normal branch + PR flow — it's a reviewed code change like
   any other, not an ad hoc DB edit. See CLAUDE.md's rule against one-off
   writes to the shared DB; this script exists specifically so this kind of
   fix is reviewed, re-runnable code instead.
4. Before trusting it's actually fixed, dry-run the real cron entrypoint
   against live SFTP once more and confirm `inserted=0` for that game:
   ```
   flask --app run pipeline-load --dry-run --since-days 3
   ```
   (This is how the sidecar-file gap above was actually found — the first
   version of the exclude list only matched `GameID` and this dry run showed
   8 rows still slipping through from the sidecar file.)

## Reference

- `scripts/load_game_csv.py` — load/correct one local game CSV.
- `scripts/remove_game.py` — delete a bad `GameID`'s rows + register the
  exclusion.
- `app/ingest/games.py` — `excluded_game_ids()` / `excluded_pitch_uids()` /
  `CORRECTABLE_COLS`; `load_games()` is where both checks actually run.
- `data/excluded_games.json` — the committed, growing list of permanently
  blocked `GameID`s/`PitchUID`s. Entries should always include a `reason`.
- `docs/pipeline-cron-runbook.md` — what the daily cron itself does.
