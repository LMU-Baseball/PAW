"""Catching Game Log (Flask + Dash), mounted at /dash/catcher-game-log/: every
pitch LMU catchers received in a game, click one for its video and receiving detail."""
from dash import Dash

from app.dashboards.catcher_game_log import callbacks, layout
from app.dashboards.shell import index_string


def build_catcher_game_log_dash(server) -> Dash:
    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/catcher-game-log/",
                    suppress_callback_exceptions=True, compress=True,
                    title="Catching Game Log — The PAW")
    dash_app.index_string = index_string()
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    return dash_app
