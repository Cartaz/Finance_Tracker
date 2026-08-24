from __future__ import annotations

import pytest

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.errors import MoneyParseError
from core.ledger_service import LedgerService
from core.money import CurrencySpec, parse_money, parse_money_magnitude
from core.payee_service import PayeeService
from ui.bridge import Bridge

EUR = CurrencySpec("EUR", 2)


@pytest.mark.parametrize("raw", ["-45", "+45", " -45,00 ", " +45.00 "])
def test_money_magnitude_rejects_explicit_sign(raw: str) -> None:
    with pytest.raises(MoneyParseError, match="must not include a sign"):
        parse_money_magnitude(raw, EUR)


@pytest.mark.parametrize("raw", ["0", "0,00", "0.00"])
def test_money_magnitude_rejects_zero(raw: str) -> None:
    with pytest.raises(MoneyParseError, match="greater than zero"):
        parse_money_magnitude(raw, EUR)


def test_money_magnitude_accepts_unsigned_value_while_signed_parser_remains_available() -> None:
    assert parse_money_magnitude("45,00", EUR) == 4_500
    assert parse_money("-45,00", EUR) == -4_500
    assert parse_money("+45,00", EUR) == 4_500


def _bridge_env(tmp_path):
    db = Database(tmp_path / "magnitude-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    return db, accounts, controller, Bridge(controller)


def test_user_transaction_and_budget_inputs_reject_explicit_signs(tmp_path) -> None:
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
            name="Food",
        )

        for amount in ("-45", "+45"):
            manual = bridge.createExpense(
                {
                    "sourceAccountId": bank.id,
                    "categoryAccountId": expense.id,
                    "amount": amount,
                    "date": "2026-08-24",
                }
            )
            assert manual["ok"] is False
            assert manual["error"]["code"] == "MoneyParseError"
            assert "must not include a sign" in manual["error"]["message"]

            scheduled = bridge.createScheduledTransaction(
                {
                    "kind": "EXPENSE",
                    "sourceAccountId": bank.id,
                    "counterAccountId": expense.id,
                    "amount": amount,
                    "frequency": "MONTHLY",
                    "interval": "1",
                    "startDate": "2026-09-01",
                }
            )
            assert scheduled["ok"] is False
            assert scheduled["error"]["code"] == "MoneyParseError"
            assert "must not include a sign" in scheduled["error"]["message"]

            budget = bridge.setBudget(
                {
                    "categoryAccountId": expense.id,
                    "period": "2026-09",
                    "amount": amount,
                }
            )
            assert budget["ok"] is False
            assert budget["error"]["code"] == "MoneyParseError"
            assert "must not include a sign" in budget["error"]["message"]

        assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert db.connection.execute("SELECT COUNT(*) FROM scheduled_transactions").fetchone()[0] == 0
        assert db.connection.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0
    finally:
        db.close()
