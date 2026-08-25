from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from config.constants import (
    DEFAULT_BOOK_CURRENCY,
    DEFAULT_LOCALE,
    DEFAULT_RECONCILIATION_REVIEW_MODE,
    SETTINGS_PATH,
)

log = logging.getLogger(__name__)

_ALLOWED_REVIEW_MODES = {"FULL_REVIEW", "ASSISTED_REVIEW"}


@dataclass(slots=True)
class Settings:
    book_currency: str = DEFAULT_BOOK_CURRENCY
    locale: str = DEFAULT_LOCALE
    reconciliation_review_mode: str = DEFAULT_RECONCILIATION_REVIEW_MODE

    def validate(self) -> None:
        if len(self.book_currency) != 3 or not self.book_currency.isalpha():
            raise ValueError("book_currency must be a three-letter currency code")
        self.book_currency = self.book_currency.upper()
        if self.reconciliation_review_mode not in _ALLOWED_REVIEW_MODES:
            raise ValueError("invalid reconciliation_review_mode")


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self._path = path

    def load(self) -> Settings:
        if not self._path.exists():
            settings = Settings()
            settings.validate()
            return settings

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load settings from %s; using defaults: %s", self._path, exc)
            settings = Settings()
            settings.validate()
            return settings

        defaults = asdict(Settings())
        defaults.update({key: value for key, value in raw.items() if key in defaults})
        try:
            settings = Settings(**defaults)
            settings.validate()
        except (TypeError, ValueError) as exc:
            log.warning("Invalid settings in %s; using defaults: %s", self._path, exc)
            settings = Settings()
            settings.validate()
        return settings

    def save(self, settings: Settings) -> None:
        settings.validate()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._path)
