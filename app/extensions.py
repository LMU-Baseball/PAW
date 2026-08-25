"""Flask extension singletons, initialized in the app factory."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()          # user/account store (app DB)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "error"

limiter = Limiter(
    key_func=get_remote_address,   # real client IP, thanks to ProxyFix
    default_limits=[],             # opt-in per route; no global limit
)
