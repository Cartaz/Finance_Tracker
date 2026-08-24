from __future__ import annotations

import random

import pytest

from core.category_service import CategoryService
from core.errors import FinanceTrackerError
from core.fx_service import FxService
from core.payee_service import PayeeService
from core.reporting_service import ReportingService


def test_m5_reporting_two_thousand_case_stress(ledger_env) -> None:
    """Stress M5 with 1,000 valid reads and 1,000 invalid/edge-case requests."""

    rng = random.Random(20260824)
    db = ledger_env.db
    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    book = ledger_env.book_id

    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Stress bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    usd = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Stress USD",
        currency_code="USD",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    equity = accounts.create_account(
        book_id=book,
        account_type="EQUITY",
        name="Stress equity",
    )
    categories = CategoryService(db, accounts)
    expense_categories = [
        categories.create_category(
            book_id=book,
            category_type="EXPENSE",
            name=f"Stress expense {index}",
        )
        for index in range(8)
    ]
    income_category = categories.create_category(
        book_id=book,
        category_type="INCOME",
        name="Stress income",
    )
    payees = PayeeService(db)
    merchants = [
        payees.create_payee(book_id=book, name=f"Stress merchant {index}")
        for index in range(10)
    ]

    ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=5_000_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )
    ledger.create_opening_balance(
        book_id=book,
        account_id=usd.id,
        equity_account_id=equity.id,
        quantity_minor=1_000_000,
        currency_code="USD",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )

    for index in range(300):
        day = 1 + index % 28
        if index % 5 == 0:
            ledger.create_income(
                book_id=book,
                destination_account_id=bank.id,
                income_account_id=income_category.id,
                amount_minor=10_000 + index,
                currency_code="EUR",
                transaction_date=f"2026-02-{day:02d}",
            )
        else:
            transaction = ledger.create_expense(
                book_id=book,
                source_account_id=bank.id,
                expense_account_id=rng.choice(expense_categories).id,
                amount_minor=100 + index,
                currency_code="EUR",
                transaction_date=f"2026-02-{day:02d}",
            )
            payees.assign_transaction(
                book_id=book,
                transaction_id=transaction.id,
                payee_id=rng.choice(merchants).id,
            )

    fx = FxService(db)
    fx.set_rate(
        book_id=book,
        currency_code="USD",
        rate_date="2026-01-01",
        rate="0.92",
    )
    reporting = ReportingService(db, fx, accounts, categories)

    before_transactions = db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0]
    before_entries = db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    before_fx = db.connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0]

    for index in range(1_000):
        mode = index % 5
        if mode == 0:
            result = reporting.overview(
                book_id=book,
                start_date="2026-02-01",
                end_date="2026-02-28",
                as_of_date="2026-02-28",
            )
            assert result["complete"] is True
        elif mode == 1:
            result = reporting.category_report(
                book_id=book,
                start_date="2026-02-01",
                end_date="2026-02-28",
                limit=8,
            )
            assert result
        elif mode == 2:
            result = reporting.merchant_report(
                book_id=book,
                start_date="2026-02-01",
                end_date="2026-02-28",
                limit=10,
            )
            assert result
        elif mode == 3:
            result = reporting.cash_flow(
                book_id=book,
                start_date="2026-02-01",
                end_date="2026-02-28",
                granularity=("DAY", "MONTH", "YEAR")[index % 3],
            )
            assert result
        else:
            result = reporting.account_history(
                book_id=book,
                account_id=bank.id if index % 2 else usd.id,
                start_date="2026-01-01",
                end_date="2026-02-28",
            )
            assert result["complete"] is True

    invalid_actions = (
        lambda: reporting.overview(
            book_id=book,
            start_date="2026-03-01",
            end_date="2026-02-01",
            as_of_date="2026-03-01",
        ),
        lambda: reporting.category_report(
            book_id=book,
            start_date="2026-02-01",
            end_date="2026-02-28",
            category_type="ASSET",
        ),
        lambda: reporting.category_report(
            book_id=book,
            start_date="2026-02-01",
            end_date="2026-02-28",
            limit=0,
        ),
        lambda: reporting.cash_flow(
            book_id=book,
            start_date="2026-02-01",
            end_date="2026-02-28",
            granularity="WEEK",
        ),
        lambda: reporting.account_history(
            book_id=book,
            account_id=expense_categories[0].id,
            start_date="2026-02-01",
            end_date="2026-02-28",
        ),
        lambda: reporting.account_history(
            book_id=ledger_env.other_book_id,
            account_id=bank.id,
            start_date="2026-02-01",
            end_date="2026-02-28",
        ),
        lambda: fx.set_rate(
            book_id=book,
            currency_code="EUR",
            rate_date="2026-02-01",
            rate="1",
        ),
        lambda: fx.set_rate(
            book_id=book,
            currency_code="USD",
            rate_date="bad-date",
            rate="1",
        ),
        lambda: fx.set_rate(
            book_id=book,
            currency_code="USD",
            rate_date="2026-02-01",
            rate="0",
        ),
        lambda: fx.set_rate(
            book_id=book,
            currency_code="USD",
            rate_date="2026-02-01",
            rate=1.1,  # type: ignore[arg-type]
        ),
    )
    for index in range(1_000):
        with pytest.raises(FinanceTrackerError):
            invalid_actions[index % len(invalid_actions)]()

    assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before_transactions
    assert db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == before_entries
    assert db.connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == before_fx
    db.integrity_check()
    assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()
