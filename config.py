"""Central configuration. Loads secrets from .env (never hard-coded)."""
import os
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
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

    # Analytics DB (raw SQLAlchemy engine in app/db.py) — the Trackman warehouse.
    ANALYTICS_DB_URL = ANALYTICS_DB_URL

    # App DB (Flask-SQLAlchemy ORM) — user accounts / roles / notes / dev plans.
    SQLALCHEMY_DATABASE_URI = _resolve_app_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
