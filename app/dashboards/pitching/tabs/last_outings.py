"""Last Outings tab: coach picks how many outings; table + avg/max velo trend."""
from __future__ import annotations

from dash import dcc, html

from app.data import pitching as P
from app.data import pitching_caps
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_COLS = {
    "game_date": "Date", "appearance_avg_velo": "Avg Velo",
    "appearance_max_velo": "Max Velo", "pitch_count": "Pitches",
}
COUNT_OPTIONS = [{"label": "Last 3", "value": 3}, {"label": "Last 5", "value": 5},
                 {"label": "Last 10", "value": 10}, {"label": "Last 15", "value": 15},
                 {"label": "All", "value": 9999}]


def body(pitcher_id, game_id, n) -> html.Div:
    if pitcher_id is None or game_id is None:
        return html.Div("No outing selected.")
    recent = pitching_caps.recent_outings(int(pitcher_id), int(game_id), int(n))
    if recent.empty:
        return html.Div("No prior outings.")
    show = recent[[c for c in _COLS if c in recent.columns]].rename(columns=_COLS)
    for col in ("Avg Velo", "Max Velo"):
        if col in show.columns:
            show[col] = show[col].round(1)
    label = "All" if int(n) >= 9999 else f"Last {len(show)}"
    return html.Div([
        section(f"{label} Outings"),
        tables.df_table(show, id_="lo-avgs"),
        section("Velocity Trend"),
        dcc.Graph(figure=P.fig_outings_velo_trend(recent)),
    ])


def render(pitcher_id, game_id, n: int = 5) -> html.Div:
    return html.Div([
        html.Div([
            html.Label("Outings", style={"fontWeight": "bold", "marginRight": "8px"}),
            dcc.Dropdown(id="lo-count-dd", options=COUNT_OPTIONS, value=5,
                         clearable=False, style={"width": "160px"}),
        ], style={"display": "flex", "alignItems": "center", "margin": "6px 0"}),
        html.Div(id="lo-body", children=body(pitcher_id, game_id, n)),
    ])
