# Per-pitch video clipping — process guide

Tool: `scripts/pitch_video_clips.py`. This doc is the checklist for actually
running it on a new game; the script's own module docstring has the
mechanical details (file formats, function contracts).

## Background — why this isn't a one-command job

Tested end-to-end on the 2026-05-15 @ USD game (HomeRight angle). Two
things make this harder than "ffmpeg -ss <timestamp>":

1. **`GAMES.Time`/`UTCDateTime`/`LocalDateTime` are NULL** for at least some
   games — the ingest loader drops them. The raw per-pitch CSV still on the
   Trackman SFTP server has real timestamps; `fetch-csv` pulls it. The
   folder there is keyed by **upload date, not game date** (the 05-15 game
   uploaded to the 05-16 folder) — `fetch-csv` already searches forward a
   few days to cover this, no manual folder-hunting needed.

2. **The camera's segment files don't hand off cleanly.** Recording splits
   into fixed-size files (~18 min / ~4GB observed, consistent with a
   FAT32-formatted card). A segment's file-close timestamp (mtime) is a
   reliable marker of when THAT segment ends, but there's a real, variable
   gap before the NEXT segment's first frame — confirmed by comparing a
   segment's last frame to the next segment's first: real game time passes
   that's on neither file. The size of that gap is unpredictable (we saw
   drift swing from +15.6s to -8.2s to +15.9s within a single 18-minute
   segment — not a constant, not even monotonic). **A single "correction
   offset" per segment does not work.** Piecewise-linear correction from
   real anchor points inside each segment does.

**First thing to check before doing any of this by hand**: whether the
camera/recording software can be reconfigured to avoid the segment split
entirely (exFAT card to remove the FAT32 4GB ceiling, or a "max clip
length" setting). If that's possible, most of this doc becomes unnecessary
— a single anchor per whole recording is enough when there's no file
rollover to introduce a gap. Worth asking whoever operates the camera
before assuming you need the full anchor process below.

## The workflow

### 1. Pull the timestamped CSV

```bash
python scripts/pitch_video_clips.py fetch-csv \
    --date 2026-05-15 --opponent UofSanDiego --game-num 2 \
    --out data/scratch/20260515-UofSanDiego-2.csv
```

`--opponent` must match the CSV filename exactly (check a FileZilla listing
if unsure — team names in there aren't always what you'd guess).

### 2. Build the anchors file

One JSON file per camera angle, anchors keyed by segment filename (see the
script's module docstring for the exact format). **You don't need a
perfectly-anchored segment to get clips out of it** — `clip` runs on
whatever you give it, down to a single anchor for a whole segment (even
zero: an un-anchored segment still gets naive, unshifted clips with wide
padding). What changes with fewer anchors is confidence, not coverage:
every pitch gets a clip either way, and `clip` prints a **flagged list** of
the pitches least likely to be right, so review effort goes only where it's
actually needed — mirroring how this worked before this tool existed: pick
the first pitch, let it process the whole game, fix the couple it flags.

Start with the minimum (one anchor per segment — even just the first pitch
of the whole recording, applied to segment 1 only) and only add more where
the flagged list is worth shrinking. More anchors per segment = smaller
flagged list = less to review by hand; it's a dial, not a requirement.

**How to find an anchor**: pick a pitch, watch the batter's front foot.
The moment it plants is the reliable tell that a pitch is arriving — this
works on *every* pitch, take or swing, unlike waiting for contact. Note the
video timestamp, look up that pitch's real Trackman time (from the CSV),
and you have one (nominal, true) pair.

**If you do want to add more anchors to shrink the flagged list, picking a
GOOD one is the actual skill** — this is what ate most of the time on the
test game:

- **Pick isolated plays**, not pitches in the middle of a busy stretch
  (back-to-back swings, a foul-ball scramble, a mound visit). Automated
  motion detection — and honestly, eyeballing it too — falls apart when
  multiple pitches' worth of action overlap in a short window. A good
  anchor has visible dead time on both sides: last pitch of a half-inning,
  first pitch after a pitching change, right after a clear break.
- **The first segment of a recording needs more anchors than the rest** —
  it looks like there's a startup/cold-start effect (untested why, but
  consistently the least predictable segment). Plan on 4-7 anchors spread
  through segment 1; 2 is usually enough for segments in the middle of a
  long recording, since drift there tends to be small and roughly linear
  between anchors.
- **Double-check which segment file you're actually looking at** before
  trusting a search window — a boundary-math slip (using one segment's end
  time as another's start) cost real time on the test game. `PitchUID` in
  the CSV cross-checked against `GAMES.PitchUID` is the reliable way to
  confirm you're looking at the right pitch.
- If two candidate moments in the video both look plausible for the same
  pitch and you can't tell them apart, that segment stretch just isn't
  anchor-able that way — pick a different, more isolated pitch nearby
  instead of guessing.

### 3. Cut the clips

```bash
python scripts/pitch_video_clips.py clip \
    --video-dir "F:\video" --angle-prefix "USD_5.15.2026_HomeRight_" \
    --csv data/scratch/20260515-UofSanDiego-2.csv --game-id 315 \
    --anchors data/scratch/homeright_anchors.json \
    --out-dir "F:\video\clips_HomeRight" \
    --pad-before 2 --pad-after 3
```

Every pitch in the game gets a clip — flagged or not. A pitch is flagged
when its segment has no anchor, has only one anchor (a flat constant-shift
assumption across the whole segment — real but unmeasured risk), is more
than 60s (nominal) from the nearest of 2+ anchors, or is in the first
segment of the recording (confirmed less predictable than later ones,
regardless of anchor count). Flagged pitches automatically get wider
padding (8s/10s instead of the 2s/3s default) as a safety margin. Add
`--flagged-out <path>` to also save that list as JSON for tracking which
ones still need a look.

### 4. Review the flagged list, spot-check the rest

The flagged list from step 3 is your punch list — that's the "couple
errors" to go fix by hand (re-anchor that pitch's segment and re-run, or
just widen that one clip). For everything else, spot-check a handful before
fully trusting the batch: pull a clip near each anchor and a couple from
mid-segment, confirm the pitch is actually in frame.
`ffmpeg -i <clip> -vf "fps=4,scale=400:225,drawtext=text='%{pts\:hms}',tile=..." -frames:v 1 out.jpg`
makes a quick timestamped contact-sheet for eyeballing without watching
full clips one at a time.

## What NOT to trust

- **Motion-energy-based auto-detection of anchors** (diffing frame content
  in a cropped catcher/batter region, looking for the biggest spike) works
  well for isolated, unambiguous swings and ball-in-play contacts, but
  produces false positives constantly in busy stretches and can't tell a
  real event from a decoy. Treat it as a fast first pass to narrow down a
  window, not a source of truth — confirm anything it finds by eye, and
  fall back to a human-verified front-foot check when it's ambiguous.
- **Motion-energy-based auto-validation of finished clips** — the tempting
  "let's just check the output instead of the input" idea, i.e. analyze a
  cut clip's pixels for "does something happen here" and flag it if not.
  Tried it, rejected it: a clip known to be wrong and a clip known to be
  right (a routine take — low visual contrast either way) scored nearly
  identically (1.40 vs 1.43 on a peak/baseline motion ratio). Confidence
  has to come from the timing math (`confidence_flag`), not the pixels.
- **Stream-copy (`-c copy`) trimming.** Keyframe-snapped seeks shift the
  actual clip start by up to a couple seconds — meaningless slop when the
  whole point is timing accuracy. `cut_clip` always re-encodes.
- **`np.interp`'s default clamping behavior** past the first/last anchor —
  it silently returns the same position for every pitch beyond your last
  anchor instead of extrapolating. `build_corrector` handles this; don't
  swap in a bare `np.interp` call without it.
