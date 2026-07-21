"""Guard: the crimson brand color is the darker #9A0021.

The coaches preferred the darker #9A0021 over the brighter official #AB0C2F
(the official blue #0076A5 was kept). No bright #AB0C2F / rgba(171,12,47) should
remain in the styled surfaces.
"""
from pathlib import Path

import pytest

_FILES = [
    "app/reports/static/report.css",
    "app/reports/plots.py",
    "app/templates/reports/pitching_landing.html",
    "app/templates/base.html",
    "app/templates/main/index.html",
    "app/dashboards/hitting/index.py",
    "app/dashboards/hitting/tables.py",
    "app/dashboards/hitting/layout.py",
    "app/dashboards/hitting/callbacks.py",
    "app/dashboards/hitting/tabs/game_level.py",
    "app/dashboards/hitting/tabs/zone_location.py",
]


@pytest.mark.parametrize("path", _FILES)
def test_no_bright_crimson(path):
    text = Path(path).read_text(encoding="utf-8")
    assert "#AB0C2F" not in text, f"bright crimson still in {path}"
    assert "171,12,47" not in text and "171, 12, 47" not in text, f"bright crimson rgba in {path}"


def test_report_css_uses_darker_crimson():
    text = Path("app/reports/static/report.css").read_text(encoding="utf-8")
    assert "#9A0021" in text
