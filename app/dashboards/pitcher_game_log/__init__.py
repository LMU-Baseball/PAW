"""Pitching Game Log (Flask + Dash), mounted at /dash/pitcher-game-log/: every
pitch LMU pitchers threw in a game, click one for its video and pitch detail."""
from dash import Dash

from app.dashboards.pitcher_game_log import callbacks, layout
from app.dashboards.shell import index_string


def build_pitcher_game_log_dash(server) -> Dash:
    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/pitcher-game-log/",
                    suppress_callback_exceptions=True, compress=True,
                    title="Pitching Game Log — The PAW")
    dash_app.index_string = index_string()
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    return dash_app
