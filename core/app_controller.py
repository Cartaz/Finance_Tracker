from __future__ import annotations

from config.settings import Settings
from core.database import Database


class AppController:
    """Thin application coordinator for the foundation milestone."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def initial_state(self) -> dict[str, object]:
        return {
            "app": "Finance Tracker",
            "schemaVersion": 1,
            "bookCurrency": self._settings.book_currency,
            "locale": self._settings.locale,
            "reconciliationReviewMode": self._settings.reconciliation_review_mode,
        }
