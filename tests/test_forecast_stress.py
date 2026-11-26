from __future__ import annotations

from core.forecast_service import ForecastService
from core.fx_service import FxService
from core.payee_service import PayeeService
from core.scheduled_transaction_service import ScheduledTransactionService


def test_many_occurrence_forecast_is_deterministic_and_read_only(ledger_env) -> None:
    payees = PayeeService(ledger_env.db)
    scheduled = ScheduledTransactionService(
        ledger_env.db,
        ledger_env.accounts,
        ledger_env.ledger,
        payees,
    )
    forecast = ForecastService(scheduled, FxService(ledger_env.db))
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )

    schedule_ids: list[int] = []
    for index in range(20):
        category = ledger_env.accounts.create_account(
            book_id=ledger_env.book_id,
            account_type="EXPENSE",
            name=f"Stress {index:02d}",
        )
        item = scheduled.create_schedule(
            book_id=ledger_env.book_id,
            kind="EXPENSE",
            source_account_id=bank.id,
            counter_account_id=category.id,
            amount_minor=index + 1,
            frequency="DAILY",
            interval=1,
            start_date="2026-01-02",
        )
        schedule_ids.append(item.id)

    before_due = {
        schedule_id: scheduled.get_schedule(ledger_env.book_id, schedule_id).next_due_date
        for schedule_id in schedule_ids
    }
    before_tx = ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0]
    before_entries = ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM entries"
    ).fetchone()[0]

    first = forecast.cash_flow_forecast(
        book_id=ledger_env.book_id,
        start_date="2026-01-02",
        end_date="2026-06-30",
        granularity="MONTH",
    )
    second = forecast.cash_flow_forecast(
        book_id=ledger_env.book_id,
        start_date="2026-01-02",
        end_date="2026-06-30",
        granularity="MONTH",
    )

    assert first == second
    assert first["complete"] is True
    assert first["occurrenceCount"] == 20 * 180
    assert first["transferCount"] == 0
    assert len(first["buckets"]) == 6
    expected_daily_outflow = sum(range(1, 21))
    assert first["totalOutflowMinor"] == expected_daily_outflow * 180
    assert first["totalNetMinor"] == -(expected_daily_outflow * 180)

    after_due = {
        schedule_id: scheduled.get_schedule(ledger_env.book_id, schedule_id).next_due_date
        for schedule_id in schedule_ids
    }
    assert after_due == before_due
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == before_tx
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM entries"
    ).fetchone()[0] == before_entries
