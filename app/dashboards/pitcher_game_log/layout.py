"""Pitching Game Log page: same layout as the hitting Game Log (filter bar,
outing strip, pitch log beside the video + selected-pitch detail), with
pitching KPIs and pitch-type movement/release context."""
from __future__ import annotations

from datetime import date

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.dashboards.game_log import charts as glcharts
from app.dashboards.game_log import tables as gltables
from app.dashboards.game_log.layout import (_PANEL, _filter, _num, _stat, _tile,
                                            filter_options, zone_options)
from app.dashboards.pitcher_game_log import charts, tables
from app.dashboards.shell import BANNER, header
from app.dashboards.video import component as videotab
from app.data import pitcher_game_log as pgl
from app.data import seasons
from app.data import video as videodata

EMPTY_DETAIL = "Click any pitch in the log to play its video and see the pitch's metrics."


def summary_strip(df: pd.DataFrame | None, who: str = "LMU pitchers") -> html.Div:
    s = pgl.summary(df)
    return html.Div([
        html.Div(who, style={"fontSize": "18px", "fontWeight": "bold", "alignSelf": "center",
                             "marginRight": "8px"}),
        *[_stat(k, v) for k, v in s.items()],
    ], style={**_PANEL, "display": "flex", "flexWrap": "wrap", "gap": "4px",
              "alignItems": "center"})


def play_detail(df: pd.DataFrame | None, pitch_uid: str | None) -> html.Div:
    """Everything under the video for one selected pitch."""
    if df is None or df.empty or not pitch_uid or pitch_uid not in set(df["PitchUID"]):
        return html.Div(EMPTY_DETAIL, style={**_PANEL, "color": "#555", "fontSize": "18px"})
    r = df[df["PitchUID"] == pitch_uid].iloc[0]
    pa = df[df["pa_key"] == r["pa_key"]].sort_values("PitchofPA")
    bats = {"Right": " (RHH)", "Left": " (LHH)"}.get(r["BatterSide"], "")
    outs = "" if pd.isna(r["Outs"]) else f"{int(r['Outs'])} out · "
    headline = (f"{r['InnLabel']} · {outs}{r['Pitcher']} vs {r['Batter']}{bats} · "
                f"{r['Count']} · pitch {int(r['PitchofPA'])} of {len(pa)}")
    line = pgl.pitcher_line(df, r["Pitcher"])
    same = pgl.same_type(df, r["Pitcher"], r["TaggedPitchType"])
    velo = pd.to_numeric(same["RelSpeed"], errors="coerce")
    avg_velo = f"{velo.mean():.1f}" if velo.notna().any() else ""

    tiles = [
        _tile("Pitch", f"{r['Type']} {_num(r['RelSpeed'], '{:.1f}')}".strip(), accent=True),
        _tile(f"Avg {r['Type']} velo", avg_velo),
        _tile("Spin", _num(r["SpinRate"], "{:.0f}")),
        _tile("IVB", _num(r["InducedVertBreak"], '{:.1f}"')),
        _tile("HB", _num(r["HorzBreak"], '{:.1f}"')),
        _tile("VAA", _num(r["VertApprAngle"], "{:.1f}°")),
        _tile("Extension", _num(r["Extension"], "{:.1f} ft")),
        _tile("Rel Height", _num(r["RelHeight"], "{:.1f} ft")),
        _tile("Zone", r["ZoneWord"] or ""),
        _tile("Result", r["Result"], accent=True),
    ]
    contact = [
        _tile("Exit Velo", _num(r["ExitSpeed"], "{:.1f}")),
        _tile("Launch", _num(r["Angle"], "{:.0f}°")),
        _tile("Distance", _num(r["Distance"], "{:.0f} ft")),
        _tile("Hard Hit", "Yes" if r["is_hard"] else "No"),
    ] if r["is_bip"] else []
    grid = {"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(84px, 1fr))",
            "gap": "6px", "marginTop": "8px"}
    graph = {"config": {"displayModeBar": False}, "style": {"flex": "1", "minWidth": "240px"}}
    return html.Div([
        html.Div(headline, style={"fontSize": "20px", "fontWeight": "bold"}),
        html.Div(f"This game: {line}" if line else "", style={"fontSize": "16px", "color": "#555"}),
        html.Div(tiles, style=grid),
        html.Div(contact, style=grid) if contact else None,
        html.Div([
            dcc.Graph(figure=glcharts.pa_zone_fig(pa, pitch_uid), **graph),
            dcc.Graph(figure=charts.movement_fig(same, pitch_uid, r["TaggedPitchType"]), **graph),
            dcc.Graph(figure=charts.release_fig(same, pitch_uid, r["TaggedPitchType"]), **graph),
        ], className="paw-chart-row",
           style={"display": "flex", "gap": "8px", "marginTop": "8px", "flexWrap": "wrap"}),
        html.Div("At-bat detail", style={"fontSize": "18px", "fontWeight": "bold",
                                         "marginTop": "6px"}),
        gltables.pa_sequence(pa, pitch_uid),
    ], style=_PANEL)


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    season = seasons.season_label_for(date.today().isoformat())
    s, e = seasons.season_bounds(season)
    games = pgl.lmu_games(s, e)
    game = str(games.iloc[0]["game_id"]) if not games.empty else None
    df = pgl.game_pitches(game) if game else None
    opts = filter_options(df)

    multi = {"multi": True, "clearable": True}
    filters = html.Div([
        _filter("Season", dcc.Dropdown(id="pgl-season", value=season, clearable=False,
                                       options=[{"label": x, "value": x}
                                                for x in seasons.available_seasons()]),
                "120px"),
        _filter("Game", dcc.Dropdown(id="pgl-game", value=game, clearable=False,
                                     options=[{"label": r.GameLabel, "value": str(r.game_id)}
                                              for r in games.itertuples()]), "280px"),
        _filter("Pitcher", dcc.Dropdown(id="pgl-pitcher", options=opts["pitcher"],
                                        placeholder="All pitchers"), "180px"),
        _filter("Hitter", dcc.Dropdown(id="pgl-batter", options=opts["batter"],
                                       placeholder="All hitters"), "180px"),
        _filter("Inning", dcc.Dropdown(id="pgl-inning", options=opts["inning"],
                                       placeholder="All", **multi), "110px"),
        _filter("Pitch type", dcc.Dropdown(id="pgl-ptype", options=opts["ptype"],
                                           placeholder="All", **multi), "150px"),
        _filter("Zone", dcc.Dropdown(id="pgl-zone", placeholder="All zones",
                                     options=zone_options(), **multi), "200px"),
        _filter("Show only", dcc.Dropdown(id="pgl-show", placeholder="Every pitch",
                                          options=[{"label": lbl, "value": k}
                                                   for k, lbl in pgl.SHOW_ONLY], **multi),
                "200px"),
    ], style={"display": "flex", "gap": "12px", "alignItems": "flex-end", "flexWrap": "wrap",
              "padding": "12px 16px", "backgroundColor": BANNER})

    return html.Div([
        header(back_href="/pitching", back_label="← Pitching"),
        filters,
        html.Div([
            html.Div(summary_strip(df), id="pgl-summary"),
            html.Div([
                html.Div([
                    html.Div(id="pgl-count", children=_count_text(df, df),
                             style={"fontSize": "16px", "color": "#555", "marginBottom": "4px"}),
                    html.Div(tables.pitch_log(df), id="pgl-log"),
                ], className="paw-video-table",
                   style={**_PANEL, "flex": "1", "minWidth": "420px"}),
                html.Div([
                    html.Div(videotab.media_panel("pgl", videodata.PITCHER_ANGLES), style=_PANEL),
                    html.Div(play_detail(df, None), id="pgl-detail", style={"marginTop": "10px"}),
                ], className="paw-video-media", style={"flex": "1.2", "minWidth": "480px"}),
            ], className="paw-video-row",
               style={"display": "flex", "gap": "16px", "alignItems": "flex-start",
                      "marginTop": "12px"}),
        ], style={"padding": "12px 16px"}),
    ])


def _count_text(shown, full) -> str:
    if full is None or full.empty:
        return "No pitches by LMU pitchers in this game."
    return (f"{len(shown)} of {len(full)} pitches · {shown['pa_key'].nunique()} PA · "
            "bold row = PA result · hover a Zone number for its name")

