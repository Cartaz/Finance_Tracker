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
    db = Database(tmp_path / "m9-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    return db, accounts, controller, Bridge(controller)


def test_forecast_bridge_preserves_financial_integer_precision(tmp_path) -> None:
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
        salary = accounts.create_account(
            book_id=book_id,
            account_type="INCOME",
            name="Salary",
        )
        created = bridge.createScheduledTransaction(
            {
                "kind": "INCOME",
                "sourceAccountId": bank.id,
                "counterAccountId": salary.id,
                "amount": "90071992547409,93",
                "frequency": "MONTHLY",
                "interval": 1,
                "startDate": "2026-09-01",
                "description": "Large salary",
            }
        )
        assert created["ok"] is True

        result = bridge.getForecast(
            {
                "startDate": "2026-09-01",
                "endDate": "2026-09-30",
                "granularity": "MONTH",
            }
        )
        assert result["ok"] is True
        data = result["data"]
        expected = "9007199254740993"
        assert data["totalInflowMinor"] == expected
        assert data["totalNetMinor"] == expected
        assert data["buckets"][0]["inflowMinor"] == expected
        assert data["occurrences"][0]["amountMinor"] == expected
        assert data["occurrences"][0]["baseAmountMinor"] == expected
        assert isinstance(data["totalInflowMinor"], str)
    finally:
        db.close()


def test_forecast_bridge_returns_domain_errors_for_invalid_window(tmp_path) -> None:
    db, _, controller, bridge = _bridge_env(tmp_path)
    try:
        result = bridge.getForecast(
            {
                "startDate": "2026-10-01",
                "endDate": "2026-09-01",
                "granularity": "MONTH",
            }
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "ForecastError"
        assert "end_date cannot precede start_date" in result["error"]["message"]
        assert controller.snapshot()["book"]["id"]
    finally:
        db.close()
