"""Pitching Game Log table: the condensed, scrollable pitch-by-pitch log.
Same look as the hitting Game Log's (`app.dashboards.game_log.tables`)."""
from __future__ import annotations

import pandas as pd
from dash import dash_table, html

from app.dashboards.game_log.tables import _CELL, _HIT_CODES
from app.dashboards.shell import BLUE, CRIMSON
from app.data import video as videodata

# The shared video component's table id for prefix "pgl".
TABLE_ID = "pgl-video-table"

LOG_COLS = [("Inn", "InnLabel"), ("Out", "Outs"), ("Pitcher", "Pitcher"), ("#", "PitchofPA"),
            ("Count", "Count"), ("Batter", "Batter"), ("Type", "Type"), ("Velo", "Velo"),
            ("Spin", "Spin"), ("IVB", "IVB"), ("HB", "HB"), ("Result", "Result"), ("Zone", "Z")]


def _records(df: pd.DataFrame) -> list[dict]:
    keep = ([c for _, c in LOG_COLS] + list(videodata.URL_COL.values())
            + ["batter_side", "pitcher_side", "ZoneWord", "PitchUID", "pa_seq", "is_pa_end",
               "pa_code"])
    d = df[keep].copy()
    d["id"] = d["PitchUID"]
    d["band"] = d["pa_seq"] % 2
    d["pa_end"] = d["is_pa_end"].map({True: "1", False: "0"})
    d["hit"] = d["pa_code"].map(lambda c: "1" if c.endswith(_HIT_CODES) else "0")
    d["k"] = d["pa_code"].map(lambda c: "1" if c.startswith("K") else "0")
    d = d.drop(columns=["is_pa_end"])
    d = d.astype(object).where(d.notna(), None)
    return d.to_dict("records")


def pitch_log(df: pd.DataFrame | None) -> html.Div | dash_table.DataTable:
    if df is None or df.empty:
        return html.Div("No pitches match these filters.",
                        style={"padding": "16px", "color": "#555", "fontSize": "18px"})
    recs = _records(df)
    return dash_table.DataTable(
        id=TABLE_ID,
        columns=[{"name": n, "id": c} for n, c in LOG_COLS],
        data=recs,
        page_action="none", fixed_rows={"headers": True},
        style_table={"maxHeight": "640px", "overflowY": "auto", "overflowX": "auto"},
        style_cell=_CELL,
        tooltip_data=[{"Z": r["ZoneWord"] or ""} for r in recs], tooltip_delay=0,
        style_cell_conditional=[{"if": {"column_id": c}, "textAlign": "left"}
                                for c in ("Batter", "Pitcher", "Result")]
                               + [{"if": {"column_id": "Z"}, "width": "38px", "minWidth": "38px",
                                   "maxWidth": "38px"},
                                  {"if": {"column_id": "Batter"}, "minWidth": "110px"},
                                  {"if": {"column_id": "Pitcher"}, "minWidth": "120px"}],
        style_header={"backgroundColor": CRIMSON, "color": "white", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"filter_query": "{band} = 1"}, "backgroundColor": "#f4f1ee"},
            {"if": {"filter_query": "{pa_end} = 1"}, "fontWeight": "bold",
             "borderBottom": "2px solid #bbb"},
            # Colors read from the pitcher's side: a K is good (blue), a hit allowed bad (crimson).
            {"if": {"filter_query": "{k} = 1", "column_id": "Result"}, "color": BLUE},
            {"if": {"filter_query": "{hit} = 1", "column_id": "Result"}, "color": CRIMSON},
            {"if": {"state": "active"}, "backgroundColor": "rgba(154,0,33,.15)",
             "border": f"1px solid {CRIMSON}"},
        ],
    )
