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


def test_html_to_pdf_returns_pdf_bytes():
    from app.reports.pdf import html_to_pdf
    out = html_to_pdf("<html><body><h1>Hello PAW</h1></body></html>")
    assert isinstance(out, bytes)
    assert out[:5] == b"%PDF-"
    assert len(out) > 1000
