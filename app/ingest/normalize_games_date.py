"""One-time: normalize GAMES.Date (mixed ISO + US m/d/yy) to ISO YYYY-MM-DD."""
from __future__ import annotations
from datetime import datetime
import pandas as pd
from sqlalchemy import text

_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")

def iso_date(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def normalize_dates(engine, *, dry_run: bool = True) -> dict:
    df = pd.read_sql(text("SELECT DISTINCT Date AS d FROM GAMES"), engine)
    scanned = would_change = unparseable = 0
    updates = []  # (old, new)
    for d in df["d"]:
        if d is None:
            continue
        scanned += 1
        new = iso_date(d)
        if new is None:
            unparseable += 1
            continue
        if str(d) != new:
            would_change += 1
            updates.append((str(d), new))
    if not dry_run and updates:
        with engine.begin() as conn:
            for old, new in updates:
                conn.execute(text("UPDATE GAMES SET Date = :new WHERE Date = :old"),
                             {"new": new, "old": old})
    return {"scanned": scanned, "would_change": would_change, "unparseable": unparseable}
