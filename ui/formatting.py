"""Presentation formatting for exact financial integers.

QML expressions run on JavaScript numbers, which lose precision above 2^53.
Financial values therefore cross the QML boundary as text and are formatted
here from exact Python integers; QML never parses or computes money.
"""

from __future__ import annotations

_MISSING_FX = "FX mancante"
_MINUS = "−"


def _exact_integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("financial value must be integer text")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        sign = 1
        if text[0] in "+-":
            sign = -1 if text[0] == "-" else 1
            text = text[1:]
        if not text.isascii() or not text.isdigit():
            raise ValueError("financial value must be integer text")
        return sign * int(text)
    raise ValueError("financial value must be integer text")


def _group_thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_money(minor: object, currency_code: str, minor_unit_digits: int) -> str:
    """Format minor units as Italian-grouped text, e.g. ``−1.234,56 EUR``."""
    amount = _exact_integer(minor)
    if amount is None:
        return _MISSING_FX
    scale = 10**minor_unit_digits
    whole, fraction = divmod(abs(amount), scale)
    fraction_text = f",{fraction:0{minor_unit_digits}d}" if minor_unit_digits else ""
    sign = _MINUS if amount < 0 else ""
    return f"{sign}{_group_thousands(whole)}{fraction_text} {currency_code}".rstrip()


def format_percent_bps(bps: object) -> str:
    """Format basis points as a two-decimal percentage, e.g. ``5,25%``."""
    value = _exact_integer(bps)
    if value is None:
        return "—"
    whole, fraction = divmod(abs(value), 100)
    sign = _MINUS if value < 0 else ""
    return f"{sign}{_group_thousands(whole)},{fraction:02d}%"
