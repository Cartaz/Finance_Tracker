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
    db = Database(tmp_path / "m7-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    return db, accounts, controller, Bridge(controller)


def test_scheduled_bridge_preserves_large_minor_units_and_posts_due(tmp_path) -> None:
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
            name="Rent",
        )
        created = bridge.createScheduledTransaction(
            {
                "kind": "EXPENSE",
                "sourceAccountId": bank.id,
                "counterAccountId": expense.id,
                "amount": "90071992547409,93",
                "frequency": "MONTHLY",
                "interval": "1",
                "startDate": "2026-02-01",
                "description": "Huge rent",
            }
        )
        assert created["ok"] is True
        scheduled = bridge.listScheduledTransactions()
        assert scheduled["ok"] is True
        assert scheduled["data"][0]["amountMinor"] == "9007199254740993"
        assert isinstance(scheduled["data"][0]["amountMinor"], str)

        posted = bridge.postDueScheduled({"asOfDate": "2026-02-01"})
        assert posted["ok"] is True
        assert posted["data"]["count"] == 1
        assert accounts.native_balance(book_id, bank.id) == -9007199254740993
        assert db.connection.execute(
            "SELECT COUNT(*) FROM scheduled_occurrences"
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_scheduled_bridge_toggle_and_validation_are_domain_safe(tmp_path) -> None:
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
        income = accounts.create_account(
            book_id=book_id,
            account_type="INCOME",
            name="Salary",
        )
        created = bridge.createScheduledTransaction(
            {
                "kind": "INCOME",
                "sourceAccountId": bank.id,
                "counterAccountId": income.id,
                "amount": "1000,00",
                "frequency": "MONTHLY",
                "interval": "1",
                "startDate": "2026-02-01",
            }
        )
        schedule_id = created["data"]["id"]
        paused = bridge.setScheduledActive({"scheduleId": schedule_id, "active": False})
        assert paused["ok"] is True
        assert paused["data"]["active"] is False
        assert bridge.postDueScheduled({"asOfDate": "2026-02-01"})["data"]["count"] == 0
        resumed = bridge.setScheduledActive({"scheduleId": schedule_id, "active": True})
        assert resumed["ok"] is True
        assert resumed["data"]["active"] is True

        invalid = bridge.createScheduledTransaction(
            {
                "kind": "EXPENSE",
                "sourceAccountId": bank.id,
                "counterAccountId": income.id,
                "amount": "1,00",
                "frequency": "MONTHLY",
                "interval": "1",
                "startDate": "2026-02-01",
            }
        )
        assert invalid["ok"] is False
        assert invalid["error"]["code"] == "ScheduledTransactionError"
    finally:
        db.close()
