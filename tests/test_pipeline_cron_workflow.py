"""Guard the pipeline-cron workflow's cron <-> job-gating contract.

`on.schedule` is workflow-level in GitHub Actions, so all three crons fire the
whole workflow and each job decides for itself whether to run by comparing
`github.event.schedule` against a literal cron string. That coupling is the
easiest way to break this workflow (see docs/PIPELINE_CRON.md, "Changing a
schedule"): edit a cron in the `on:` block without updating the job condition
that matches it and the job silently stops running -- no failure, no email, just
a run where it is skipped.

These tests fail loudly instead. They parse the real workflow file, so they also
cover anyone hand-editing the YAML.
"""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # not a production dep; skip if unavailable

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/pipeline-cron.yml"

GAMES_SLOT = "30 9 * * *"
BULLPEN_EVENING = "0 4 * * *"
BULLPEN_MORNING = "0 16 * * *"


@pytest.fixture(scope="module")
def wf():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1).
    doc["triggers"] = doc[True] if True in doc else doc["on"]
    return doc


@pytest.fixture(scope="module")
def crons(wf):
    return [c["cron"] for c in wf["triggers"]["schedule"]]


def _fires(condition: str, *, event: str, schedule=None) -> bool:
    """Evaluate the subset of GitHub expression syntax these conditions use."""
    expr = condition.replace("github.event_name", repr(event))
    expr = re.sub(r"github\.event\.schedule",
                  repr(schedule) if schedule is not None else "None", expr)
    return eval(expr.replace("||", " or ").replace("&&", " and "))  # noqa: S307


def _conditions(wf) -> dict:
    return {name: (body.get("if") or "") for name, body in wf["jobs"].items()}


# --- the contract ----------------------------------------------------------

def test_every_cron_triggers_at_least_one_job(wf, crons):
    """An orphan cron is a scheduled run that does nothing -- pure waste, and a
    sign someone changed a cron string without its `if:`."""
    for cron in crons:
        fired = [n for n, c in _conditions(wf).items()
                 if _fires(c, event="schedule", schedule=cron)]
        assert fired, (
            f"cron {cron!r} fires no job -- its `if:` condition was not updated "
            "to match (see docs/PIPELINE_CRON.md, 'Changing a schedule')")


def test_every_job_is_reachable_by_some_cron(wf, crons):
    """The silent-stop failure this whole contract exists to prevent."""
    for name, cond in _conditions(wf).items():
        assert any(_fires(cond, event="schedule", schedule=c) for c in crons), (
            f"job {name!r} can never run on a schedule -- no cron in `on:` "
            f"matches its `if:` condition {cond!r}")


def test_job_conditions_only_reference_declared_crons(wf, crons):
    """The other direction: an `if:` naming a cron that no longer exists in the
    `on:` block is dead code and the job is (partly) unreachable."""
    for name, cond in _conditions(wf).items():
        for referenced in re.findall(r"github\.event\.schedule\s*==\s*'([^']+)'", cond):
            assert referenced in crons, (
                f"job {name!r} gates on cron {referenced!r}, which is not in the "
                f"`on.schedule` list {crons}")


def test_manual_dispatch_still_runs_every_job(wf):
    """A manual 'Run workflow' must remain a full run -- that is how the whole
    pipeline gets verified on demand."""
    for name, cond in _conditions(wf).items():
        assert _fires(cond, event="workflow_dispatch"), (
            f"job {name!r} would be skipped on a manual dispatch")


# --- the intended mapping --------------------------------------------------

def test_intended_schedule_mapping(wf):
    """games/hittrax keep the post-HitTrax-export slot; bullpen runs evening +
    morning so players get same-night reports."""
    conds = _conditions(wf)
    expected = {
        "games": {GAMES_SLOT},
        "hittrax": {GAMES_SLOT},
        "bullpen": {BULLPEN_EVENING, BULLPEN_MORNING},
    }
    assert set(conds) == set(expected), "workflow jobs changed"
    all_crons = [c["cron"] for c in wf["triggers"]["schedule"]]
    for name, slots in expected.items():
        actual = {c for c in all_crons
                  if _fires(conds[name], event="schedule", schedule=c)}
        assert actual == slots, f"job {name!r} runs on {sorted(actual)}, expected {sorted(slots)}"


def test_hittrax_stays_live(wf):
    """Flipped live 2026-08-28 (docs/PIPELINE_CRON.md) once `app/ingest/
    hittrax.py`'s extract_load_raw stopped taking the OLDEST 20 filenames
    alphabetically (it now skips already-loaded files and takes what's left
    newest-first -- see tests/test_ingest_hittrax_raw.py). If this ever flips
    back to --dry-run, it should be a deliberate edit, not a silent revert."""
    steps = wf["jobs"]["hittrax"]["steps"]
    run = " ".join(s.get("run", "") for s in steps)
    assert "ingest hittrax" in run
    assert "--no-dry-run" in run, (
        "hittrax reverted to dry-run -- if that's deliberate, update this test "
        "and docs/PIPELINE_CRON.md to match")


def test_bullpen_stays_live(wf):
    """The bullpen job is the one that makes same-night reports possible."""
    steps = wf["jobs"]["bullpen"]["steps"]
    run = " ".join(s.get("run", "") for s in steps)
    assert "ingest bullpen" in run and "--no-dry-run" in run


def test_games_stays_live(wf):
    """Flipped live 2026-08-28 (docs/PIPELINE_CRON.md) after a scoped dry-run
    confirmed the SFTP walk + LMU filter work correctly. If this ever flips
    back to --dry-run, it should be a deliberate edit, not a silent revert."""
    steps = wf["jobs"]["games"]["steps"]
    run = " ".join(s.get("run", "") for s in steps)
    assert "pipeline-load" in run
    assert "--no-dry-run" in run, (
        "games reverted to dry-run -- if that's deliberate, update this test "
        "and docs/PIPELINE_CRON.md to match")
