"""Flask extension singletons, initialized in the app factory."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()          # user/account store (app DB)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "error"


def add_missing_columns(engine, specs) -> None:
    """Add columns that shipped after their table did: `specs` is
    (table, column, DDL). create_all() never alters an existing table, so this
    is how new columns reach the deployed DB -- additive only, skipped when the
    column (or the whole table) isn't there to alter, safe on every boot."""
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, col, ddl in specs:
            if table not in tables:
                continue
            if col not in {c["name"] for c in inspect(conn).get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


# Module-level singleton, re-initialized per app via init_app(). flask_limiter
# stores its `enabled` flag on THIS shared object and re-assigns it on every
# init_app() call (from RATELIMIT_ENABLED in the app's config) rather than
# reading current_app.config per request. That is only safe because every
# test today builds a fresh app per test function/module -- a future
# module- or session-scoped Flask test client fixture shared across tests
# with different RATELIMIT_ENABLED values would clobber this flag out from
# under a sibling test.
limiter = Limiter(
    key_func=get_remote_address,   # real client IP, thanks to ProxyFix
    default_limits=[],             # opt-in per route; no global limit
)
