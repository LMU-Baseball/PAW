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


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

    # Analytics DB (raw SQLAlchemy engine in app/db.py) — the Trackman warehouse.
    ANALYTICS_DB_URL = ANALYTICS_DB_URL

    # App DB (Flask-SQLAlchemy ORM) — user accounts / roles. Separate on purpose.
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "APP_DATABASE_URL",
        "sqlite:///" + (BASE_DIR / "instance" / "paw_app.db").as_posix(),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
