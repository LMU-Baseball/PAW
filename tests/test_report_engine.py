import importlib
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_report_dependencies_importable():
    assert importlib.util.find_spec("playwright.sync_api") is not None
    assert importlib.util.find_spec("kaleido") is not None


def test_report_assets_present():
    reports = APP / "static" / "reports"
    assert (reports / "lmu.png").exists()
    assert (reports / "Teko-Regular.ttf").exists()
