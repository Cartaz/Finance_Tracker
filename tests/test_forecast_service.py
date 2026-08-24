from __future__ import annotations

import pytest

from core.errors import ForecastError, ScheduledTransactionError
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
    fx = FxService(env.db)
    return scheduled, fx, ForecastService(scheduled, fx)


def _account(env, account_type: str, name: str, currency: str | None = None):
    return env.accounts.create_account(
        book_id=env.book_id,
        account_type=account_type,
        name=name,
        currency_code=currency,
        tracking_start_date="2026-01-01" if currency else None,
        tracking_start_time="00:00:00" if currency else None,
    )


def test_forecast_uses_canonical_recurrence_and_is_read_only(ledger_env) -> None:
    scheduled, _, forecast = _services(ledger_env)
    bank = _account(ledger_env, "ASSET", "Bank", "EUR")
    savings = _account(ledger_env, "ASSET", "Savings", "EUR")
    rent = _account(ledger_env, "EXPENSE", "Rent")
    salary = _account(ledger_env, "INCOME", "Salary")

    rent_schedule = scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=rent.id,
        amount_minor=100_00,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-01-31",
        description="Rent",
    )
    scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="INCOME",
        source_account_id=bank.id,
        counter_account_id=salary.id,
        amount_minor=250_00,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-02-15",
        description="Salary",
    )
    scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="TRANSFER",
        source_account_id=bank.id,
        counter_account_id=savings.id,
        amount_minor=50_00,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-02-20",
        description="Savings transfer",
    )

    before_tx = ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0]
    before_entries = ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM entries"
    ).fetchone()[0]
    before_due = scheduled.get_schedule(
        ledger_env.book_id, rent_schedule.id
    ).next_due_date

    result = forecast.cash_flow_forecast(
        book_id=ledger_env.book_id,
        start_date="2026-02-01",
        end_date="2026-03-31",
    )

    assert result["complete"] is True
    assert result["baseCurrency"] == "EUR"
    assert result["scheduledOnly"] is True
    assert result["fxPolicy"] == "LATEST_KNOWN_ON_OR_BEFORE_DUE_DATE"
    assert result["totalInflowMinor"] == 500_00
    assert result["totalOutflowMinor"] == 200_00
    assert result["totalNetMinor"] == 300_00
    assert result["occurrenceCount"] == 6
    assert result["transferCount"] == 2
    assert [item["period"] for item in result["buckets"]] == [
        "2026-02",
        "2026-03",
    ]
    february = result["buckets"][0]
    assert february["inflowMinor"] == 250_00
    assert february["outflowMinor"] == 100_00
    assert february["netMinor"] == 150_00
    assert february["transferCount"] == 1
    rent_dates = [
        item["dueDate"]
        for item in result["occurrences"]
        if item["scheduleId"] == rent_schedule.id
    ]
    assert rent_dates == ["2026-02-28", "2026-03-31"]

    assert scheduled.get_schedule(
        ledger_env.book_id, rent_schedule.id
    ).next_due_date == before_due
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == before_tx
    assert ledger_env.db.connection.execute(
        "SELECT COUNT(*) FROM entries"
    ).fetchone()[0] == before_entries


def test_forecast_uses_latest_known_fx_and_fails_closed_when_missing(ledger_env) -> None:
    scheduled, fx, forecast = _services(ledger_env)
    usd = _account(ledger_env, "ASSET", "USD", "USD")
    travel = _account(ledger_env, "EXPENSE", "Travel")
    scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=usd.id,
        counter_account_id=travel.id,
        amount_minor=10_00,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-04-10",
    )

    missing = forecast.cash_flow_forecast(
        book_id=ledger_env.book_id,
        start_date="2026-04-01",
        end_date="2026-04-30",
    )
    assert missing["complete"] is False
    assert missing["totalInflowMinor"] is None
    assert missing["totalOutflowMinor"] is None
    assert missing["totalNetMinor"] is None
    assert missing["missingFx"] == [{"currency": "USD", "date": "2026-04-10"}]
    assert missing["buckets"][0]["outflowMinor"] is None
    assert missing["occurrences"][0]["baseAmountMinor"] is None

    fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="USD",
        rate_date="2026-03-31",
        rate="0.90",
    )
    complete = forecast.cash_flow_forecast(
        book_id=ledger_env.book_id,
        start_date="2026-04-01",
        end_date="2026-04-30",
    )
    assert complete["complete"] is True
    assert complete["totalOutflowMinor"] == 900
    assert complete["totalNetMinor"] == -900
    assert complete["occurrences"][0]["baseAmountMinor"] == 900


def test_forecast_ignores_inactive_schedules_and_supports_granularity(ledger_env) -> None:
    scheduled, _, forecast = _services(ledger_env)
    bank = _account(ledger_env, "ASSET", "Bank", "EUR")
    food = _account(ledger_env, "EXPENSE", "Food")
    item = scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=food.id,
        amount_minor=500,
        frequency="WEEKLY",
        interval=1,
        start_date="2026-05-01",
    )
    scheduled.set_active(ledger_env.book_id, item.id, False)

    result = forecast.cash_flow_forecast(
        book_id=ledger_env.book_id,
        start_date="2026-05-01",
        end_date="2026-05-31",
        granularity="DAY",
    )
    assert result["occurrences"] == []
    assert result["buckets"] == []
    assert result["totalNetMinor"] == 0


@pytest.mark.parametrize(
    ("start", "end", "granularity"),
    [
        ("bad", "2026-01-01", "MONTH"),
        ("2026-02-01", "2026-01-01", "MONTH"),
        ("2026-01-01", "2037-01-01", "MONTH"),
        ("2026-01-01", "2026-02-01", "WEEK"),
    ],
)
def test_forecast_rejects_invalid_queries(
    ledger_env, start: str, end: str, granularity: str
) -> None:
    _, _, forecast = _services(ledger_env)
    with pytest.raises(ForecastError):
        forecast.cash_flow_forecast(
            book_id=ledger_env.book_id,
            start_date=start,
            end_date=end,
            granularity=granularity,
        )


def test_projection_has_bounded_occurrence_limit(ledger_env) -> None:
    scheduled, _, _ = _services(ledger_env)
    bank = _account(ledger_env, "ASSET", "Bank", "EUR")
    food = _account(ledger_env, "EXPENSE", "Food")
    scheduled.create_schedule(
        book_id=ledger_env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=food.id,
        amount_minor=1,
        frequency="DAILY",
        interval=1,
        start_date="2026-01-02",
    )
    with pytest.raises(ScheduledTransactionError, match="projected occurrence limit"):
        scheduled.project_occurrences(
            book_id=ledger_env.book_id,
            start_date="2026-01-02",
            end_date="2026-01-10",
            max_occurrences=3,
        )
