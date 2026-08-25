from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from core.errors import CurrencyPrecisionError, MoneyParseError

_SIGN_RE = re.compile(r"^[+-]?")
_DIGITS_RE = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class CurrencySpec:
    code: str
    minor_unit_digits: int

    def __post_init__(self) -> None:
        if len(self.code) != 3 or not self.code.isalpha():
            raise ValueError("currency code must contain exactly three letters")
        if self.minor_unit_digits < 0:
            raise ValueError("minor_unit_digits must be non-negative")
        object.__setattr__(self, "code", self.code.upper())


def _collapse_adjacent_identical_separators(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = text.replace(",,", ",").replace("..", ".")
    return text


def _split_sign(text: str) -> tuple[str, str]:
    if text.startswith(("+", "-")):
        return text[0], text[1:]
    return "", text


def _validate_grouped_integer(text: str, separator: str) -> str:
    groups = text.split(separator)
    if not groups or not (1 <= len(groups[0]) <= 3) or not all(
        _DIGITS_RE.fullmatch(g or "") for g in groups
    ):
        raise MoneyParseError("invalid thousands grouping")
    if any(len(group) != 3 for group in groups[1:]):
        raise MoneyParseError("invalid thousands grouping")
    return "".join(groups)


def normalize_decimal_text(raw: str) -> str:
    if not isinstance(raw, str):
        raise MoneyParseError("money input must be text")

    text = raw.strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        raise MoneyParseError("empty monetary amount")

    sign, body = _split_sign(text)
    if not body or any(char not in "0123456789,." for char in body):
        raise MoneyParseError("monetary amount contains unsupported characters")

    body = _collapse_adjacent_identical_separators(body)
    comma_count = body.count(",")
    dot_count = body.count(".")

    if comma_count and dot_count:
        decimal_sep = "," if body.rfind(",") > body.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        integer_part, fractional_part = body.rsplit(decimal_sep, 1)
        if not fractional_part or not _DIGITS_RE.fullmatch(fractional_part):
            raise MoneyParseError("invalid decimal fraction")
        if decimal_sep in integer_part:
            raise MoneyParseError("ambiguous monetary separators")
        integer_digits = _validate_grouped_integer(integer_part, thousands_sep)
        canonical = f"{integer_digits}.{fractional_part}"
    elif comma_count or dot_count:
        separator = "," if comma_count else "."
        if body.count(separator) != 1:
            raise MoneyParseError("ambiguous monetary separators")
        integer_part, fractional_part = body.split(separator, 1)
        if not integer_part or not fractional_part:
            raise MoneyParseError("invalid decimal amount")
        if not _DIGITS_RE.fullmatch(integer_part) or not _DIGITS_RE.fullmatch(
            fractional_part
        ):
            raise MoneyParseError("invalid decimal amount")
        canonical = f"{integer_part}.{fractional_part}"
    else:
        if not _DIGITS_RE.fullmatch(body):
            raise MoneyParseError("invalid monetary amount")
        canonical = body

    return sign + canonical


def parse_money(raw: str, currency: CurrencySpec) -> int:
    """Parse signed monetary text for sources where the sign is part of the data."""
    canonical = normalize_decimal_text(raw)
    unsigned = canonical.lstrip("+-")
    fractional = unsigned.partition(".")[2]

    if len(fractional) > currency.minor_unit_digits:
        excess = fractional[currency.minor_unit_digits :]
        if any(char != "0" for char in excess):
            raise CurrencyPrecisionError(
                f"{currency.code} supports at most {currency.minor_unit_digits} decimal places"
            )
        fractional = fractional[: currency.minor_unit_digits]
        integer = unsigned.partition(".")[0]
        canonical = (
            "-"
            if canonical.startswith("-")
            else "+"
            if canonical.startswith("+")
            else ""
        ) + integer
        if fractional:
            canonical += "." + fractional

    try:
        value = Decimal(canonical)
    except InvalidOperation as exc:
        raise MoneyParseError("invalid monetary amount") from exc

    scale = Decimal(10) ** currency.minor_unit_digits
    minor = value * scale
    if minor != minor.to_integral_value():
        raise CurrencyPrecisionError(
            f"{currency.code} amount cannot be represented exactly in minor units"
        )
    return int(minor)


def parse_money_magnitude(raw: str, currency: CurrencySpec) -> int:
    """Parse a user-entered monetary magnitude.

    Transaction kind owns economic direction. A magnitude therefore cannot carry
    an explicit plus/minus sign and must be strictly greater than zero.
    """
    if not isinstance(raw, str):
        raise MoneyParseError("money input must be text")
    stripped = raw.strip()
    if stripped.startswith(("+", "-")):
        raise MoneyParseError(
            "monetary magnitude must not include a sign; transaction type determines direction"
        )
    minor = parse_money(raw, currency)
    if minor <= 0:
        raise MoneyParseError("monetary magnitude must be greater than zero")
    return minor


def decimal_to_minor(
    value: Decimal,
    currency: CurrencySpec,
    *,
    rounding: str = ROUND_HALF_UP,
) -> int:
    if isinstance(value, float) or not isinstance(value, Decimal):
        raise TypeError("value must be Decimal; float is prohibited for financial math")
    quantum = Decimal(1).scaleb(-currency.minor_unit_digits)
    quantized = value.quantize(quantum, rounding=rounding)
    scale = Decimal(10) ** currency.minor_unit_digits
    return int(quantized * scale)


def minor_to_decimal(amount_minor: int, currency: CurrencySpec) -> Decimal:
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise TypeError("amount_minor must be int")
    return Decimal(amount_minor).scaleb(-currency.minor_unit_digits)
