"""Splash Report Dash app factory, mounted at /dash/splash_report/."""
from __future__ import annotations

from dash import Dash

from app.dashboards.shell import index_string
from app.dashboards.splash_report import callbacks, layout


def build_splash_report_dash(server) -> Dash:
    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/splash_report/",
                    suppress_callback_exceptions=True, compress=True)
    dash_app.index_string = index_string()
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    return dash_app
