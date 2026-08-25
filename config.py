"""Central configuration. Loads secrets from .env (never hard-coded)."""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


def is_production() -> bool:
    """True only when PAW_ENV is explicitly "production".

    Deliberately NOT inferred from Render's auto-set RENDER variable: RENDER is
    already set on the live host, so inferring from it would activate the
    SECRET_KEY boot guard the moment this merges. It also does not exist on
    Lightsail, so it would silently disable production behavior after the AWS
    move. An explicit variable is both safe to merge and portable.
    """
    return os.getenv("PAW_ENV", "").strip().lower() == "production"


def _resolve_secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if is_production():
        raise RuntimeError(
            "SECRET_KEY must be set when PAW_ENV=production. Without it Flask "
            "would sign session cookies with a value published in this public "
            "repo, letting anyone forge a login. Set SECRET_KEY in the host's "
            "environment (Render dashboard / the .env on Lightsail)."
        )
    return "dev-only-change-me"


# Built with URL.create so special characters in the password ($, #, etc.)
# are escaped correctly.
ANALYTICS_DB_URL = URL.create(
    "mysql+pymysql",
    username=_require("MYSQL_USER"),
    password=_require("MYSQL_PASSWORD"),
    host=_require("MYSQL_HOST"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=_require("MYSQL_DB"),
)


def _resolve_app_db_uri():
    """App DB (Flask-SQLAlchemy ORM) — user accounts / roles / coach notes / dev
    plans. Separate from the analytics warehouse on purpose. Resolution order:

    1. APP_DATABASE_URL — an explicit full URL (advanced/override).
    2. APP_DB_NAME — a schema on the SAME RDS server as the analytics DB, built
       from the MYSQL_* creds so a password with special chars ($, #) is escaped
       correctly (e.g. APP_DB_NAME=paw_app). Makes accounts/notes/dev-plans
       durable + shared on a host with an ephemeral disk (Render free tier).
    3. Local SQLite — the default for dev.
    """
    explicit = os.getenv("APP_DATABASE_URL")
    if explicit:
        return explicit
    app_db_name = os.getenv("APP_DB_NAME")
    if app_db_name:
        return ANALYTICS_DB_URL.set(database=app_db_name)
    return "sqlite:///" + (BASE_DIR / "instance" / "paw_app.db").as_posix()


class Config:
    SECRET_KEY = _resolve_secret_key()

    # Analytics DB (raw SQLAlchemy engine in app/db.py) — the Trackman warehouse.
    ANALYTICS_DB_URL = ANALYTICS_DB_URL

    # App DB (Flask-SQLAlchemy ORM) — user accounts / roles / notes / dev plans.
    SQLALCHEMY_DATABASE_URI = _resolve_app_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- session cookie hardening ---
    # HTTPONLY + SameSite=Lax are safe on plain HTTP, so they are always on.
    # SameSite=Lax is also what protects Dash's callback POSTs: a global
    # CSRFProtect would break every Dash callback (Dash sends no CSRF token),
    # so do NOT add one -- see the spec's "Deliberately NOT done" section.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # A browser silently DROPS a Secure cookie sent over plain HTTP, which
    # makes login appear to do nothing. Production-gated for that reason.
    SESSION_COOKIE_SECURE = is_production()

    # 30-day sliding window: refreshed on every request, so anyone using PAW
    # regularly is never logged out, while an abandoned or stolen cookie still
    # expires on its own.
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_REFRESH_EACH_REQUEST = True

    # Future-proofing, currently inert: login_user(user) in app/auth/routes.py
    # never passes remember=True, so Flask-Login never issues a remember
    # cookie and these settings have nothing to apply to yet. Left configured
    # so a future remember-me feature is secure by default from the moment
    # it's turned on, instead of needing someone to remember these too.
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = is_production()
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    # Flask-Limiter reads this. Off under test so the 17 test files that POST
    # to /login are unaffected; app/__init__.py re-derives it from TESTING.
    RATELIMIT_ENABLED = True
