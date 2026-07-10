"""Analytics database access: a single pooled engine + a DataFrame helper.

Mirrors the R apps' get_con()/dbGetQuery() pattern, but with one shared
connection pool instead of open-close-per-query.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import Config

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            Config.ANALYTICS_DB_URL,
            pool_pre_ping=True,   # validate connections before use (RDS drops idle ones)
            pool_recycle=3600,
        )
    return _engine


def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame. Use :named params."""
    return pd.read_sql(text(sql), get_engine(), params=params or {})
