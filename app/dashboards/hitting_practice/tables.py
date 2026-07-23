"""Dash DataTable helper for practice dashboard."""
from __future__ import annotations

import pandas as pd
from dash import dash_table


def df_table(df: pd.DataFrame, id_: str | None = None):
    return dash_table.DataTable(
        id=id_ or "practice-table",
        columns=[{"name": str(c), "id": str(c)} for c in df.columns],
        data=df.to_dict("records"),
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": "#9A0021", "color": "white",
                      "fontWeight": "bold"},
        page_size=15,
    )
