from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from config.constants import (
    BACKUP_DIR,
    CONFIG_DIR,
    DATA_DIR,
    IMPORT_DIR,
    LOAN_DOCUMENT_DIR,
    LOG_DIR,
)
from config.settings import SettingsStore
from core.account_service import AccountService
from core.app_controller import AppController
from core.app_state_service import AppStateService
from core.backup_controller import BackupController
from core.backup_service import BackupService
from core.book_service import BookService
from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.database import Database
from core.forecast_service import ForecastService
from core.fx_service import FxService
from core.ledger_service import LedgerService
from core.loan_service import LoanService
from core.payee_service import PayeeService
from core.reconciliation_service import ReconciliationService
from core.reporting_service import ReportingService
from core.scheduled_transaction_service import ScheduledTransactionService
from ui.backup_task_manager import BackupTaskManager
from ui.bridge import Bridge
from ui.window import MainWindow

log = logging.getLogger(__name__)


def _ensure_directories() -> None:
    for path in (DATA_DIR, CONFIG_DIR, BACKUP_DIR, IMPORT_DIR, LOAN_DOCUMENT_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError as exc:
            log.warning("Could not restrict directory permissions for %s: %s", path, exc)


def _configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "finance-tracker.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    database = Database()
    try:
        _ensure_directories()
        _configure_logging()
        settings = SettingsStore().load()
        database.open()
        database.migrate()
        database.integrity_check()
        account_service = AccountService(database)
        ledger_service = LedgerService(database)
        book_service = BookService(database)
        payee_service = PayeeService(database)
        category_service = CategoryService(database, account_service)
        fx_service = FxService(database)
        reporting_service = ReportingService(
            database,
            fx_service,
            account_service,
            category_service,
        )
        reconciliation_service = ReconciliationService(
            database,
            account_service,
            ledger_service,
            payee_service,
        )
        scheduled_service = ScheduledTransactionService(
            database,
            account_service,
            ledger_service,
            payee_service,
        )
        budget_service = BudgetService(
            database,
            reporting_service,
            fx_service,
            account_service,
            category_service,
        )
        loan_service = LoanService(database, account_service, ledger_service)
        forecast_service = ForecastService(scheduled_service, fx_service, loan_service)
        app_state_service = AppStateService(database, account_service)
        backup_controller = BackupController(BackupService(database, BACKUP_DIR))
        app = QApplication(sys.argv)
        app.setApplicationName("Finance Tracker")
        controller = AppController(
            database,
            settings,
            account_service,
            ledger_service,
            book_service,
            payee_service,
            fx_service,
            reporting_service,
            reconciliation_service,
            scheduled_service,
            app_state_service,
            budget_service,
            forecast_service,
            loan_service,
        )
        backup_tasks = BackupTaskManager(backup_controller, controller.error_payload)
        bridge = Bridge(controller, backup_tasks)
        window = MainWindow(bridge, backup_tasks)
        window.show()
        return app.exec()
    except Exception:
        log.exception("Finance Tracker failed to start")
        return 1
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
