"""Dash DataTable builders for the hitting stat tables."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

# Numeric-percent columns produced by app/data/hitting.py, shown with a % suffix.
PCT_COLS = {"Swing %", "Whiff %", "Take %", "Contact %"}


def _format(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    for c in d.columns:
        if c in PCT_COLS:
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{float(v):.1f}%")
    return d


def stat_table(df: pd.DataFrame, *, id: str | None = None) -> dash_table.DataTable:
    d = _format(df)
    cols = [{"name": c, "id": c} for c in d.columns]
    return dash_table.DataTable(
        id=id or "stat-table",
        columns=cols,
        data=d.to_dict("records"),
        style_as_list_view=True,
        style_header={"backgroundColor": "#9A0021", "color": "white",
                      "fontWeight": "bold", "textAlign": "center"},
        style_cell={"textAlign": "center", "padding": "6px 10px",
                    "fontFamily": "Teko, sans-serif", "fontSize": "16px"},
        style_data={"backgroundColor": "rgba(255,255,255,0.85)"},
    )
