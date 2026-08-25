from __future__ import annotations

import pytest

from core.errors import AccountNotFoundError, ScheduledTransactionError
from core.payee_service import PayeeService
from core.scheduled_transaction_service import ScheduledTransactionService


def _setup(ledger_env):
    accounts = ledger_env.accounts
    book = ledger_env.book_id
    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    savings = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Savings",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    usd = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="USD",
        currency_code="USD",
        tracking_start_date="2026-01-01",
    )
    expense = accounts.create_account(
        book_id=book, account_type="EXPENSE", name="Rent"
    )
    income = accounts.create_account(
        book_id=book, account_type="INCOME", name="Salary"
    )
    payees = PayeeService(ledger_env.db)
    landlord = payees.create_payee(book_id=book, name="Landlord")
    service = ScheduledTransactionService(
        ledger_env.db, accounts, ledger_env.ledger, payees
    )
    return service, bank, savings, usd, expense, income, landlord


def test_monthly_schedule_posts_once_per_due_date_and_clamps_month_end(ledger_env) -> None:
    service, bank, _, _, expense, _, landlord = _setup(ledger_env)
    schedule = service.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=expense.id,
        amount_minor=50_000,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-01-31",
        end_date="2026-04-30",
        description="Rent",
        payee_id=landlord.id,
    )

    posted = service.post_due(
        book_id=ledger_env.book_id,
        schedule_id=schedule.id,
        as_of_date="2026-04-30",
    )
    assert [item["dueDate"] for item in posted] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ]
    assert len({item["transactionId"] for item in posted}) == 4
    updated = service.get_schedule(ledger_env.book_id, schedule.id)
    assert updated.next_due_date == "2026-05-31"
    assert updated.active is False
    assert service.post_due(
        book_id=ledger_env.book_id,
        schedule_id=schedule.id,
        as_of_date="2026-12-31",
    ) == []
    rows = ledger_env.db.connection.execute(
        "SELECT due_date FROM scheduled_occurrences WHERE schedule_id=? ORDER BY due_date",
        (schedule.id,),
    ).fetchall()
    assert [row[0] for row in rows] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ]
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE payee_id=?", (landlord.id,)
    ).fetchone()[0] == 4


def test_income_refund_and_transfer_use_ledger_semantics(ledger_env) -> None:
    service, bank, savings, _, expense, income, _ = _setup(ledger_env)
    schedules = [
        service.create_schedule(
            book_id=ledger_env.book_id,
            kind="INCOME",
            source_account_id=bank.id,
            counter_account_id=income.id,
            amount_minor=100_000,
            frequency="MONTHLY",
            interval=1,
            start_date="2026-02-01",
        ),
        service.create_schedule(
            book_id=ledger_env.book_id,
            kind="REFUND",
            source_account_id=bank.id,
            counter_account_id=expense.id,
            amount_minor=2_000,
            frequency="MONTHLY",
            interval=1,
            start_date="2026-02-02",
        ),
        service.create_schedule(
            book_id=ledger_env.book_id,
            kind="TRANSFER",
            source_account_id=bank.id,
            counter_account_id=savings.id,
            amount_minor=20_000,
            frequency="MONTHLY",
            interval=1,
            start_date="2026-02-03",
        ),
    ]
    for schedule in schedules:
        result = service.post_due(
            book_id=ledger_env.book_id,
            schedule_id=schedule.id,
            as_of_date="2026-02-03",
        )
        assert len(result) == 1
    kinds = [
        row[0]
        for row in ledger_env.db.connection.execute(
            "SELECT kind FROM transactions ORDER BY id"
        ).fetchall()
    ]
    assert kinds == ["INCOME", "REFUND", "TRANSFER"]
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 82_000
    assert ledger_env.accounts.native_balance(ledger_env.book_id, savings.id) == 20_000


def test_catchup_limit_is_fail_closed_before_any_posting(ledger_env) -> None:
    service, bank, _, _, expense, _, _ = _setup(ledger_env)
    schedule = service.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=expense.id,
        amount_minor=100,
        frequency="DAILY",
        interval=1,
        start_date="2026-02-01",
    )
    before = ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    with pytest.raises(ScheduledTransactionError, match="limit"):
        service.post_due(
            book_id=ledger_env.book_id,
            schedule_id=schedule.id,
            as_of_date="2026-02-20",
            max_occurrences=10,
        )
    after = ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert after == before
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM scheduled_occurrences"
    ).fetchone()[0] == 0
    assert service.get_schedule(ledger_env.book_id, schedule.id).next_due_date == "2026-02-01"


def test_post_due_batch_rolls_back_all_schedules_if_one_becomes_invalid(ledger_env) -> None:
    service, bank, _, _, expense, income, _ = _setup(ledger_env)
    first = service.create_schedule(
        book_id=ledger_env.book_id,
        kind="INCOME",
        source_account_id=bank.id,
        counter_account_id=income.id,
        amount_minor=10_000,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-02-01",
    )
    second = service.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=expense.id,
        amount_minor=2_000,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-02-01",
    )
    ledger_env.accounts.set_archived(ledger_env.book_id, expense.id, True)
    before = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0],
    )
    with pytest.raises(ScheduledTransactionError):
        service.post_due(book_id=ledger_env.book_id, as_of_date="2026-02-01")
    after = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM scheduled_occurrences").fetchone()[0],
    )
    assert after == before
    assert service.get_schedule(ledger_env.book_id, first.id).next_due_date == "2026-02-01"
    assert service.get_schedule(ledger_env.book_id, second.id).next_due_date == "2026-02-01"


def test_invalid_schedule_inputs_and_cross_book_are_rejected(ledger_env) -> None:
    service, bank, _, usd, expense, income, _ = _setup(ledger_env)
    other = ledger_env.accounts.create_account(
        book_id=ledger_env.other_book_id,
        account_type="EXPENSE",
        name="Other",
    )
    common = {
        "book_id": ledger_env.book_id,
        "source_account_id": bank.id,
        "amount_minor": 100,
        "frequency": "MONTHLY",
        "interval": 1,
        "start_date": "2026-02-01",
    }
    invalid = (
        lambda: service.create_schedule(kind="NOPE", counter_account_id=expense.id, **common),
        lambda: service.create_schedule(kind="EXPENSE", counter_account_id=income.id, **common),
        lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "amount_minor": 0}),
        lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "frequency": "NEVER"}),
        lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "interval": 0}),
        lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, **{**common, "start_date": "2026-01-01"}),
        lambda: service.create_schedule(kind="EXPENSE", counter_account_id=expense.id, end_date="2026-01-31", **common),
        lambda: service.create_schedule(kind="TRANSFER", counter_account_id=usd.id, **common),
    )
    for operation in invalid:
        with pytest.raises(ScheduledTransactionError):
            operation()
    with pytest.raises(AccountNotFoundError):
        service.create_schedule(kind="EXPENSE", counter_account_id=other.id, **common)
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM scheduled_transactions"
    ).fetchone()[0] == 0
    ledger_env.db.integrity_check()
