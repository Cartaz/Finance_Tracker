from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, time

from core.database import Database
from core.errors import (
    AccountArchivedError,
    AccountNotFoundError,
    AccountPlaceholderError,
    CrossBookReferenceError,
    LedgerValidationError,
    TrackingBoundaryAmbiguousError,
    TrackingBoundaryError,
    UnbalancedTransactionError,
)

_TRANSACTION_KINDS = {
    "EXPENSE",
    "INCOME",
    "TRANSFER",
    "OPENING_BALANCE",
    "ADJUSTMENT",
    "REFUND",
    "REVERSAL",
}
_BALANCE_TYPES = {"ASSET", "LIABILITY"}


@dataclass(frozen=True, slots=True)
class EntryDraft:
    account_id: int
    value_minor: int
    quantity_minor: int | None
    memo: str = ""


@dataclass(frozen=True, slots=True)
class TransactionDraft:
    book_id: int
    kind: str
    transaction_date: str
    currency_code: str
    entries: tuple[EntryDraft, ...]
    transaction_time: str | None = None
    description: str = ""
    notes: str = ""
    original_amount_minor: int | None = None
    original_currency_code: str | None = None
    reverses_transaction_id: int | None = None
    created_by_user_id: int | None = None


@dataclass(frozen=True, slots=True)
class EntryRecord:
    id: int
    account_id: int
    value_minor: int
    quantity_minor: int | None
    memo: str


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    id: int
    book_id: int
    kind: str
    transaction_date: str
    transaction_time: str | None
    currency_code: str
    description: str
    notes: str
    reverses_transaction_id: int | None
    entries: tuple[EntryRecord, ...]


class LedgerService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_transaction(
        self,
        draft: TransactionDraft,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> TransactionRecord:
        if connection is not None:
            transaction_id = self._create_transaction(draft, connection)
            return self.get_transaction(draft.book_id, transaction_id, connection=connection)

        with self._database.transaction() as conn:
            transaction_id = self._create_transaction(draft, conn)
        return self.get_transaction(draft.book_id, transaction_id)

    def create_expense(
        self,
        *,
        book_id: int,
        source_account_id: int,
        expense_account_id: int,
        amount_minor: int,
        currency_code: str,
        transaction_date: str,
        transaction_time: str | None = None,
        description: str = "",
    ) -> TransactionRecord:
        self._require_positive_minor(amount_minor)
        self._require_native_currency(book_id, source_account_id, currency_code)
        self._require_account_type(book_id, expense_account_id, "EXPENSE")
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="EXPENSE",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=currency_code,
                description=description,
                entries=(
                    EntryDraft(source_account_id, -amount_minor, -amount_minor),
                    EntryDraft(expense_account_id, amount_minor, None),
                ),
            )
        )

    def create_income(
        self,
        *,
        book_id: int,
        destination_account_id: int,
        income_account_id: int,
        amount_minor: int,
        currency_code: str,
        transaction_date: str,
        transaction_time: str | None = None,
        description: str = "",
    ) -> TransactionRecord:
        self._require_positive_minor(amount_minor)
        self._require_native_currency(book_id, destination_account_id, currency_code)
        self._require_account_type(book_id, income_account_id, "INCOME")
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="INCOME",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=currency_code,
                description=description,
                entries=(
                    EntryDraft(destination_account_id, amount_minor, amount_minor),
                    EntryDraft(income_account_id, -amount_minor, None),
                ),
            )
        )

    def create_transfer(
        self,
        *,
        book_id: int,
        source_account_id: int,
        destination_account_id: int,
        amount_minor: int,
        currency_code: str,
        transaction_date: str,
        transaction_time: str | None = None,
        description: str = "",
    ) -> TransactionRecord:
        self._require_positive_minor(amount_minor)
        self._require_native_currency(book_id, source_account_id, currency_code)
        self._require_native_currency(book_id, destination_account_id, currency_code)
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="TRANSFER",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=currency_code,
                description=description,
                entries=(
                    EntryDraft(source_account_id, -amount_minor, -amount_minor),
                    EntryDraft(destination_account_id, amount_minor, amount_minor),
                ),
            )
        )

    def create_opening_balance(
        self,
        *,
        book_id: int,
        account_id: int,
        equity_account_id: int,
        quantity_minor: int,
        currency_code: str,
        transaction_date: str,
        transaction_time: str | None = None,
        description: str = "Opening Balance",
    ) -> TransactionRecord:
        self._require_nonzero_minor(quantity_minor)
        self._require_native_currency(book_id, account_id, currency_code)
        self._require_account_type(book_id, equity_account_id, "EQUITY")
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="OPENING_BALANCE",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=currency_code,
                description=description,
                entries=(
                    EntryDraft(account_id, quantity_minor, quantity_minor),
                    EntryDraft(equity_account_id, -quantity_minor, None),
                ),
            )
        )

    def create_reversal(
        self,
        *,
        book_id: int,
        transaction_id: int,
        transaction_date: str,
        transaction_time: str | None = None,
    ) -> TransactionRecord:
        original = self.get_transaction(book_id, transaction_id)
        entries = tuple(
            EntryDraft(
                account_id=entry.account_id,
                value_minor=-entry.value_minor,
                quantity_minor=(
                    None if entry.quantity_minor is None else -entry.quantity_minor
                ),
                memo=f"Reversal of entry {entry.id}",
            )
            for entry in original.entries
        )
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="REVERSAL",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=original.currency_code,
                description=f"Reversal of transaction {transaction_id}",
                entries=entries,
                reverses_transaction_id=transaction_id,
            )
        )

    def get_transaction(
        self,
        book_id: int,
        transaction_id: int,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> TransactionRecord:
        conn = connection or self._database.connection
        row = conn.execute(
            """
            SELECT id, book_id, kind, transaction_date, transaction_time,
                   currency_code, description, notes, reverses_transaction_id
            FROM transactions
            WHERE id = ? AND book_id = ?
            """,
            (transaction_id, book_id),
        ).fetchone()
        if row is None:
            raise LedgerValidationError(
                f"transaction {transaction_id} does not exist in book {book_id}"
            )
        entry_rows = conn.execute(
            """
            SELECT id, account_id, value_minor, quantity_minor, memo
            FROM entries
            WHERE transaction_id = ? AND book_id = ?
            ORDER BY id
            """,
            (transaction_id, book_id),
        ).fetchall()
        entries = tuple(
            EntryRecord(
                id=int(entry["id"]),
                account_id=int(entry["account_id"]),
                value_minor=int(entry["value_minor"]),
                quantity_minor=(
                    None
                    if entry["quantity_minor"] is None
                    else int(entry["quantity_minor"])
                ),
                memo=str(entry["memo"]),
            )
            for entry in entry_rows
        )
        return TransactionRecord(
            id=int(row["id"]),
            book_id=int(row["book_id"]),
            kind=str(row["kind"]),
            transaction_date=str(row["transaction_date"]),
            transaction_time=(
                None if row["transaction_time"] is None else str(row["transaction_time"])
            ),
            currency_code=str(row["currency_code"]),
            description=str(row["description"]),
            notes=str(row["notes"]),
            reverses_transaction_id=(
                None
                if row["reverses_transaction_id"] is None
                else int(row["reverses_transaction_id"])
            ),
            entries=entries,
        )

    def _create_transaction(
        self,
        draft: TransactionDraft,
        conn: sqlite3.Connection,
    ) -> int:
        normalized_kind = draft.kind.upper()
        if normalized_kind not in _TRANSACTION_KINDS:
            raise LedgerValidationError(f"unsupported transaction kind: {draft.kind}")
        self._validate_date(draft.transaction_date)
        if draft.transaction_time is not None:
            self._validate_time(draft.transaction_time)
        currency_code = self._database.currency(draft.currency_code).code

        if len(draft.entries) < 2:
            raise LedgerValidationError("a transaction requires at least two entries")
        self._validate_original_amount(draft)
        self._validate_integer_values(draft.entries)
        if sum(entry.value_minor for entry in draft.entries) != 0:
            raise UnbalancedTransactionError("transaction entry values must sum to zero")

        accounts = self._load_accounts(conn, draft.book_id, draft.entries)
        for entry in draft.entries:
            account = accounts[entry.account_id]
            self._validate_entry_semantics(entry, account)
            self._validate_tracking_boundary(draft, account, normalized_kind)

        if draft.reverses_transaction_id is not None:
            row = conn.execute(
                "SELECT 1 FROM transactions WHERE id = ? AND book_id = ?",
                (draft.reverses_transaction_id, draft.book_id),
            ).fetchone()
            if row is None:
                raise CrossBookReferenceError(
                    "reversed transaction does not exist in the requested book"
                )

        cursor = conn.execute(
            """
            INSERT INTO transactions(
                book_id, kind, transaction_date, transaction_time, currency_code,
                description, notes, original_amount_minor, original_currency_code,
                reverses_transaction_id, created_by_user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                draft.book_id,
                normalized_kind,
                draft.transaction_date,
                draft.transaction_time,
                currency_code,
                draft.description.strip(),
                draft.notes.strip(),
                draft.original_amount_minor,
                (
                    None
                    if draft.original_currency_code is None
                    else self._database.currency(draft.original_currency_code).code
                ),
                draft.reverses_transaction_id,
                draft.created_by_user_id,
            ),
        )
        transaction_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO entries(
                transaction_id, book_id, account_id, quantity_minor, value_minor, memo
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    transaction_id,
                    draft.book_id,
                    entry.account_id,
                    entry.quantity_minor,
                    entry.value_minor,
                    entry.memo.strip(),
                )
                for entry in draft.entries
            ),
        )
        return transaction_id

    def _load_accounts(
        self,
        conn: sqlite3.Connection,
        book_id: int,
        entries: tuple[EntryDraft, ...],
    ) -> dict[int, sqlite3.Row]:
        account_ids = sorted({entry.account_id for entry in entries})
        placeholders = ",".join("?" for _ in account_ids)
        rows = conn.execute(
            f"""
            SELECT id, book_id, type, currency_code, tracking_start_date,
                   tracking_start_time, placeholder, archived
            FROM accounts
            WHERE book_id = ? AND id IN ({placeholders})
            """,
            (book_id, *account_ids),
        ).fetchall()
        accounts = {int(row["id"]): row for row in rows}
        if len(accounts) == len(account_ids):
            return accounts

        missing = [account_id for account_id in account_ids if account_id not in accounts]
        for account_id in missing:
            exists = conn.execute(
                "SELECT book_id FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if exists is not None:
                raise CrossBookReferenceError(
                    f"account {account_id} belongs to another book"
                )
        raise AccountNotFoundError(f"unknown account ids: {missing}")

    def _require_native_currency(
        self,
        book_id: int,
        account_id: int,
        currency_code: str,
    ) -> None:
        requested = self._database.currency(currency_code).code
        row = self._database.connection.execute(
            "SELECT book_id, type, currency_code FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError(f"unknown account id: {account_id}")
        if int(row["book_id"]) != book_id:
            raise CrossBookReferenceError(f"account {account_id} belongs to another book")
        if str(row["type"]) not in _BALANCE_TYPES:
            raise LedgerValidationError("source/destination account must be an asset or liability")
        if str(row["currency_code"]) != requested:
            raise LedgerValidationError(
                "convenience transaction currency must match the balance account currency"
            )

    def _require_account_type(
        self,
        book_id: int,
        account_id: int,
        expected_type: str,
    ) -> None:
        row = self._database.connection.execute(
            "SELECT book_id, type FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError(f"unknown account id: {account_id}")
        if int(row["book_id"]) != book_id:
            raise CrossBookReferenceError(f"account {account_id} belongs to another book")
        if str(row["type"]) != expected_type:
            raise LedgerValidationError(
                f"account {account_id} must be of type {expected_type}"
            )

    @staticmethod
    def _validate_integer_values(entries: tuple[EntryDraft, ...]) -> None:
        for entry in entries:
            if isinstance(entry.value_minor, bool) or not isinstance(entry.value_minor, int):
                raise LedgerValidationError("entry value_minor must be an integer")
            if entry.value_minor == 0:
                raise LedgerValidationError("entry value_minor cannot be zero")
            if entry.quantity_minor is not None and (
                isinstance(entry.quantity_minor, bool)
                or not isinstance(entry.quantity_minor, int)
            ):
                raise LedgerValidationError("entry quantity_minor must be an integer or None")

    @staticmethod
    def _validate_entry_semantics(entry: EntryDraft, account: sqlite3.Row) -> None:
        if bool(account["archived"]):
            raise AccountArchivedError(f"account {entry.account_id} is archived")
        if bool(account["placeholder"]):
            raise AccountPlaceholderError(f"account {entry.account_id} is a placeholder")

        account_type = str(account["type"])
        if account_type in _BALANCE_TYPES:
            if entry.quantity_minor is None:
                raise LedgerValidationError(
                    "asset and liability entries require quantity_minor"
                )
            if entry.quantity_minor == 0:
                raise LedgerValidationError(
                    "asset and liability entry quantity_minor cannot be zero"
                )
        elif entry.quantity_minor is not None:
            raise LedgerValidationError(
                "income, expense and equity entries must not have quantity_minor"
            )

    @staticmethod
    def _validate_tracking_boundary(
        draft: TransactionDraft,
        account: sqlite3.Row,
        normalized_kind: str,
    ) -> None:
        if str(account["type"]) not in _BALANCE_TYPES:
            return
        start_date_text = str(account["tracking_start_date"])
        start_time_text = (
            None
            if account["tracking_start_time"] is None
            else str(account["tracking_start_time"])
        )
        transaction_date = date.fromisoformat(draft.transaction_date)
        start_date = date.fromisoformat(start_date_text)
        if transaction_date < start_date:
            raise TrackingBoundaryError(
                f"transaction precedes tracking start for account {account['id']}"
            )
        if transaction_date > start_date:
            return

        if normalized_kind == "OPENING_BALANCE" and draft.transaction_time == start_time_text:
            return
        if start_time_text is None or draft.transaction_time is None:
            raise TrackingBoundaryAmbiguousError(
                f"time precision is insufficient for account {account['id']} tracking boundary"
            )
        if time.fromisoformat(draft.transaction_time) < time.fromisoformat(start_time_text):
            raise TrackingBoundaryError(
                f"transaction precedes tracking start for account {account['id']}"
            )

    @staticmethod
    def _validate_original_amount(draft: TransactionDraft) -> None:
        one_missing = (draft.original_amount_minor is None) != (
            draft.original_currency_code is None
        )
        if one_missing:
            raise LedgerValidationError(
                "original amount and original currency must be provided together"
            )
        if draft.original_amount_minor is not None and (
            isinstance(draft.original_amount_minor, bool)
            or not isinstance(draft.original_amount_minor, int)
        ):
            raise LedgerValidationError("original_amount_minor must be an integer")

    @staticmethod
    def _validate_date(value: str) -> None:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise LedgerValidationError("date must use ISO YYYY-MM-DD format") from exc

    @staticmethod
    def _validate_time(value: str) -> None:
        try:
            time.fromisoformat(value)
        except ValueError as exc:
            raise LedgerValidationError("time must use ISO HH:MM[:SS] format") from exc

    @staticmethod
    def _require_positive_minor(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise LedgerValidationError("amount_minor must be a positive integer")

    @staticmethod
    def _require_nonzero_minor(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value == 0:
            raise LedgerValidationError("amount_minor must be a non-zero integer")
