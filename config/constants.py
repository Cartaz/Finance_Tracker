from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Finance Tracker"
APP_SLUG = "finance-tracker"
SCHEMA_VERSION = 3
DEFAULT_BOOK_CURRENCY = "EUR"
DEFAULT_LOCALE = "it_IT"
DEFAULT_RECONCILIATION_REVIEW_MODE = "FULL_REVIEW"


def _xdg_path(env_name: str, fallback: Path) -> Path:
    raw = os.environ.get(env_name)
    return Path(raw).expanduser() if raw else fallback


HOME = Path.home()
DATA_DIR = _xdg_path("XDG_DATA_HOME", HOME / ".local" / "share") / APP_SLUG
CONFIG_DIR = _xdg_path("XDG_CONFIG_HOME", HOME / ".config") / APP_SLUG
CACHE_DIR = _xdg_path("XDG_CACHE_HOME", HOME / ".cache") / APP_SLUG

DATABASE_PATH = DATA_DIR / "finance.db"
BACKUP_DIR = DATA_DIR / "backups"
IMPORT_DIR = DATA_DIR / "imports"
LOAN_DOCUMENT_DIR = DATA_DIR / "loan-documents"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
