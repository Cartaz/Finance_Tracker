from decimal import Decimal

import pytest

from core.errors import CurrencyPrecisionError, MoneyParseError
from core.money import CurrencySpec, decimal_to_minor, minor_to_decimal, parse_money

EUR = CurrencySpec("EUR", 2)
JPY = CurrencySpec("JPY", 0)
KWD = CurrencySpec("KWD", 3)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12", 1200),
        ("12,3", 1230),
        ("12.30", 1230),
        ("12,30", 1230),
        ("12,,30", 1230),
        ("12...30", 1230),
        ("12,3000", 1230),
        ("1.234,56", 123456),
        ("1,234.56", 123456),
        ("-42,73", -4273),
        ("+42.73", 4273),
    ],
)
def test_parse_eur(raw: str, expected: int) -> None:
    assert parse_money(raw, EUR) == expected


@pytest.mark.parametrize("raw", ["12,345", "12.345", "12,3,0", "1,,234,56", "abc12,30", "", ",12"])
def test_rejects_ambiguous_or_overprecise_eur(raw: str) -> None:
    with pytest.raises((MoneyParseError, CurrencyPrecisionError)):
        parse_money(raw, EUR)


def test_currency_specific_precision() -> None:
    assert parse_money("1234", JPY) == 1234
    assert parse_money("1234,0", JPY) == 1234
    with pytest.raises(CurrencyPrecisionError):
        parse_money("1234,5", JPY)
    assert parse_money("12,345", KWD) == 12345


def test_decimal_conversion_is_explicit() -> None:
    assert decimal_to_minor(Decimal("12.345"), EUR) == 1235
    assert minor_to_decimal(1235, EUR) == Decimal("12.35")
    with pytest.raises(TypeError):
        decimal_to_minor(12.345, EUR)  # type: ignore[arg-type]
