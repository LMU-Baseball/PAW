"""Config for the Trackman SFTP / HitTrax FTPS ingestion loaders.

Follows the same dotenv pattern as the root ``config.py``: secrets come only
from environment variables (loaded via python-dotenv), never hard-coded, and
are never printed/logged.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root .env (this file lives at <repo>/app/ingest/config.py).
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"{key} not set")
    return val


def trackman_cfg() -> dict:
    """Trackman SFTP connection settings, read from TM_SFTP_* env vars."""
    return {
        "host": _require("TM_SFTP_HOST"),
        "port": int(os.getenv("TM_SFTP_PORT", "22")),
        "user": _require("TM_SFTP_USER"),
        "password": _require("TM_SFTP_PASS"),
    }


def hittrax_cfg() -> dict:
    """HitTrax FTPS connection settings, read from HT_FTPS_* env vars."""
    return {
        "host": _require("HT_FTPS_HOST"),
        "port": int(os.getenv("HT_FTPS_PORT", "21")),
        "user": _require("HT_FTPS_USER"),
        "password": _require("HT_FTPS_PASSWORD"),
        "remote_dir": _require("HT_FTPS_REMOTE_DIR"),
    }
