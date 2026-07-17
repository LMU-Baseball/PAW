"""Guard: the legacy crimson #9A0021 is fully replaced by official #AB0C2F."""
from pathlib import Path

import pytest

_FILES = [
    "app/reports/static/report.css",
    "app/reports/plots.py",
    "app/templates/reports/pitching_landing.html",
    "app/templates/base.html",
    "app/templates/main/index.html",
]


@pytest.mark.parametrize("path", _FILES)
def test_no_legacy_crimson(path):
    text = Path(path).read_text(encoding="utf-8")
    assert "#9A0021" not in text, f"legacy crimson still in {path}"
    assert "154,0,33" not in text and "154, 0, 33" not in text, f"legacy crimson rgba in {path}"


def test_report_css_has_official_crimson():
    text = Path("app/reports/static/report.css").read_text(encoding="utf-8")
    assert "#AB0C2F" in text
