from __future__ import annotations

from dataclasses import dataclass

from core.database import Database
from core.errors import ValidationError


@dataclass(frozen=True, slots=True)
class Book:
    id: int
    name: str
    base_currency_code: str


class BookService:
    """Owns the local user's book bootstrap and book lookup."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def current_book(self) -> Book | None:
        row = self._database.connection.execute(
            """
            SELECT b.id, b.name, b.base_currency_code
            FROM books b
            JOIN book_members bm ON bm.book_id = b.id
            JOIN users u ON u.id = bm.user_id
            WHERE b.archived = 0 AND u.archived = 0
            ORDER BY b.id LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return Book(int(row["id"]), str(row["name"]), str(row["base_currency_code"]))

    def create_personal_book(self, *, user_name: str, book_name: str, currency_code: str) -> Book:
        if self.current_book() is not None:
            raise ValidationError("a personal book already exists")
        clean_user = user_name.strip()
        clean_book = book_name.strip()
        if not clean_user or not clean_book:
            raise ValidationError("user and book names cannot be empty")
        currency = self._database.currency(currency_code)
        with self._database.transaction() as conn:
            user_id = int(
                conn.execute(
                    "INSERT INTO users(name, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))",
                    (clean_user,),
                ).lastrowid
            )
            book_id = int(
                conn.execute(
                    """
                    INSERT INTO books(name, base_currency_code, created_at, updated_at)
                    VALUES (?, ?, datetime('now'), datetime('now'))
                    """,
                    (clean_book, currency.code),
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO book_members(book_id, user_id, role) VALUES (?, ?, 'OWNER')",
                (book_id, user_id),
            )
        return Book(book_id, clean_book, currency.code)
