import re
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
        ("1.500.000", 150000000),
        ("1,500,000", 150000000),
        ("1.500,00", 150000),
        # Not a possible thousands group: an ordinary decimal.
        ("0,500", 50),
        ("1234,500", 123450),
        ("12,3000", 1230),
        ("1.234,56", 123456),
        ("1,234.56", 123456),
        ("-42,73", -4273),
        ("+42.73", 4273),
    ],
)
def test_parse_eur(raw: str, expected: int) -> None:
    assert parse_money(raw, EUR) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "12,345",
        "12.345",
        "12,3,0",
        "1,,234,56",
        "abc12,30",
        "",
        ",12",
        "12,,30",
        "12...30",
        # Thousands group or decimals? Refused instead of read as 1,50 EUR.
        "1.500",
        "1,500",
        "10.000",
        "-1.500",
        "1.50.0",
        "0.500.000",
    ],
)
def test_rejects_ambiguous_or_overprecise_eur(raw: str) -> None:
    with pytest.raises((MoneyParseError, CurrencyPrecisionError)):
        parse_money(raw, EUR)


def test_currency_specific_precision() -> None:
    assert parse_money("1234", JPY) == 1234
    assert parse_money("1234,0", JPY) == 1234
    with pytest.raises(CurrencyPrecisionError):
        parse_money("1234,5", JPY)
    assert parse_money("12,345", KWD) == 12345
    assert parse_money("1.000.000", JPY) == 1000000
    with pytest.raises(MoneyParseError, match="ambiguo"):
        parse_money("1.000", JPY)


@pytest.mark.parametrize(
    ("raw", "currency", "expected"),
    [
        ("1.500", EUR, "per le migliaia scrivi 1500 (o 1.500,00), per i decimali scrivi 1,50"),
        ("+1,500", EUR, "per le migliaia scrivi +1500 (o +1.500,00), per i decimali scrivi +1,50"),
        ("-2.000", JPY, "per le migliaia scrivi -2000 (o -2.000), per i decimali scrivi -2"),
    ],
)
def test_ambiguous_amount_message_offers_both_readings(raw, currency, expected) -> None:
    with pytest.raises(MoneyParseError, match=re.escape(expected)):
        parse_money(raw, currency)


def test_ambiguous_amount_without_a_valid_decimal_reading_offers_thousands_only() -> None:
    with pytest.raises(MoneyParseError) as caught:
        parse_money("1.234", EUR)
    assert "per le migliaia scrivi 1234 (o 1.234,00)" in str(caught.value)
    assert "decimali" not in str(caught.value)


def test_decimal_conversion_is_explicit() -> None:
    assert decimal_to_minor(Decimal("12.345"), EUR) == 1235
    assert minor_to_decimal(1235, EUR) == Decimal("12.35")
    with pytest.raises(TypeError):
        decimal_to_minor(12.345, EUR)  # type: ignore[arg-type]


def test_fx_style_decimals_do_not_accept_thousands_grouping() -> None:
    from core.money import normalize_decimal_text

    assert normalize_decimal_text("1.085") == "1.085"
    with pytest.raises(MoneyParseError):
        normalize_decimal_text("1.450.000")
    assert normalize_decimal_text("1.450.000", allow_grouping=True) == "1450000"
