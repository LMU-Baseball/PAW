"""Dash callbacks for the hitter All Things Process board: the same Season /
Cycle / Game Type / Dates / Games filter flow as the pitcher board."""
from __future__ import annotations

from app.data import hitter_process_board as HB
from app.dashboards.hitter_process_board import tables
from app.dashboards.process_board.callbacks import register_filter_callbacks


def register_callbacks(dash_app) -> None:
    register_filter_callbacks(dash_app, "hproc", HB, tables)
