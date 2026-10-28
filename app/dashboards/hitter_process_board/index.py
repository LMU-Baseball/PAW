"""All Things Process (hitters) Dash app factory, mounted at /dash/hitter_process_board/."""
from __future__ import annotations

from dash import Dash

from app.dashboards.shell import index_string
from app.dashboards.hitter_process_board import callbacks, layout


def build_hitter_process_board_dash(server) -> Dash:
    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/hitter_process_board/",
                    suppress_callback_exceptions=True, compress=True)
    dash_app.index_string = index_string()
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    return dash_app
