from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, time

from core.database import Database
from core.errors import AccountHierarchyError, AccountNotFoundError, ValidationError

_ACCOUNT_TYPES = {"ASSET", "LIABILITY", "INCOME", "EXPENSE", "EQUITY"}
_BALANCE_TYPES = {"ASSET", "LIABILITY"}


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    book_id: int
    parent_id: int | None
    type: str
    name: str
    currency_code: str | None
    tracking_start_date: str | None
    tracking_start_time: str | None
    placeholder: bool
    archived: bool


class AccountService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_account(
        self,
        *,
        book_id: int,
        account_type: str,
        name: str,
        parent_id: int | None = None,
        currency_code: str | None = None,
        tracking_start_date: str | None = None,
        tracking_start_time: str | None = None,
        placeholder: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> Account:
        account_type = account_type.upper()
        clean_name = name.strip()
        if account_type not in _ACCOUNT_TYPES:
            raise ValidationError(f"unsupported account type: {account_type}")
        if not clean_name:
            raise ValidationError("account name cannot be empty")
        self._ensure_book_exists(book_id)

        if account_type in _BALANCE_TYPES:
            if currency_code is None or tracking_start_date is None:
                raise ValidationError(
                    "asset and liability accounts require currency and tracking start date"
                )
            currency_code = self._database.currency(currency_code).code
            self._validate_date(tracking_start_date)
            if tracking_start_time is not None:
                self._validate_time(tracking_start_time)
        elif any(
            value is not None
            for value in (currency_code, tracking_start_date, tracking_start_time)
        ):
            raise ValidationError(
                "income, expense and equity accounts cannot have currency or tracking boundary"
            )

        if parent_id is not None:
            parent = self.get_account(book_id, parent_id)
            if parent.type != account_type:
                raise AccountHierarchyError("parent and child account types must match")

        if connection is None:
            with self._database.transaction() as conn:
                account_id = self._insert_account(
                    conn,
                    book_id=book_id,
                    parent_id=parent_id,
                    account_type=account_type,
                    name=clean_name,
                    currency_code=currency_code,
                    tracking_start_date=tracking_start_date,
                    tracking_start_time=tracking_start_time,
                    placeholder=placeholder,
                )
        else:
            account_id = self._insert_account(
                connection,
                book_id=book_id,
                parent_id=parent_id,
                account_type=account_type,
                name=clean_name,
                currency_code=currency_code,
                tracking_start_date=tracking_start_date,
                tracking_start_time=tracking_start_time,
                placeholder=placeholder,
            )
        return self.get_account(book_id, account_id)

    def get_account(self, book_id: int, account_id: int) -> Account:
        row = self._database.connection.execute(
            """
            SELECT id, book_id, parent_id, type, name, currency_code,
                   tracking_start_date, tracking_start_time, placeholder, archived
            FROM accounts
            WHERE id = ? AND book_id = ?
            """,
            (account_id, book_id),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError(
                f"account {account_id} does not exist in book {book_id}"
            )
        return self._row_to_account(row)

    def list_accounts(self, book_id: int, *, include_archived: bool = False) -> list[Account]:
        sql = """
            SELECT id, book_id, parent_id, type, name, currency_code,
                   tracking_start_date, tracking_start_time, placeholder, archived
            FROM accounts
            WHERE book_id = ?
        """
        params: list[object] = [book_id]
        if not include_archived:
            sql += " AND archived = 0"
        sql += " ORDER BY type, name COLLATE NOCASE, id"
        rows = self._database.connection.execute(sql, params).fetchall()
        return [self._row_to_account(row) for row in rows]

    def rename_account(self, book_id: int, account_id: int, name: str) -> Account:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError("account name cannot be empty")
        self.get_account(book_id, account_id)
        with self._database.transaction() as conn:
            conn.execute(
                "UPDATE accounts SET name = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (clean_name, account_id, book_id),
            )
        return self.get_account(book_id, account_id)

    def move_account(
        self,
        book_id: int,
        account_id: int,
        new_parent_id: int | None,
    ) -> Account:
        account = self.get_account(book_id, account_id)
        if new_parent_id == account_id:
            raise AccountHierarchyError("an account cannot be its own parent")
        if new_parent_id is not None:
            parent = self.get_account(book_id, new_parent_id)
            if parent.type != account.type:
                raise AccountHierarchyError("parent and child account types must match")
            cursor = parent
            while cursor.parent_id is not None:
                if cursor.parent_id == account_id:
                    raise AccountHierarchyError("account move would create a cycle")
                cursor = self.get_account(book_id, cursor.parent_id)

        with self._database.transaction() as conn:
            conn.execute(
                "UPDATE accounts SET parent_id = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (new_parent_id, account_id, book_id),
            )
        return self.get_account(book_id, account_id)

    def set_archived(self, book_id: int, account_id: int, archived: bool) -> Account:
        self.get_account(book_id, account_id)
        with self._database.transaction() as conn:
            conn.execute(
                "UPDATE accounts SET archived = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (int(archived), account_id, book_id),
            )
        return self.get_account(book_id, account_id)

    def native_balance(self, book_id: int, account_id: int) -> int:
        account = self.get_account(book_id, account_id)
        if account.type not in _BALANCE_TYPES:
            raise ValidationError("native balances exist only for asset and liability accounts")
        value = self._database.connection.execute(
            "SELECT COALESCE(SUM(quantity_minor), 0) FROM entries WHERE account_id = ? AND book_id = ?",
            (account_id, book_id),
        ).fetchone()[0]
        return int(value)

    def _ensure_book_exists(self, book_id: int) -> None:
        row = self._database.connection.execute(
            "SELECT 1 FROM books WHERE id = ? AND archived = 0",
            (book_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(f"book does not exist or is archived: {book_id}")

    @staticmethod
    def _insert_account(
        connection: sqlite3.Connection,
        *,
        book_id: int,
        parent_id: int | None,
        account_type: str,
        name: str,
        currency_code: str | None,
        tracking_start_date: str | None,
        tracking_start_time: str | None,
        placeholder: bool,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO accounts(
                book_id, parent_id, type, name, currency_code,
                tracking_start_date, tracking_start_time, placeholder,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                book_id,
                parent_id,
                account_type,
                name,
                currency_code,
                tracking_start_date,
                tracking_start_time,
                int(placeholder),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _validate_date(value: str) -> None:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError("date must use ISO YYYY-MM-DD format") from exc

    @staticmethod
    def _validate_time(value: str) -> None:
        try:
            time.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError("time must use ISO HH:MM[:SS] format") from exc

    @staticmethod
    def _row_to_account(row) -> Account:
        return Account(
            id=int(row["id"]),
            book_id=int(row["book_id"]),
            parent_id=None if row["parent_id"] is None else int(row["parent_id"]),
            type=str(row["type"]),
            name=str(row["name"]),
            currency_code=None if row["currency_code"] is None else str(row["currency_code"]),
            tracking_start_date=(
                None if row["tracking_start_date"] is None else str(row["tracking_start_date"])
            ),
            tracking_start_time=(
                None if row["tracking_start_time"] is None else str(row["tracking_start_time"])
            ),
            placeholder=bool(row["placeholder"]),
            archived=bool(row["archived"]),
        )
