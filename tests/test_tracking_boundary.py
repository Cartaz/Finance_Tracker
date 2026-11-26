from __future__ import annotations

import pytest

from core.errors import ScheduledTransactionError
from core.payee_service import PayeeService
from core.scheduled_transaction_service import ScheduledTransactionService


def test_transfer_schedule_validates_both_balance_account_tracking_boundaries(
    ledger_env,
) -> None:
    accounts = ledger_env.accounts
    book = ledger_env.book_id
    source = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Source",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    destination = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Destination",
        currency_code="EUR",
        tracking_start_date="2026-03-01",
    )
    service = ScheduledTransactionService(
        ledger_env.db,
        accounts,
        ledger_env.ledger,
        PayeeService(ledger_env.db),
    )

    with pytest.raises(ScheduledTransactionError, match="Destination|account"):
        service.create_schedule(
            book_id=book,
            kind="TRANSFER",
            source_account_id=source.id,
            counter_account_id=destination.id,
            amount_minor=1_000,
            frequency="MONTHLY",
            interval=1,
            start_date="2026-02-01",
        )

    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM scheduled_transactions"
    ).fetchone()[0] == 0
    ledger_env.db.integrity_check()
