from __future__ import annotations

import pytest

from core.errors import LedgerValidationError
from core.money import MAX_PERSISTED_MINOR


def test_canonical_ledger_rejects_minor_units_outside_storage_range(ledger_env) -> None:
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-08-01",
    )
    expense = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Food",
    )
    before = ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0]

    with pytest.raises(LedgerValidationError, match="supported storage range"):
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=expense.id,
            amount_minor=MAX_PERSISTED_MINOR + 1,
            currency_code="EUR",
            transaction_date="2026-08-29",
        )

    after = ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0]
    assert after == before
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 0
