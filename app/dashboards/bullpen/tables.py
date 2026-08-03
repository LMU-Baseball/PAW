"""Dash DataTable builder for the bullpen dashboard (pitch colors via plots)."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

from app.reports.plots import color_for


def df_table(df: pd.DataFrame, id_: str | None = None, color_col: str = "pitch"):
    conditional = []
    if color_col in df.columns:
        for pt in df[color_col].dropna().unique():
            conditional.append({
                "if": {"filter_query": f'{{{color_col}}} = "{pt}"', "column_id": color_col},
                "color": color_for(str(pt)), "fontWeight": "bold"})
    return dash_table.DataTable(
        id=id_ or "bullpen-table",
        columns=[{"name": str(c), "id": str(c)} for c in df.columns],
        data=df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": "#9A0021", "color": "white", "fontWeight": "bold"},
        style_data_conditional=conditional,
    )
