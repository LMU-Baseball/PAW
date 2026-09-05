"""Zone Frequency tab: 9-pocket (catcher's view) hot/cold charts of damage
metrics by zone cell -- Avg Exit Velocity, Avg Distance, Batting Average, and
Pitches Seen in a 2x2 grid (stacked on phone, via the shared .paw-chart-grid
class), all filterable by pitch group / pitcher throws."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import hitting
from app.dashboards.hitting import charts

DAMAGE_METRICS = ("ev", "distance", "avg")

# Values match the "PitchCat" column ("Fastball"/"Offspeed") exactly; "All"
# is the no-filter sentinel `zone_frequency_grid` expects.
PITCH_GROUP_OPTIONS = [
    {"label": "All Pitches", "value": "All"},
    {"label": "Fastball", "value": "Fastball"},
    {"label": "Offspeed", "value": "Offspeed"},
]
# Values match the raw PitcherThrows column, same as
# catching/tabs/framing.py's identical Pitcher Hand dropdown.
THROWS_OPTIONS = [
    {"label": "All", "value": "All"},
    {"label": "RHP", "value": "Right"},
    {"label": "LHP", "value": "Left"},
]


def _field(label, id_, options, value) -> html.Div:
    return html.Div([
        html.Label(label, style={"fontSize": "13px", "color": "#555", "display": "block"}),
        dcc.Dropdown(id=id_, options=options, value=value, clearable=False,
                     style={"minWidth": "170px"}),
    ])


def filter_bar() -> html.Div:
    return html.Div([
        _field("Pitch Group", "zf-pitchgroup", PITCH_GROUP_OPTIONS, "All"),
        _field("Pitcher Throws", "zf-throws", THROWS_OPTIONS, "All"),
    ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "margin": "8px 0 12px"})


def _panel(fig) -> html.Div:
    return html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}))


def body(df: pd.DataFrame, *, pitch_group: str = "All", throws: str = "All") -> html.Div:
    panels = []
    for metric in DAMAGE_METRICS:
        grid = hitting.zone_frequency_grid(df, metric=metric, pitch_group=pitch_group,
                                           throws=throws)
        panels.append(_panel(charts.zone_frequency_fig(grid, metric=metric, compact=True)))
    pitch_grid = hitting.zone_pitch_frequency_grid(df, pitch_group=pitch_group, throws=throws)
    panels.append(_panel(charts.zone_pitch_frequency_fig(pitch_grid, compact=True)))
    return html.Div(panels, className="paw-chart-grid",
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"})


def render(df: pd.DataFrame) -> html.Div:
    return html.Div([filter_bar(), html.Div(id="zf-body", children=body(df))])
