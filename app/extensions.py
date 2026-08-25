"""Flask extension singletons, initialized in the app factory."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()          # user/account store (app DB)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "error"


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
