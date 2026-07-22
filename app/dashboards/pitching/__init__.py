"""Login-protected Pitching game-stats dashboard (Flask + Dash)."""
from dash import Dash

from app.dashboards.pitching.index import INDEX_STRING
from app.dashboards.pitching import layout

__all__ = ["build_pitching_dash", "INDEX_STRING"]


def build_pitching_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/pitching/",
        suppress_callback_exceptions=True,
        title="Pitching — The PAW",
    )
    dash_app.index_string = INDEX_STRING
    dash_app.layout = layout.serve_layout

    from app.dashboards.pitching import callbacks
    callbacks.register_callbacks(dash_app)
    return dash_app
