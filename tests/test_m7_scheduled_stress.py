from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database
from core.errors import AccountNotFoundError, ScheduledTransactionError
from core.payee_service import PayeeService
from core.scheduled_transaction_service import ScheduledTransactionService


def test_m7_thousand_occurrences_and_invalid_state_stress(
    ledger_env, tmp_path: Path
) -> None:
    db = ledger_env.db
    book = ledger_env.book_id
    accounts = ledger_env.accounts
    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="M7 Bank",
        currency_code="EUR",
        tracking_start_date="2025-12-31",
    )
    savings = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="M7 Savings",
        currency_code="EUR",
        tracking_start_date="2025-12-31",
    )
    usd = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="M7 USD",
        currency_code="USD",
        tracking_start_date="2025-12-31",
    )
    expense = accounts.create_account(
        book_id=book, account_type="EXPENSE", name="M7 Expense"
    )
    income = accounts.create_account(
        book_id=book, account_type="INCOME", name="M7 Income"
    )
    placeholder = accounts.create_account(
        book_id=book,
        account_type="EXPENSE",
        name="M7 Placeholder",
        placeholder=True,
    )
    archived = accounts.create_account(
        book_id=book, account_type="EXPENSE", name="M7 Archived"
    )
    accounts.set_archived(book, archived.id, True)
    other_book_counter = accounts.create_account(
        book_id=ledger_env.other_book_id,
        account_type="EXPENSE",
        name="Other M7 Expense",
    )
    payees = PayeeService(db)
    payee = payees.create_payee(book_id=book, name="M7 Merchant")
    service = ScheduledTransactionService(db, accounts, ledger_env.ledger, payees)

    schedules = []
    for index in range(100):
        kind = "EXPENSE" if index % 2 == 0 else "INCOME"
        schedules.append(
            service.create_schedule(
                book_id=book,
                kind=kind,
                source_account_id=bank.id,
                counter_account_id=expense.id if kind == "EXPENSE" else income.id,
                amount_minor=100 + index,
                frequency="DAILY",
                interval=1,
                start_date="2026-01-01",
                end_date="2026-01-10",
                description=f"stress {index}",
                payee_id=payee.id if kind == "EXPENSE" else None,
            )
        )
    posted = service.post_due(
        book_id=book,
        as_of_date="2026-01-10",
        max_occurrences=1000,
    )
    assert len(posted) == 1000
    assert len({item["transactionId"] for item in posted}) == 1000
    assert db.connection.execute(
        "SELECT COUNT(*) FROM scheduled_occurrences WHERE book_id=?", (book,)
    ).fetchone()[0] == 1000
    assert db.connection.execute(
        "SELECT COUNT(*) FROM scheduled_transactions WHERE book_id=? AND active=0", (book,)
    ).fetchone()[0] == 100
    assert service.post_due(book_id=book, as_of_date="2026-12-31") == []

    limited = service.create_schedule(
        book_id=book,
        kind="TRANSFER",
        source_account_id=bank.id,
        counter_account_id=savings.id,
        amount_minor=500,
        frequency="DAILY",
        interval=1,
        start_date="2026-02-01",
    )
    before_limit = (
        db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0],
    )
    with pytest.raises(ScheduledTransactionError):
        service.post_due(
            book_id=book,
            schedule_id=limited.id,
            as_of_date="2026-02-20",
            max_occurrences=10,
        )
    assert (
        db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0],
    ) == before_limit

    stable_counts = (
        db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM scheduled_transactions").fetchone()[0],
        db.connection.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0],
    )
    common = {
        "book_id": book,
        "source_account_id": bank.id,
        "amount_minor": 100,
        "frequency": "MONTHLY",
        "interval": 1,
        "start_date": "2026-03-01",
    }
    invalid_cases = (
        (ScheduledTransactionError, lambda: service.create_schedule(kind="UNKNOWN", counter_account_id=expense.id, **common)),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=income.id, **common)),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=placeholder.id, **common)),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=archived.id, **common)),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="TRANSFER", counter_account_id=usd.id, **common)),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "amount_minor": 0})),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "frequency": "NOPE"})),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "interval": 0})),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "start_date": "2025-12-31"})),
        (ScheduledTransactionError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, end_date="2026-02-28", **common)),
        (AccountNotFoundError, lambda: service.create_schedule(kind="EXPENSE", counter_account_id=other_book_counter.id, **common)),
        (ScheduledTransactionError, lambda: service.get_schedule(book, 999_999_999)),
        (ScheduledTransactionError, lambda: service.set_active(book, schedules[0].id, True)),
    )
    for index in range(1000):
        expected, operation = invalid_cases[index % len(invalid_cases)]
        with pytest.raises(expected):
            operation()
        assert (
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM scheduled_transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0],
        ) == stable_counts

    db.integrity_check()
    backup = tmp_path / "m7-backup.db"
    db.backup_to(backup)
    restored = Database(backup)
    restored.open()
    try:
        restored.integrity_check()
        assert restored.connection.execute(
            "SELECT COUNT(*) FROM scheduled_transactions"
        ).fetchone()[0] == 101
        assert restored.connection.execute(
            "SELECT COUNT(*) FROM scheduled_occurrences"
        ).fetchone()[0] == 1000
    finally:
        restored.close()
