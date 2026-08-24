from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from core.database import Database
from core.errors import FxRateError, FxRateMissingError, MoneyParseError
from core.money import decimal_to_minor, minor_to_decimal, normalize_decimal_text


@dataclass(frozen=True, slots=True)
class FxRate:
    book_id: int
    currency_code: str
    rate_date: str
    rate: Decimal


class FxService:
    """Owns exact book-scoped FX rates used by reporting.

    A stored rate means: one major unit of ``currency_code`` equals ``rate``
    major units of the book's base currency. The base currency itself is
    always an implicit rate of exactly one.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def base_currency(self, book_id: int) -> str:
        self._require_positive_id(book_id, "book_id")
        row = self._database.connection.execute(
            "SELECT base_currency_code FROM books WHERE id = ? AND archived = 0",
            (book_id,),
        ).fetchone()
        if row is None:
            raise FxRateError(f"active book {book_id} does not exist")
        return str(row["base_currency_code"])

    def set_rate(
        self,
        *,
        book_id: int,
        currency_code: str,
        rate_date: str,
        rate: str | Decimal,
    ) -> FxRate:
        base_currency = self.base_currency(book_id)
        code = self._normalize_currency(currency_code)
        if code == base_currency:
            raise FxRateError("the book base currency has an implicit FX rate of 1")
        normalized_date = self._normalize_date(rate_date)
        parsed_rate = self._parse_rate(rate)
        rate_text = format(parsed_rate, "f")
        with self._database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO fx_rates(
                    book_id, currency_code, rate_date, rate_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(book_id, currency_code, rate_date) DO UPDATE SET
                    rate_text = excluded.rate_text,
                    updated_at = datetime('now')
                """,
                (book_id, code, normalized_date, rate_text),
            )
        return FxRate(book_id, code, normalized_date, parsed_rate)

    def list_rates(self, book_id: int, *, limit: int = 100) -> list[FxRate]:
        self.base_currency(book_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise FxRateError("FX rate limit must be between 1 and 500")
        rows = self._database.connection.execute(
            """
            SELECT book_id, currency_code, rate_date, rate_text
            FROM fx_rates
            WHERE book_id = ?
            ORDER BY rate_date DESC, currency_code
            LIMIT ?
            """,
            (book_id, limit),
        ).fetchall()
        return [self._row_to_rate(row) for row in rows]

    def rate_for(self, book_id: int, currency_code: str, rate_date: str) -> Decimal:
        base_currency = self.base_currency(book_id)
        code = self._normalize_currency(currency_code)
        normalized_date = self._normalize_date(rate_date)
        if code == base_currency:
            return Decimal(1)
        row = self._database.connection.execute(
            """
            SELECT book_id, currency_code, rate_date, rate_text
            FROM fx_rates
            WHERE book_id = ? AND currency_code = ? AND rate_date <= ?
            ORDER BY rate_date DESC
            LIMIT 1
            """,
            (book_id, code, normalized_date),
        ).fetchone()
        if row is None:
            raise FxRateMissingError(code, normalized_date)
        return self._row_to_rate(row).rate

    def convert_minor(
        self,
        *,
        book_id: int,
        amount_minor: int,
        currency_code: str,
        rate_date: str,
    ) -> int:
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
            raise FxRateError("amount_minor must be an integer")
        code = self._normalize_currency(currency_code)
        source = self._database.currency(code)
        base = self._database.currency(self.base_currency(book_id))
        rate = self.rate_for(book_id, code, rate_date)
        source_major = minor_to_decimal(amount_minor, source)
        return decimal_to_minor(source_major * rate, base)

    def _normalize_currency(self, currency_code: str) -> str:
        if not isinstance(currency_code, str) or not currency_code.strip():
            raise FxRateError("currency_code is required")
        code = currency_code.strip().upper()
        self._database.currency(code)
        return code

    @staticmethod
    def _normalize_date(raw: str) -> str:
        if not isinstance(raw, str):
            raise FxRateError("rate_date must be YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise FxRateError("rate_date must be YYYY-MM-DD") from exc
        return parsed.isoformat()

    @staticmethod
    def _parse_rate(raw: str | Decimal) -> Decimal:
        if isinstance(raw, (float, bool)):
            raise FxRateError("FX rates must not use float")
        try:
            if isinstance(raw, Decimal):
                value = raw
            elif isinstance(raw, str):
                value = Decimal(normalize_decimal_text(raw))
            else:
                raise FxRateError("FX rate must be text or Decimal")
        except (InvalidOperation, ValueError, MoneyParseError) as exc:
            raise FxRateError("invalid FX rate") from exc
        if not value.is_finite() or value <= 0:
            raise FxRateError("FX rate must be finite and greater than zero")
        return value.normalize()

    @staticmethod
    def _require_positive_id(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FxRateError(f"{name} must be a positive integer")

    @staticmethod
    def _row_to_rate(row) -> FxRate:
        try:
            value = Decimal(str(row["rate_text"]))
        except InvalidOperation as exc:
            raise FxRateError("stored FX rate is invalid") from exc
        if not value.is_finite() or value <= 0:
            raise FxRateError("stored FX rate is invalid")
        return FxRate(
            book_id=int(row["book_id"]),
            currency_code=str(row["currency_code"]),
            rate_date=str(row["rate_date"]),
            rate=value,
        )
