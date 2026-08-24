from decimal import Decimal

import pytest

from core.errors import FxRateError, FxRateMissingError
from core.fx_service import FxService


def test_fx_rates_are_exact_historical_and_book_scoped(ledger_env) -> None:
    fx = FxService(ledger_env.db)
    first = fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="usd",
        rate_date="2026-01-10",
        rate="0,90",
    )
    fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="USD",
        rate_date="2026-01-20",
        rate=Decimal("0.95"),
    )
    assert first.rate == Decimal("0.9")
    assert fx.rate_for(ledger_env.book_id, "USD", "2026-01-15") == Decimal("0.9")
    assert fx.rate_for(ledger_env.book_id, "USD", "2026-01-25") == Decimal("0.95")
    assert fx.rate_for(ledger_env.book_id, "EUR", "2026-01-01") == Decimal(1)
    with pytest.raises(FxRateMissingError):
        fx.rate_for(ledger_env.other_book_id, "USD", "2026-01-25")


def test_fx_conversion_respects_minor_units_and_rounding(ledger_env) -> None:
    fx = FxService(ledger_env.db)
    fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="USD",
        rate_date="2026-01-01",
        rate="0.90",
    )
    fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="JPY",
        rate_date="2026-01-01",
        rate="0.006",
    )
    assert fx.convert_minor(
        book_id=ledger_env.book_id,
        amount_minor=10_00,
        currency_code="USD",
        rate_date="2026-01-02",
    ) == 9_00
    assert fx.convert_minor(
        book_id=ledger_env.book_id,
        amount_minor=100,
        currency_code="JPY",
        rate_date="2026-01-02",
    ) == 60
    assert fx.convert_minor(
        book_id=ledger_env.book_id,
        amount_minor=1,
        currency_code="EUR",
        rate_date="2026-01-02",
    ) == 1


def test_fx_rate_upsert_and_validation(ledger_env) -> None:
    fx = FxService(ledger_env.db)
    fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="USD",
        rate_date="2026-01-01",
        rate="0.9",
    )
    fx.set_rate(
        book_id=ledger_env.book_id,
        currency_code="USD",
        rate_date="2026-01-01",
        rate="0.91",
    )
    rates = fx.list_rates(ledger_env.book_id)
    assert len(rates) == 1
    assert rates[0].rate == Decimal("0.91")

    invalid = ("0", "-1", "nan", "inf", "", "abc")
    for value in invalid:
        with pytest.raises(FxRateError):
            fx.set_rate(
                book_id=ledger_env.book_id,
                currency_code="USD",
                rate_date="2026-01-02",
                rate=value,
            )
    with pytest.raises(FxRateError):
        fx.set_rate(
            book_id=ledger_env.book_id,
            currency_code="USD",
            rate_date="2026-01-02",
            rate=0.91,  # type: ignore[arg-type]
        )
    with pytest.raises(FxRateError):
        fx.set_rate(
            book_id=ledger_env.book_id,
            currency_code="EUR",
            rate_date="2026-01-02",
            rate="1",
        )
    with pytest.raises(FxRateError):
        fx.set_rate(
            book_id=ledger_env.book_id,
            currency_code="USD",
            rate_date="not-a-date",
            rate="1",
        )
