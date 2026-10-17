"""Catching Game Log page: same layout as the hitting Game Log (filter bar,
receiving strip, pitch log beside the video + selected-pitch detail), with the
Catching dashboard's framing / SLAA / throwing measures."""
from __future__ import annotations

from datetime import date

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.dashboards.catcher_game_log import charts, tables
from app.dashboards.game_log import charts as glcharts
from app.dashboards.game_log import tables as gltables
from app.dashboards.game_log.layout import (_PANEL, _filter, _num, _stat, _tile,
                                            filter_options, zone_options)
from app.dashboards.shell import BANNER, header
from app.dashboards.video import component as videotab
from app.data import catcher_game_log as cgl
from app.data import seasons
from app.data import video as videodata

EMPTY_DETAIL = "Click any pitch in the log to play its video and see the receiving detail."
_STEAL_NAME = {"SB": "Stolen base", "CS": "Caught stealing"}


def catcher_options(df: pd.DataFrame | None) -> list[dict]:
    if df is None or df.empty:
        return []
    names = df.loc[df["Catcher"] != "", "Catcher"].value_counts().index
    return [{"label": c, "value": c} for c in names]


def summary_strip(df: pd.DataFrame | None, who: str = "LMU catchers") -> html.Div:
    s = cgl.summary(df)
    return html.Div([
        html.Div(who, style={"fontSize": "18px", "fontWeight": "bold", "alignSelf": "center",
                             "marginRight": "8px"}),
        *[_stat(k, v) for k, v in s.items()],
    ], style={**_PANEL, "display": "flex", "flexWrap": "wrap", "gap": "4px",
              "alignItems": "center"})


def _added(v) -> str:
    return "" if v is None or pd.isna(v) else f"{float(v):+.2f}"


def play_detail(df: pd.DataFrame | None, pitch_uid: str | None) -> html.Div:
    """Everything under the video for one selected pitch."""
    if df is None or df.empty or not pitch_uid or pitch_uid not in set(df["PitchUID"]):
        return html.Div(EMPTY_DETAIL, style={**_PANEL, "color": "#555", "fontSize": "18px"})
    r = df[df["PitchUID"] == pitch_uid].iloc[0]
    pa = df[df["pa_key"] == r["pa_key"]].sort_values("PitchofPA")
    outs = "" if pd.isna(r["Outs"]) else f"{int(r['Outs'])} out · "
    headline = (f"{r['InnLabel']} · {outs}{r['Catcher'] or 'Catcher'} catching "
                f"{r['Pitcher']} vs {r['Batter']} · {r['Count']}")
    line = cgl.catcher_line(df, r["Catcher"])

    tiles = [
        _tile("Pitch", f"{r['Type']} {_num(r['RelSpeed'], '{:.1f}')}".strip(), accent=True),
        _tile("Call", r["Result"]),
        _tile("Strike chance", r["xK"] or ""),
        _tile("Strikes added", _added(r["strikes_added"]), accent=bool(r["Frame"])),
        _tile("Framing", r["Frame"] or ("Correct" if r["is_take_scored"] else "")),
        _tile("Zone", r["ZoneWord"] or ""),
    ]
    throw = [
        _tile("Steal", _STEAL_NAME[r["Steal"]], accent=True),
        _tile("Pop Time", _num(r["PopTime"], "{:.2f}s")),
        _tile("Exchange", _num(r["ExchangeTime"], "{:.2f}s")),
        _tile("Throw Velo", _num(r["ThrowSpeed"], "{:.1f}")),
    ] if r["Steal"] else []
    grid = {"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(84px, 1fr))",
            "gap": "6px", "marginTop": "8px"}
    graph = {"config": {"displayModeBar": False}, "style": {"flex": "1", "minWidth": "260px"}}
    taken = df[(df["Catcher"] == r["Catcher"]) & df["is_take_scored"]]
    return html.Div([
        html.Div(headline, style={"fontSize": "20px", "fontWeight": "bold"}),
        html.Div(f"This game: {line}" if line else "", style={"fontSize": "16px", "color": "#555"}),
        html.Div(tiles, style=grid),
        html.Div(throw, style=grid) if throw else None,
        html.Div([
            dcc.Graph(figure=charts.framing_fig(taken, r, r["Catcher"] or "Catcher"), **graph),
            dcc.Graph(figure=glcharts.pa_zone_fig(pa, pitch_uid), **graph),
        ], className="paw-chart-row", style={"display": "flex", "gap": "8px", "marginTop": "8px"}),
        html.Div("At-bat detail", style={"fontSize": "18px", "fontWeight": "bold",
                                         "marginTop": "6px"}),
        gltables.pa_sequence(pa, pitch_uid),
    ], style=_PANEL)


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    season = seasons.season_label_for(date.today().isoformat())
    s, e = seasons.season_bounds(season)
    games = cgl.lmu_games(s, e)
    game = str(games.iloc[0]["game_id"]) if not games.empty else None
    df = cgl.game_pitches(game) if game else None
    opts = filter_options(df)

    multi = {"multi": True, "clearable": True}
    filters = html.Div([
        _filter("Season", dcc.Dropdown(id="cgl-season", value=season, clearable=False,
                                       options=[{"label": x, "value": x}
                                                for x in seasons.available_seasons()]),
                "120px"),
        _filter("Game", dcc.Dropdown(id="cgl-game", value=game, clearable=False,
                                     options=[{"label": r.GameLabel, "value": str(r.game_id)}
                                              for r in games.itertuples()]), "280px"),
        _filter("Catcher", dcc.Dropdown(id="cgl-catcher", options=catcher_options(df),
                                        placeholder="All catchers"), "170px"),
        _filter("Pitcher", dcc.Dropdown(id="cgl-pitcher", options=opts["pitcher"],
                                        placeholder="All pitchers"), "170px"),
        _filter("Hitter", dcc.Dropdown(id="cgl-batter", options=opts["batter"],
                                       placeholder="All hitters"), "170px"),
        _filter("Inning", dcc.Dropdown(id="cgl-inning", options=opts["inning"],
                                       placeholder="All", **multi), "110px"),
        _filter("Pitch type", dcc.Dropdown(id="cgl-ptype", options=opts["ptype"],
                                           placeholder="All", **multi), "150px"),
        _filter("Zone", dcc.Dropdown(id="cgl-zone", placeholder="All zones",
                                     options=zone_options(), **multi), "200px"),
        _filter("Show only", dcc.Dropdown(id="cgl-show", placeholder="Every pitch",
                                          options=[{"label": lbl, "value": k}
                                                   for k, lbl in cgl.SHOW_ONLY], **multi),
                "200px"),
    ], style={"display": "flex", "gap": "12px", "alignItems": "flex-end", "flexWrap": "wrap",
              "padding": "12px 16px", "backgroundColor": BANNER})

    return html.Div([
        header(back_href="/catching", back_label="← Catching"),
        filters,
        html.Div([
            html.Div(summary_strip(df), id="cgl-summary"),
            html.Div([
                html.Div([
                    html.Div(id="cgl-count", children=_count_text(df, df),
                             style={"fontSize": "16px", "color": "#555", "marginBottom": "4px"}),
                    html.Div(tables.pitch_log(df), id="cgl-log"),
                ], className="paw-video-table",
                   style={**_PANEL, "flex": "1", "minWidth": "420px"}),
                html.Div([
                    html.Div(videotab.media_panel("cgl", videodata.CATCHER_ANGLES), style=_PANEL),
                    html.Div(play_detail(df, None), id="cgl-detail", style={"marginTop": "10px"}),
                ], className="paw-video-media", style={"flex": "1.2", "minWidth": "480px"}),
            ], className="paw-video-row",
               style={"display": "flex", "gap": "16px", "alignItems": "flex-start",
                      "marginTop": "12px"}),
        ], style={"padding": "12px 16px"}),
    ])


def _count_text(shown, full) -> str:
    if full is None or full.empty:
        return "No pitches caught by LMU in this game."
    return (f"{len(shown)} of {len(full)} pitches · {shown['pa_key'].nunique()} PA · "
            "xK = chance an average catcher gets it called a strike · "
            "hover a Zone number for its name")
