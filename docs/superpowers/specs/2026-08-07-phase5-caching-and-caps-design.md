# Phase 5 — In-process caching + round-trip reduction + chart crash-guard

**Date:** 2026-08-07
**Status:** Design approved (brainstorm). First Phase 5 slice, re-scoped from a fresh profile of the CURRENT app (post-precalc).

## Goal

Make tab/game navigation feel instant by attacking the **measured** dominant cost — RDS round-trips on the raw-CAPS data loads — and remove a latent crash on oversized chart inputs.

## Re-profile (2026-08-07, heaviest hitter 806253, post-precalc)

| call | time | nature |
|---|---|---|
| `sidebar_stats` (precalc 1-row) | **240 ms** | already fixed by Phase 4 |
| `game_pitches` (1 game, 24 rows) | 1220 ms | round-trips |
| `games_for_batter` | 1190 ms | round-trips |
| `season_pitches` (1094 rows) | 1470 ms | round-trips |
| `bip_points` (season) | 1190 ms | round-trips |
| `last_n_pas(27)` | 1720 ms | round-trips |
| `all_pas_figure` (game, 12-PA cap) | 327 ms | CPU (already capped) |
| `all_pas_figure` (uncapped season) | **crash** | 88-row `make_subplots` `ValueError` |

**Findings:** (1) The old "2.6s Plotly render" is stale — `all_pas_figure` is already 12-PA-capped in the tab. (2) The dominant cost is now round-trips: every load is ~1.2–1.7s, mostly network, and **each caps function redundantly re-runs `_sibling_ids`** (an extra ~500ms round-trip); a tab load fires ~5 of them. (3) An uncapped season df doesn't slow `all_pas_figure` — it *crashes* it.

## Design

Three levers, in value order.

### 1. Memoize the sibling-id resolvers (biggest cheap win)

`hitting_caps._sibling_ids`, `pitching_caps._sibling_pitcher_ids`, `catching_caps._sibling_catcher_ids` each issue a query and are called by nearly every read function. Memoizing them per player collapses a tab's ~5 identical sibling round-trips into 1 (~2s off a cold tab load). The sibling→id mapping is static within a data epoch (only changes when new games/players land), so a process-lifetime memo cleared on rebuild is correct.

### 2. In-process cache of the heavy CAPS read functions (instant repeats)

Cache the results of the ~1.2s read functions so repeat game/tab selections are 0-round-trip:
- hitting: `game_pitches`, `season_pitches`, `range_pitches`, `games_for_batter`, `bip_points`, `last_n_pas`
- pitching: `range_pitches_for`, `games_for_pitcher`, `game_pitches_for`, the velo/recent-outings reads
- catching: `game_pitches_for`, `range_pitches_for`, `games_for_catcher`

Not cached: the precalc readers (already 1-row fast) and scalar helpers.

**Mechanism — `app/data/cache.py`:**
- `@cached` decorator. Key = the call's positional args normalized to a hashable form (lists→tuples). DataFrame results are returned as a **`.copy()` on every hit** so a caller mutating the frame can't corrupt the cached copy (the ~ms copy is negligible vs a ~1.2s query). Non-DataFrame results returned as-is.
- Each decorated function registers its store in a module registry; `cache.clear_all()` empties them.
- `precalc.rebuild_*` calls `cache.clear_all()` at the end, so an in-process rebuild refreshes both precalc and the read cache.

**Invalidation scope (honest limitation):** the cache is per-process. In the dev server (single process, `use_reloader=False`) and any single-process run this is fully correct — a rebuild clears it. Under a future multi-worker prod server, a cron rebuild runs in a separate process and cannot clear the web workers' caches; those would serve cached CAPS reads until worker restart. **Acceptable now** (offseason: data is static, no new games until Fall 2026). When the cron lands, add cheap cross-process invalidation (a data-version stamp keyed into the cache) as part of that work — noted, not built here.

### 3. Defense-in-depth cap inside `all_pas_figure`

Independent of the tab's 12-PA cap, `all_pas_figure` itself caps to the most-recent `_MAX_PA_SUBPLOTS` (e.g. 12) PAs and never builds an 88-row subplot. This closes the crash for *any* caller (the "big requests can crash" class), belt-and-suspenders with the tab cap. No visible change for normal (already-capped) callers.

## Testing

- **Sibling memo:** two calls to `_sibling_ids(bid)` issue one query (patch `query_df` to count calls); `cache.clear_all()` re-arms it.
- **Read cache:** two `season_pitches(bid)` calls issue one query; results equal; mutating a returned frame doesn't affect the next call's result (copy-on-hit); `clear_all()` forces a re-query.
- **Key normalization:** list-arg functions (`bip_points(bid, [g1,g2])`) cache correctly (list normalized to tuple; a different list is a cache miss).
- **Rebuild invalidation:** `precalc.rebuild_hitting` leaves the read cache empty (calls `clear_all`).
- **Crash guard:** `all_pas_figure(season_df)` with >12 PAs returns a figure with exactly `_MAX_PA_SUBPLOTS` PAs and does not raise.
- Full suite stays green; return shapes unchanged.

## Out of scope

Pre-shaped one-row-per-pitch precalc tables (a separate slice — would cut the *first*-load round-trip further); Plotly render optimization (already adequate post-cap); the cross-process/cron cache invalidation (deferred with the cron build).

## Success criteria

A cold hitting tab load issues ~1 sibling round-trip instead of ~5; repeat game/tab selections in a session are ~instant (0 round-trips); `all_pas_figure` cannot crash on an oversized df; full suite green; live navigation visibly snappier.
