"""Single composition root for the domain services behind AppController."""

from __future__ import annotations

from config.settings import Settings
from core.account_service import AccountService
from core.account_setup_service import AccountSetupService
from core.app_controller import AppController
from core.app_state_service import AppStateService
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


def build_reconciliation(database: Database) -> ReconciliationService:
    """Reconciliation service over ``database``; also used by the CSV worker."""
    return ReconciliationService(
        database, AccountService(database), LedgerService(database), PayeeService(database)
    )


def build_controller(database: Database, settings: Settings) -> AppController:
    """Wire every domain service exactly once, for production and tests alike."""
    accounts = AccountService(database)
    ledger = LedgerService(database)
    payees = PayeeService(database)
    categories = CategoryService(database, accounts)
    fx = FxService(database)
    reporting = ReportingService(database, fx, accounts, categories)
    scheduled = ScheduledTransactionService(database, accounts, ledger, payees)
    loans = LoanService(database, accounts, ledger)
    return AppController(
        database=database,
        settings=settings,
        accounts=accounts,
        ledger=ledger,
        books=BookService(database),
        payees=payees,
        categories=categories,
        account_setup=AccountSetupService(database, accounts, categories, ledger),
        fx=fx,
        reporting=reporting,
        reconciliation=build_reconciliation(database),
        reconciliation_factory=build_reconciliation,
        scheduled=scheduled,
        app_state=AppStateService(database, accounts),
        budgets=BudgetService(database, reporting, fx, accounts, categories),
        loans=loans,
        forecast=ForecastService(scheduled, fx, loans),
    )
