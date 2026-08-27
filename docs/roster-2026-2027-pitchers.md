# 2026/2027 pitching roster — name list (2026-08-26)

**Why this exists:** Brad supplied these 24 pitcher names ahead of the fall
season, but there is no LMU athletics roster page to scrape this year (see
`scripts/scrape_roster_media.py`). PAW has no separate "declared roster" table
— every player (and their numeric id in `instance/roster_media.json`) exists
only once real Trackman/HitTrax data is ingested for them
(`app/data/pitching_caps.py::lmu_pitchers`, `app/data/bullpen.py`). So this
list can't populate anything in the app yet; it's here so that once Fall-2026
bullpen/game data starts landing, the new ids that appear can be sanity-checked
against these expected names, and so we know at a glance who still needs a
jersey number + photo in `instance/roster_media.json` once available.

## Returning pitchers — already in `instance/roster_media.json`

| Name | PitcherId | Jersey |
|---|---|---|
| Niko Riera | 822321 | 21 |
| Caleb Sweeney | 1000256215 | 13 |
| Matt Champion | 1000072225 | 26 |
| Alec Johnson | 10927439 | 31 |
| Max Schneider | 1000342941 | 12 |
| Johnny Casale | 832463 | 9 |
| Matt Moreno | 1000170776 | 0 |
| Adam Behrens | 823008 | 24 |
| Eric Erdmann | 1000196545 | 22 |

## New pitchers — no id yet, will appear once Trackman/HitTrax data is ingested

- Andrew Phillips
- Blake Killinger
- Colton Landen
- Will Kaczynski
- Ryan Bresaw
- Branson Wade
- Braden Burness
- Charlie Ushijima
- Corbin Giesen
- Lucas Geren
- Gavin Jacobsen
- Donnie Morgan
- Ari Silva
- Cole Stucky
- Holden Newhouse

**Once data starts flowing:** cross-check the pitcher names that show up in
`GAMES`/`BULLPEN` against this list (typos, nickname mismatches). For each new
name above, once a jersey number + photo is available, add an entry to
`instance/roster_media.json` keyed by their real `PitcherId` (see existing
entries for the format) — until then `pitching_caps.pitcher_profile` will show
blank jersey/photo for them, which is the existing documented degrade-gracefully
behavior in `app/data/roster_media.py`, not a bug.
