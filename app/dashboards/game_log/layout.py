"""Hitting Game Log page: filter bar, game-at-a-glance strip, then the
pitch-by-pitch log beside the video + selected-play detail."""
from __future__ import annotations

from datetime import date

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.dashboards.game_log import charts, tables
from app.dashboards.shell import BANNER, CRIMSON, header
from app.dashboards.video import component as videotab
from app.data import game_log, seasons
from app.data import video as videodata

_PANEL = {"backgroundColor": "rgba(255,255,255,0.88)", "borderRadius": "8px", "padding": "10px"}
_LABEL = {"color": "white", "fontWeight": "bold"}
EMPTY_DETAIL = "Click any pitch in the log to play its video and see the play's metrics."


def _filter(label, component, min_width="140px"):
    return html.Div([html.Label(label, style=_LABEL), component], style={"minWidth": min_width})


def filter_options(df: pd.DataFrame | None) -> dict:
    """Hitter / pitcher / inning / pitch-type options for one game's pitches."""
    if df is None or df.empty:
        return {"batter": [], "pitcher": [], "inning": [], "ptype": []}
    order = df.drop_duplicates("Batter")["Batter"].tolist()
    return {
        "batter": [{"label": b, "value": b} for b in order],
        "pitcher": [{"label": p, "value": p}
                    for p in df.drop_duplicates("Pitcher")["Pitcher"].dropna()],
        "inning": [{"label": str(int(i)), "value": int(i)}
                   for i in sorted(df["Inning"].dropna().unique())],
        "ptype": [{"label": t, "value": t}
                  for t in df["TaggedPitchType"].dropna().value_counts().index],
    }


def _stat(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "24px", "fontWeight": "bold", "color": CRIMSON,
                               "lineHeight": "1"}),
        html.Div(label, style={"fontSize": "13px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "4px 8px", "minWidth": "64px"})


def summary_strip(df: pd.DataFrame | None, who: str = "LMU hitters") -> html.Div:
    s = game_log.summary(df)
    return html.Div([
        html.Div(who, style={"fontSize": "18px", "fontWeight": "bold", "alignSelf": "center",
                             "marginRight": "8px"}),
        *[_stat(k, v) for k, v in s.items()],
    ], style={**_PANEL, "display": "flex", "flexWrap": "wrap", "gap": "4px",
              "alignItems": "center"})


def _tile(label, value, *, accent=False):
    return html.Div([
        html.Div(value if value not in (None, "") else "—",
                 style={"fontSize": "20px", "fontWeight": "bold", "lineHeight": "1.05",
                        "color": "#fff" if accent else CRIMSON}),
        html.Div(label, style={"fontSize": "12px",
                               "color": "rgba(255,255,255,.85)" if accent else "#555"}),
    ], style={"textAlign": "center", "padding": "6px 4px", "borderRadius": "6px",
              "backgroundColor": CRIMSON if accent else "rgba(255,255,255,0.9)",
              "border": "1px solid #e4dcd6"})


def _num(v, fmt):
    return "" if v is None or pd.isna(v) else fmt.format(v)


def _xba(r) -> str:
    if not r["is_bip"]:
        return ""
    try:
        from app.data import xba
        return f"{xba.p_hit(r['ExitSpeed'], r['Angle']):.3f}".lstrip("0")
    except Exception:
        return ""


_DECISION_GOOD = {"Heart swing", "Good take", "Shadow swing", "Shadow take"}


def play_detail(df: pd.DataFrame | None, pitch_uid: str | None) -> html.Div:
    """Everything under the video for one selected pitch."""
    if df is None or df.empty or not pitch_uid or pitch_uid not in set(df["PitchUID"]):
        return html.Div(EMPTY_DETAIL, style={**_PANEL, "color": "#555", "fontSize": "18px"})
    r = df[df["PitchUID"] == pitch_uid].iloc[0]
    pa = df[df["pa_key"] == r["pa_key"]].sort_values("PitchofPA")
    throws = {"Right": " (RHP)", "Left": " (LHP)"}.get(r["PitcherThrows"], "")
    outs = "" if pd.isna(r["Outs"]) else f"{int(r['Outs'])} out · "
    headline = (f"{r['InnLabel']} · {outs}{r['Batter']} vs {r['Pitcher']}{throws} · "
                f"{r['Count']} · pitch {int(r['PitchofPA'])} of {len(pa)}")
    line = game_log.batter_line(df, r["Batter"])

    decision = r["decision"]
    pitch_tiles = [
        _tile("Pitch", f"{r['Type']} {_num(r['RelSpeed'], '{:.1f}')}".strip(), accent=True),
        _tile("Spin", _num(r["SpinRate"], "{:.0f}")),
        _tile("IVB", _num(r["InducedVertBreak"], '{:.1f}"')),
        _tile("HB", _num(r["HorzBreak"], '{:.1f}"')),
        _tile("VAA", _num(r["VertApprAngle"], "{:.1f}°")),
        _tile("Zone", r["Zone"]),
        _tile("Decision", decision, accent=bool(decision) and decision not in _DECISION_GOOD),
    ]
    contact_tiles = [
        _tile("Result", r["Result"], accent=True),
        _tile("Exit Velo", _num(r["ExitSpeed"], "{:.1f}")),
        _tile("Launch", _num(r["Angle"], "{:.0f}°")),
        _tile("Distance", _num(r["Distance"], "{:.0f} ft")),
        _tile("Hang Time", _num(r["HangTime"], "{:.1f}s")),
        _tile("xBA", _xba(r)),
        _tile("Hard Hit", "Yes" if r["is_hard"] else ("No" if r["is_bip"] else "")),
    ]
    grid = {"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(84px, 1fr))",
            "gap": "6px", "marginTop": "8px"}
    batter_bips = game_log.bip_xy(df[df["Batter"] == r["Batter"]])
    return html.Div([
        html.Div(headline, style={"fontSize": "20px", "fontWeight": "bold"}),
        html.Div(f"This game: {line}" if line else "", style={"fontSize": "16px", "color": "#555"}),
        html.Div(pitch_tiles, style=grid),
        html.Div(contact_tiles, style=grid) if r["is_bip"] else None,
        html.Div([
            dcc.Graph(figure=charts.pa_zone_fig(pa, pitch_uid), config={"displayModeBar": False},
                      style={"flex": "1", "minWidth": "260px"}),
            dcc.Graph(figure=charts.spray_highlight_fig(
                          batter_bips, pitch_uid, f"{r['Batter']} — Balls in Play"),
                      config={"displayModeBar": False}, style={"flex": "1", "minWidth": "260px"}),
        ], className="paw-chart-row", style={"display": "flex", "gap": "8px", "marginTop": "8px"}),
        html.Div("At-bat detail", style={"fontSize": "18px", "fontWeight": "bold",
                                         "marginTop": "6px"}),
        tables.pa_sequence(pa, pitch_uid),
    ], style=_PANEL)


def zone_options() -> list[dict]:
    return [{"label": w, "value": w} for w in game_log.ZONE_WORDS]


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    season = seasons.season_label_for(date.today().isoformat())
    s, e = seasons.season_bounds(season)
    games = game_log.lmu_games(s, e)
    game = str(games.iloc[0]["game_id"]) if not games.empty else None
    df = game_log.game_pitches(game) if game else None
    opts = filter_options(df)

    multi = {"multi": True, "clearable": True}
    filters = html.Div([
        _filter("Season", dcc.Dropdown(id="gl-season", value=season, clearable=False,
                                       options=[{"label": x, "value": x}
                                                for x in seasons.available_seasons()]),
                "120px"),
        _filter("Game", dcc.Dropdown(id="gl-game", value=game, clearable=False,
                                     options=[{"label": r.GameLabel, "value": str(r.game_id)}
                                              for r in games.itertuples()]), "280px"),
        _filter("Hitter", dcc.Dropdown(id="gl-batter", options=opts["batter"],
                                       placeholder="All hitters"), "180px"),
        _filter("Pitcher", dcc.Dropdown(id="gl-pitcher", options=opts["pitcher"],
                                        placeholder="All pitchers"), "180px"),
        _filter("Inning", dcc.Dropdown(id="gl-inning", options=opts["inning"],
                                       placeholder="All", **multi), "110px"),
        _filter("Pitch type", dcc.Dropdown(id="gl-ptype", options=opts["ptype"],
                                           placeholder="All", **multi), "150px"),
        _filter("Zone", dcc.Dropdown(id="gl-zone", placeholder="All zones",
                                     options=zone_options(), **multi), "200px"),
        _filter("Show only", dcc.Dropdown(id="gl-show", placeholder="Every pitch",
                                          options=[{"label": lbl, "value": k}
                                                   for k, lbl in game_log.SHOW_ONLY], **multi),
                "200px"),
    ], style={"display": "flex", "gap": "12px", "alignItems": "flex-end", "flexWrap": "wrap",
              "padding": "12px 16px", "backgroundColor": BANNER})

    return html.Div([
        header(back_href="/hitting", back_label="← Hitting"),
        filters,
        html.Div([
            html.Div(summary_strip(df), id="gl-summary"),
            html.Div([
                html.Div([
                    html.Div(id="gl-count", children=_count_text(df, df),
                             style={"fontSize": "16px", "color": "#555", "marginBottom": "4px"}),
                    html.Div(tables.pitch_log(df), id="gl-log"),
                ], className="paw-video-table",
                   style={**_PANEL, "flex": "1", "minWidth": "420px"}),
                html.Div([
                    html.Div(videotab.media_panel("gl", videodata.HITTER_ANGLES), style=_PANEL),
                    html.Div(play_detail(df, None), id="gl-detail", style={"marginTop": "10px"}),
                ], className="paw-video-media", style={"flex": "1.2", "minWidth": "480px"}),
            ], className="paw-video-row",
               style={"display": "flex", "gap": "16px", "alignItems": "flex-start",
                      "marginTop": "12px"}),
        ], style={"padding": "12px 16px"}),
    ])


def _count_text(shown, full) -> str:
    if full is None or full.empty:
        return "No pitches to LMU hitters in this game."
    return (f"{len(shown)} of {len(full)} pitches · {shown['pa_key'].nunique()} PA · "
            "bold row = PA result · 🎥 = video")
