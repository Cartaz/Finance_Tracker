from __future__ import annotations

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from ui.bridge import Bridge


def _bridge_env(tmp_path):
    db = Database(tmp_path / "m8-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    return db, accounts, controller, Bridge(controller)


def test_budget_bridge_preserves_large_minor_units_and_reports_spending(tmp_path) -> None:
    db, accounts, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        bank = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Bank",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        expense = accounts.create_account(
            book_id=book_id,
            account_type="EXPENSE",
            name="Housing",
        )
        created = bridge.setBudget(
            {
                "categoryAccountId": expense.id,
                "period": "2026-08",
                "amount": "90071992547409,93",
            }
        )
        assert created["ok"] is True
        assert created["data"]["amountMinor"] == "9007199254740993"
        assert isinstance(created["data"]["amountMinor"], str)

        ledger = LedgerService(db)
        ledger.create_expense(
            book_id=book_id,
            source_account_id=bank.id,
            expense_account_id=expense.id,
            amount_minor=12_345,
            currency_code="EUR",
            transaction_date="2026-08-15",
        )
        status = bridge.getBudgetStatus({"period": "2026-08"})
        assert status["ok"] is True
        data = status["data"]
        assert data["totalBudgetMinor"] == "9007199254740993"
        assert data["totalSpentMinor"] == "12345"
        assert data["budgets"][0]["spentMinor"] == "12345"
        assert isinstance(data["budgets"][0]["remainingMinor"], str)
        assert isinstance(data["budgets"][0]["usageBps"], str)
    finally:
        db.close()


def test_budget_bridge_rejects_float_and_supports_delete(tmp_path) -> None:
    db, accounts, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        expense = accounts.create_account(
            book_id=book_id,
            account_type="EXPENSE",
            name="Food",
        )
        bad = bridge.setBudget(
            {
                "categoryAccountId": expense.id,
                "period": "2026-09",
                "amount": 12.50,
            }
        )
        assert bad["ok"] is False
        assert bad["error"]["code"] == "MoneyParseError"

        created = bridge.setBudget(
            {
                "categoryAccountId": expense.id,
                "period": "2026-09",
                "amount": "12,50",
            }
        )
        budget_id = created["data"]["id"]
        deleted = bridge.deleteBudget({"budgetId": budget_id})
        assert deleted == {"ok": True, "data": {"deletedBudgetId": budget_id}}
        status = bridge.getBudgetStatus({"period": "2026-09"})
        assert status["data"]["budgets"] == []
    finally:
        db.close()
