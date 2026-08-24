from __future__ import annotations

import pytest

from core.errors import ScheduledTransactionError
from core.forecast_service import ForecastService
from core.fx_service import FxService
from core.payee_service import PayeeService
from core.scheduled_transaction_service import ScheduledTransactionService


def _services(env):
    payees = PayeeService(env.db)
    scheduled = ScheduledTransactionService(
        env.db,
        env.accounts,
        env.ledger,
        payees,
    )
    return scheduled, ForecastService(scheduled, FxService(env.db))


def test_forecast_fails_closed_when_active_schedule_becomes_unmaterializable(
    ledger_env,
) -> None:
    scheduled, forecast = _services(ledger_env)
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    category = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Utilities",
    )
    scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=category.id,
        amount_minor=5_000,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-02-01",
    )
    ledger_env.accounts.set_archived(ledger_env.book_id, category.id, True)

    with pytest.raises(ScheduledTransactionError, match="not eligible"):
        forecast.cash_flow_forecast(
            book_id=ledger_env.book_id,
            start_date="2026-02-01",
            end_date="2026-03-31",
        )


def test_projection_bounds_work_needed_to_skip_old_occurrences(ledger_env) -> None:
    scheduled, _ = _services(ledger_env)
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Long-lived",
        currency_code="EUR",
        tracking_start_date="1990-01-01",
    )
    category = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Daily",
    )
    scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=category.id,
        amount_minor=1,
        frequency="DAILY",
        interval=1,
        start_date="1990-01-01",
    )

    with pytest.raises(ScheduledTransactionError, match="projection advance limit"):
        scheduled.project_occurrences(
            book_id=ledger_env.book_id,
            start_date="2026-01-01",
            end_date="2026-01-01",
        )
