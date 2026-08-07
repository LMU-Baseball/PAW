"""Phase 3 regression guard: the app runtime must not query the warehouse.

After the tm_*/fact_*/dim_* warehouse was dropped, no runtime module may issue a
SQL query against a warehouse object. This walks the runtime packages and, for
every string passed to a DB entry point (query_df / text / execute / read_sql),
asserts it names no warehouse table or view. It inspects only SQL STRINGS via
AST -- so historical prose/comments mentioning the old tables are fine; only a
real query reintroducing a warehouse read fails.

app/ingest/ is intentionally EXCLUDED: the one-time backfill loaders legitimately
referenced the warehouse and are kept (dead after the drop; their tests mock the
DB seam).
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "app"
RUNTIME_DIRS = ["data", "dashboards", "reports", "main", "auth"]
DB_CALLS = {"query_df", "read_sql", "execute", "text"}
WAREHOUSE_TOKENS = (
    "fact_tm_game_pitch", "dim_tm_game", "dim_conference", "tm_player",
    "tm_team", "tm_umpire", "tm_ingest_file", "vw_pitch_video", "vw_pitcher_",
    "vw_game_pitchers", "vw_active_players", "vw_games", "vw_pitchers",
    "vw_cleaned_game_csv", "vw_available_seasons", "vw_available_game_types",
)


def _sql_literals_in_db_calls(tree: ast.AST) -> list[str]:
    """Every string constant appearing anywhere inside an argument to a DB call."""
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name not in DB_CALLS:
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
    return out


def test_runtime_modules_issue_no_warehouse_queries():
    offenders = []
    for d in RUNTIME_DIRS:
        for path in (ROOT / d).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for sql in _sql_literals_in_db_calls(tree):
                low = sql.lower()
                for tok in WAREHOUSE_TOKENS:
                    if tok in low:
                        offenders.append(f"{path.relative_to(ROOT.parent)}: query references '{tok}'")
    assert not offenders, "warehouse queries reintroduced:\n" + "\n".join(offenders)
