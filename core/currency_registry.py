from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from core.errors import UnsupportedCurrencyError
from core.money import CurrencySpec

DEFAULT_CURRENCIES: tuple[tuple[str, str, str, int], ...] = (
    ("EUR", "Euro", "€", 2),
    ("USD", "US Dollar", "$", 2),
    ("GBP", "Pound Sterling", "£", 2),
    ("CHF", "Swiss Franc", "CHF", 2),
    ("JPY", "Japanese Yen", "¥", 0),
    ("KWD", "Kuwaiti Dinar", "KWD", 3),
    ("BHD", "Bahraini Dinar", "BHD", 3),
    ("OMR", "Omani Rial", "OMR", 3),
    ("KRW", "South Korean Won", "₩", 0),
)


@dataclass(frozen=True, slots=True)
class CurrencyRecord:
    code: str
    minor_unit_digits: int


class CurrencyRegistry:
    """Own currency lookup and precision metadata independently of persistence wiring."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, code: str) -> CurrencySpec:
        if not isinstance(code, str):
            raise UnsupportedCurrencyError("currency code must be text")
        normalized = code.strip().upper()
        row = self._connection.execute(
            "SELECT code, minor_unit_digits FROM currencies WHERE code=? AND active=1",
            (normalized,),
        ).fetchone()
        if row is None:
            raise UnsupportedCurrencyError(f"unsupported currency: {code}")
        return CurrencySpec(str(row["code"]), int(row["minor_unit_digits"]))

    def list_active(self) -> list[CurrencyRecord]:
        rows = self._connection.execute(
            "SELECT code, minor_unit_digits FROM currencies WHERE active=1 ORDER BY code"
        ).fetchall()
        return [
            CurrencyRecord(str(row["code"]), int(row["minor_unit_digits"]))
            for row in rows
        ]
