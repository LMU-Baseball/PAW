"""DataTable builders for Splash Report's editable grids."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

from app.data import splash_report as SR

_HEADER_STYLE = {"backgroundColor": "#9A0021", "color": "white",
                 "fontWeight": "bold", "textAlign": "center"}
_CELL_STYLE = {"textAlign": "center", "padding": "6px 8px",
              "fontFamily": "Teko, sans-serif", "fontSize": "15px"}
_TABLE_STYLE = {"overflowX": "auto", "width": "fit-content", "maxWidth": "100%"}


def _table(id_, columns, data, *, editable: bool, row_deletable: bool = False,
          dropdown=None) -> dash_table.DataTable:
    return dash_table.DataTable(
        id=id_, columns=columns, data=data, editable=editable,
        row_deletable=row_deletable, dropdown=dropdown or {},
        style_table=_TABLE_STYLE, style_as_list_view=True,
        style_header=_HEADER_STYLE, style_cell=_CELL_STYLE,
        style_data={"backgroundColor": "rgba(255,255,255,0.85)"},
    )


def engine_metrics_table(df: pd.DataFrame, table_id: str, *, editable: bool) -> dash_table.DataTable:
    """Label (readonly) / Base / Now (editable) / Δ (readonly, computed).
    Called twice per page (Strength + ROM), so `table_id` must be distinct
    each time -- a duplicate Dash component id is invalid."""
    columns = [
        {"name": "", "id": "label", "editable": False},
        {"name": "Base", "id": "base_value", "editable": editable, "type": "numeric"},
        {"name": "Now", "id": "now_value", "editable": editable, "type": "numeric"},
        {"name": "Δ", "id": "delta", "editable": False},
    ]
    d = df.copy()
    d["delta"] = d["delta"].map(lambda v: "—" if pd.isna(v) else f"{v:+.1f}")
    return _table(table_id, columns, d.to_dict("records"), editable=editable)


def gas_station_table(df: pd.DataFrame, *, editable: bool) -> dash_table.DataTable:
    """Need (dropdown) / Exercise / Sets x Reps / Notes -- variable rows."""
    columns = [
        {"name": "Need", "id": "need", "editable": editable, "presentation": "dropdown"},
        {"name": "Exercise", "id": "exercise", "editable": editable},
        {"name": "Sets x Reps", "id": "sets_reps", "editable": editable},
        {"name": "Notes", "id": "notes", "editable": editable},
    ]
    dropdown = {"need": {"options": [{"label": v, "value": v} for v in
                                     SR.STRENGTH_NEED_OPTIONS]}}
    data = df[["need", "exercise", "sets_reps", "notes"]].to_dict("records") \
        if not df.empty else []
    if editable and len(data) < 8:
        data = data + [{"need": "", "exercise": "", "sets_reps": "", "notes": ""}
                      for _ in range(8 - len(data))]
    return _table("splash-gas-table", columns, data, editable=editable,
                 row_deletable=editable, dropdown=dropdown)


def script_pitch_table(df: pd.DataFrame, script_number: int, *,
                       editable: bool) -> dash_table.DataTable:
    """# (readonly 1-12) / Type / Ball / Info -- always exactly 12 rows."""
    columns = [
        {"name": "#", "id": "row_num", "editable": False},
        {"name": "Type", "id": "pitch_type", "editable": editable},
        {"name": "Ball", "id": "ball_info", "editable": editable},
        {"name": "Info", "id": "info", "editable": editable},
    ]
    return _table(f"splash-script-rows-{script_number}", columns,
                 df.to_dict("records"), editable=editable)


def pen_results_table(df: pd.DataFrame, *, editable: bool) -> dash_table.DataTable:
    """Script # / Pen Date / Value% -- variable rows, one shared table across
    all 6 scripts (pen_number is assigned from row order per script on save,
    so it isn't a user-facing column here)."""
    columns = [
        {"name": "Script #", "id": "script_number", "editable": editable, "type": "numeric"},
        {"name": "Pen Date", "id": "pen_date", "editable": editable},
        {"name": "Value %", "id": "value", "editable": editable, "type": "numeric"},
    ]
    data = df[["script_number", "pen_date", "value"]].to_dict("records") \
        if not df.empty else []
    if editable and len(data) < 6:
        data = data + [{"script_number": None, "pen_date": "", "value": None}
                      for _ in range(6 - len(data))]
    return _table("splash-pen-table", columns, data, editable=editable,
                 row_deletable=editable)
