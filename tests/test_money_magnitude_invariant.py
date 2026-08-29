from __future__ import annotations

import pytest

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.errors import MoneyParseError, MoneyRangeError
from core.ledger_service import LedgerService
from core.money import (
    MAX_PERSISTED_MINOR,
    CurrencySpec,
    parse_money,
    parse_money_magnitude,
)
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


def test_money_magnitude_is_exact_above_javascript_safe_integer() -> None:
    expected = 9_007_199_254_740_993
    assert expected > 2**53
    assert parse_money_magnitude("90071992547409,93", EUR) == expected


def test_money_magnitude_rejects_values_beyond_persistent_integer_range() -> None:
    assert parse_money_magnitude("92233720368547758,07", EUR) == MAX_PERSISTED_MINOR
    with pytest.raises(MoneyRangeError, match="Importo troppo grande per EUR"):
        parse_money_magnitude("92233720368547758,08", EUR)


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


def test_large_exact_bridge_amount_round_trips_as_string_and_overflow_is_atomic(tmp_path) -> None:
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
        exact_minor = 9_007_199_254_740_993

        accepted = bridge.createExpense(
            {
                "sourceAccountId": bank.id,
                "categoryAccountId": expense.id,
                "amount": "90071992547409,93",
                "date": "2026-08-29",
                "description": "D05 exact",
            }
        )
        assert accepted["ok"] is True
        snapshot = accepted["data"]["state"]
        transaction = next(
            item for item in snapshot["transactions"] if item["description"] == "D05 exact"
        )
        assert transaction["amountMinor"] == str(exact_minor)
        assert transaction["sourceAccountNames"] == ["Bank"]
        assert transaction["destinationAccountNames"] == []
        assert accounts.native_balance(book_id, bank.id) == -exact_minor

        count_before = db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        balance_before = accounts.native_balance(book_id, bank.id)
        rejected = bridge.createExpense(
            {
                "sourceAccountId": bank.id,
                "categoryAccountId": expense.id,
                "amount": "92233720368547758,08",
                "date": "2026-08-29",
            }
        )
        assert rejected["ok"] is False
        assert rejected["error"]["code"] == "MoneyRangeError"
        assert "Importo troppo grande per EUR" in rejected["error"]["message"]
        assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == count_before
        assert accounts.native_balance(book_id, bank.id) == balance_before
    finally:
        db.close()
