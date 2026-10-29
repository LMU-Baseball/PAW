"""All Things Process leaderboard table.

One DataTable: the three reference rows (LMU Baseline / selected cycle /
team average) pinned on top, then a row per pitcher. Pitcher cells are tinted
by whether they meet the coaches' baseline, and each column's leader gets the
Team Process sheet's gold highlight.
"""
from __future__ import annotations

from dash import dash_table
from dash.dash_table.Format import Format, Scheme, Symbol

from app.data import process_board as PB
from app.dashboards import shell

TABLE_ID = "process-grid"

LEADER = "#FFD54A"
MEETS = "#DCEFF7"
MISSES = "#F8DDE2"
_SUMMARY_BG = {"baseline": shell.CRIMSON, "cycle": "#4A4A4A", "team": shell.BLUE}

_PCT = Format(precision=1, scheme=Scheme.fixed).symbol(Symbol.yes).symbol_suffix("%")
_VELO = Format(precision=1, scheme=Scheme.fixed)

_HEADER = {
    "backgroundColor": "#161616", "color": "#fff", "fontWeight": "bold",
    "textTransform": "uppercase", "letterSpacing": "1px", "border": "none",
    "borderBottom": f"2px solid {shell.BLUE}",
}


def columns() -> list[dict]:
    cols = [{"name": "Pitcher", "id": "pitcher", "type": "text"}]
    cols += [{"name": label, "id": key, "type": "numeric", "format": _PCT}
             for key, label, _fn, _hib in PB.METRICS]
    cols += [{"name": label, "id": key, "type": "numeric", "format": _VELO}
             for key, label in PB.VELO_COLS]
    cols.append({"name": "Pitches", "id": "pitches", "type": "numeric"})
    return cols


def _sort_key(row: dict, col: str):
    v = row.get(col)
    return (v is None, v if v is not None else 0)


def records(board: dict, sort_by: list | None = None) -> list[dict]:
    """Table rows: reference rows always first, pitchers below in the coach's
    chosen sort (alphabetical by default, like the sheet). Missing values
    always sort last regardless of direction."""
    pitchers = [dict(r, kind="pitcher") for r in board.get("pitchers", [])]
    if sort_by:
        col, desc = sort_by[0]["column_id"], sort_by[0]["direction"] == "desc"
        present = [r for r in pitchers if r.get(col) is not None]
        missing = [r for r in pitchers if r.get(col) is None]
        pitchers = sorted(present, key=lambda r: _sort_key(r, col), reverse=desc) + missing
    return list(board.get("summary", [])) + pitchers


def _q(v) -> str:
    return repr(float(v))


def cell_styles(board: dict) -> list[dict]:
    """Conditional styles: summary-row fills, baseline tint per pitcher cell,
    gold for each column's leader (applied last so it wins)."""
    styles = [{"if": {"filter_query": f"{{kind}} = '{kind}'"},
               "backgroundColor": bg, "color": "#fff", "fontWeight": "700"}
              for kind, bg in _SUMMARY_BG.items()]
    for key, _label, _fn, hib in PB.METRICS:
        target = PB.BASELINE.get(key)
        if target is None:
            continue
        good, bad = (">=", "<") if hib else ("<=", ">")
        base = f"{{kind}} = 'pitcher' && {{{key}}} is num && {{{key}}}"
        styles.append({"if": {"filter_query": f"{base} {good} {_q(target)}", "column_id": key},
                       "backgroundColor": MEETS})
        styles.append({"if": {"filter_query": f"{base} {bad} {_q(target)}", "column_id": key},
                       "backgroundColor": MISSES})
    for key, best in board.get("best", {}).items():
        styles.append({"if": {"filter_query": f"{{kind}} = 'pitcher' && {{{key}}} = {_q(best)}",
                              "column_id": key},
                       "backgroundColor": LEADER, "fontWeight": "700"})
    return styles


def process_table(board: dict) -> dash_table.DataTable:
    return dash_table.DataTable(
        id=TABLE_ID,
        columns=columns(),
        data=records(board),
        sort_action="custom",
        sort_mode="single",
        sort_by=[],
        style_table={"overflowX": "auto"},
        style_header=_HEADER,
        style_cell={"fontFamily": "Teko, Arial, sans-serif", "fontSize": "17px",
                    "padding": "6px 12px", "textAlign": "center",
                    "border": "1px solid #d9d9d9", "backgroundColor": "#fff",
                    "color": "#161616"},
        style_cell_conditional=[
            {"if": {"column_id": "pitcher"}, "textAlign": "left", "fontWeight": "700",
             "minWidth": "190px"},
            {"if": {"column_id": "pitches"}, "color": "#777"},
        ],
        style_data_conditional=cell_styles(board),
    )
