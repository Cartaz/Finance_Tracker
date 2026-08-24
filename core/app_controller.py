from __future__ import annotations

from config.constants import SCHEMA_VERSION
from config.settings import Settings
from core.account_service import AccountService
from core.database import Database
from core.ledger_service import LedgerService


class AppController:
    """Thin application coordinator for Finance Tracker services."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        account_service: AccountService,
        ledger_service: LedgerService,
    ) -> None:
        self._database = database
        self._settings = settings
        self._account_service = account_service
        self._ledger_service = ledger_service

    def initial_state(self) -> dict[str, object]:
        return {
            "app": "Finance Tracker",
            "schemaVersion": SCHEMA_VERSION,
            "bookCurrency": self._settings.book_currency,
            "locale": self._settings.locale,
            "reconciliationReviewMode": self._settings.reconciliation_review_mode,
        }
