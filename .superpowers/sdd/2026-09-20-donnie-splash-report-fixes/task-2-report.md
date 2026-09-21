# Task 2 Report: Support Dual-Position Roster Classification

## Status

Implemented dual-position roster classification and updated Donnie Morgan's single 2026–2027 roster record.

## Changes

- Updated `app/data/lmu_roster.py`:
  - Added token-aware position parsing for `/`, `,`, and `&` separators.
  - Any `RHP` or `LHP` token classifies the row as `pitcher`.
  - Catcher classification remains available for `C` when no pitcher token exists.
  - All other, blank, and unknown values remain `hitter`.
  - Pitcher classification takes precedence for dual-position values such as `RHP/CF`.
- Updated `data/rosters/2026-2027.json`:
  - Changed only Donnie Morgan's existing record from `CF` to `RHP/CF`.
  - Kept his `JR` class year and name unchanged; no duplicate record was added.
- Updated tests:
  - Added `RHP/CF` and ordinary `CF` assertions to `tests/test_lmu_roster.py`.
  - Added an assertion that the real fixture contains exactly one Donnie Morgan row with position `RHP/CF` in `tests/test_load_lmu_roster.py`.

## Verification

Focused tests requested for this environment:

```text
python -m pytest tests/test_lmu_roster.py::test_position_group_mapping tests/test_load_lmu_roster.py::test_real_2026_2027_fixture_loads_47_players -q
..                                                                       [100%]
2 passed in 0.96s
```

Also ran:

```text
python -m pytest tests/test_lmu_roster.py tests/test_load_lmu_roster.py tests/test_splash_report_dash.py -q
```

This broader run reached the expected local database limitation: tests that access MySQL fail with `sqlalchemy.exc.OperationalError: Access denied for user 'ci'@'localhost'`. The non-database fixture/classification tests passed; the failures are unrelated to these changes and match the task's provided environment warning.

`git diff --check` passed.
