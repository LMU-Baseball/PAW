"""All Things Process (hitters) leaderboard table.

Same shape as the pitcher board: the cycle and team-average rows pinned on
top, then a row per hitter. The LMU Team Average is the baseline -- a hitter
cell is blue when it is at or better than that average, red when worse, and
each column's leader is gold (applied last so it wins).
"""
from __future__ import annotations

from dash import dash_table
from dash.dash_table.Format import Format, Scheme, Symbol

from app.data import hitter_process_board as HB
from app.dashboards import shell
from app.dashboards.process_board.tables import LEADER, MEETS, MISSES, _HEADER

TABLE_ID = "hproc-grid"

_SUMMARY_BG = {"cycle": "#4A4A4A", "team": shell.BLUE}

_PCT = Format(precision=1, scheme=Scheme.fixed).symbol(Symbol.yes).symbol_suffix("%")
_EV = Format(precision=1, scheme=Scheme.fixed)


def columns() -> list[dict]:
    cols = [{"name": "Hitter", "id": "hitter", "type": "text"}]
    for key, label, _hib in HB.METRICS:
        cols.append({"name": label, "id": key, "type": "numeric",
                     "format": _EV if key in HB.EV_KEYS else _PCT})
    cols.append({"name": "Pitches", "id": "pitches", "type": "numeric"})
    return cols


def _sort_key(row: dict, col: str):
    v = row.get(col)
    return (v is None, v if v is not None else 0)


def records(board: dict, sort_by: list | None = None) -> list[dict]:
    """Table rows: summary rows first, hitters below in the chosen sort
    (alphabetical by default). Missing values always sort last."""
    hitters = [dict(r, kind="hitter") for r in board.get("hitters", [])]
    if sort_by:
        col, desc = sort_by[0]["column_id"], sort_by[0]["direction"] == "desc"
        present = [r for r in hitters if r.get(col) is not None]
        missing = [r for r in hitters if r.get(col) is None]
        hitters = sorted(present, key=lambda r: _sort_key(r, col), reverse=desc) + missing
    return list(board.get("summary", [])) + hitters


def _q(v) -> str:
    return repr(float(v))


def cell_styles(board: dict) -> list[dict]:
    styles = [{"if": {"filter_query": f"{{kind}} = '{kind}'"},
               "backgroundColor": bg, "color": "#fff", "fontWeight": "700"}
              for kind, bg in _SUMMARY_BG.items()]
    for key, _label, hib in HB.METRICS:
        target = board.get("baseline", {}).get(key)
        if target is None:
            continue
        good, bad = (">=", "<") if hib else ("<=", ">")
        base = f"{{kind}} = 'hitter' && {{{key}}} is num && {{{key}}}"
        styles.append({"if": {"filter_query": f"{base} {good} {_q(target)}", "column_id": key},
                       "backgroundColor": MEETS})
        styles.append({"if": {"filter_query": f"{base} {bad} {_q(target)}", "column_id": key},
                       "backgroundColor": MISSES})
    for key, best in board.get("best", {}).items():
        styles.append({"if": {"filter_query": f"{{kind}} = 'hitter' && {{{key}}} = {_q(best)}",
                              "column_id": key},
                       "backgroundColor": LEADER, "fontWeight": "700"})
    return styles


def hitter_table(board: dict) -> dash_table.DataTable:
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
            {"if": {"column_id": "hitter"}, "textAlign": "left", "fontWeight": "700",
             "minWidth": "190px"},
            {"if": {"column_id": "pitches"}, "color": "#777"},
        ],
        style_data_conditional=cell_styles(board),
    )
