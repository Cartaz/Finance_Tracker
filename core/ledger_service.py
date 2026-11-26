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
    ValidationError,
)
from core.money import MAX_PERSISTED_MINOR
from core.tracking_policy import TrackingBoundaryPolicy, TrackingBoundaryStatus

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
REVERSAL_BLOCKERS = {
    "REVERSAL": "uno storno non può essere stornato",
    "REVERSED": "la transazione è già stata stornata",
    "LOAN": "appartiene a un prestito",
    "SCHEDULED": "è un'occorrenza di una transazione programmata",
    "RECONCILED": "è collegata a un movimento bancario riconciliato",
    "INVALID": "i conti coinvolti non accettano più registrazioni alla sua data "
    "(archiviati, contenitori o fuori dal periodo monitorato)",
}


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
            return self.get_transaction(
                draft.book_id, transaction_id, connection=connection
            )

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
        connection: sqlite3.Connection | None = None,
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
            ),
            connection=connection,
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
        connection: sqlite3.Connection | None = None,
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
            ),
            connection=connection,
        )

    def create_refund(
        self,
        *,
        book_id: int,
        destination_account_id: int,
        expense_account_id: int,
        amount_minor: int,
        currency_code: str,
        transaction_date: str,
        transaction_time: str | None = None,
        description: str = "",
        connection: sqlite3.Connection | None = None,
    ) -> TransactionRecord:
        self._require_positive_minor(amount_minor)
        self._require_native_currency(book_id, destination_account_id, currency_code)
        self._require_account_type(book_id, expense_account_id, "EXPENSE")
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="REFUND",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=currency_code,
                description=description,
                entries=(
                    EntryDraft(destination_account_id, amount_minor, amount_minor),
                    EntryDraft(expense_account_id, -amount_minor, None),
                ),
            ),
            connection=connection,
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
        connection: sqlite3.Connection | None = None,
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
            ),
            connection=connection,
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
        connection: sqlite3.Connection | None = None,
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
            ),
            connection=connection,
        )

    def create_adjustment(
        self,
        *,
        book_id: int,
        account_id: int,
        equity_account_id: int,
        quantity_minor: int,
        currency_code: str,
        transaction_date: str,
        transaction_time: str | None = None,
        description: str = "Adjustment",
        connection: sqlite3.Connection | None = None,
    ) -> TransactionRecord:
        self._require_nonzero_minor(quantity_minor)
        self._require_native_currency(book_id, account_id, currency_code)
        self._require_account_type(book_id, equity_account_id, "EQUITY")
        return self.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="ADJUSTMENT",
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                currency_code=currency_code,
                description=description,
                entries=(
                    EntryDraft(account_id, quantity_minor, quantity_minor),
                    EntryDraft(equity_account_id, -quantity_minor, None),
                ),
            ),
            connection=connection,
        )

    def reversal_blockers(
        self,
        book_id: int,
        transaction_ids: list[int],
        *,
        connection: sqlite3.Connection | None = None,
        check_postability: bool = True,
    ) -> dict[int, str]:
        """Blocker code (see REVERSAL_BLOCKERS) for each non-reversible transaction.

        Ownership blocks first: loan installments, scheduled occurrences and
        reconciled bank rows keep their own records of a transaction. With
        ``check_postability`` the reversal on the original date is also run
        through the canonical entry and tracking-boundary rules, in bulk.
        """
        if not transaction_ids:
            return {}
        conn = connection or self._database.connection
        placeholders = ",".join("?" for _ in transaction_ids)
        rows = conn.execute(
            f"""
            SELECT t.id, t.kind, t.transaction_date, t.transaction_time,
                   t.kind = 'REVERSAL' AS reversal,
                   EXISTS (SELECT 1 FROM transactions r
                           WHERE r.reverses_transaction_id = t.id) AS reversed,
                   EXISTS (SELECT 1 FROM loan_payments p
                           WHERE p.book_id = t.book_id AND p.transaction_id = t.id)
                   OR EXISTS (SELECT 1 FROM loans l
                              WHERE l.book_id = t.book_id
                                AND l.origination_transaction_id = t.id) AS loan,
                   EXISTS (SELECT 1 FROM scheduled_occurrences o
                           WHERE o.book_id = t.book_id AND o.transaction_id = t.id) AS scheduled,
                   EXISTS (SELECT 1 FROM reconciliation_links k
                           WHERE k.book_id = t.book_id AND k.transaction_id = t.id)
                   OR EXISTS (SELECT 1 FROM import_rows i
                              WHERE i.book_id = t.book_id
                                AND i.matched_transaction_id = t.id
                                AND i.review_state IN ('MATCHED', 'POSTED')) AS reconciled
            FROM transactions t
            WHERE t.book_id = ? AND t.id IN ({placeholders})
            """,
            (book_id, *transaction_ids),
        ).fetchall()
        blockers: dict[int, str] = {}
        candidates = []
        for row in rows:
            for code in ("REVERSAL", "REVERSED", "LOAN", "SCHEDULED", "RECONCILED"):
                if row[code.lower()]:
                    blockers[int(row["id"])] = code
                    break
            else:
                candidates.append(row)
        if check_postability and candidates:
            for transaction_id in self._unpostable_reversals(conn, book_id, candidates):
                blockers[transaction_id] = "INVALID"
        return blockers

    def _unpostable_reversals(self, conn, book_id: int, candidates) -> set[int]:
        """Ids whose reversal on the original date breaks entry/boundary rules."""
        ids = [int(row["id"]) for row in candidates]
        placeholders = ",".join("?" for _ in ids)
        entries = conn.execute(
            f"""
            SELECT e.transaction_id, e.account_id, e.value_minor, e.quantity_minor,
                   a.id, a.book_id, a.type, a.currency_code, a.tracking_start_date,
                   a.tracking_start_time, a.placeholder, a.archived
            FROM entries e
            JOIN accounts a ON a.id = e.account_id AND a.book_id = e.book_id
            WHERE e.book_id = ? AND e.transaction_id IN ({placeholders})
            """,
            (book_id, *ids),
        ).fetchall()
        by_transaction: dict[int, list] = {}
        for entry in entries:
            by_transaction.setdefault(int(entry["transaction_id"]), []).append(entry)
        invalid: set[int] = set()
        for row in candidates:
            draft = TransactionDraft(
                book_id=book_id,
                kind="REVERSAL",
                transaction_date=str(row["transaction_date"]),
                transaction_time=row["transaction_time"],
                currency_code="",
                entries=(),
            )
            try:
                for entry in by_transaction.get(int(row["id"]), []):
                    quantity = entry["quantity_minor"]
                    self._validate_entry_semantics(
                        EntryDraft(
                            int(entry["account_id"]),
                            -int(entry["value_minor"]),
                            None if quantity is None else -int(quantity),
                        ),
                        entry,
                    )
                    self._validate_tracking_boundary(draft, entry, "REVERSAL")
            except ValidationError:
                invalid.add(int(row["id"]))
        return invalid

    def create_reversal(
        self,
        *,
        book_id: int,
        transaction_id: int,
        transaction_date: str,
        transaction_time: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> TransactionRecord:
        if connection is not None:
            reversal_id = self._create_reversal(
                book_id, transaction_id, transaction_date, transaction_time, connection
            )
            return self.get_transaction(book_id, reversal_id, connection=connection)
        with self._database.transaction() as conn:
            reversal_id = self._create_reversal(
                book_id, transaction_id, transaction_date, transaction_time, conn
            )
        return self.get_transaction(book_id, reversal_id)

    def _create_reversal(
        self,
        book_id: int,
        transaction_id: int,
        transaction_date: str,
        transaction_time: str | None,
        conn: sqlite3.Connection,
    ) -> int:
        original = self.get_transaction(book_id, transaction_id, connection=conn)
        # Ownership only: the draft itself is validated at the requested date.
        blocker = self.reversal_blockers(
            book_id, [transaction_id], connection=conn, check_postability=False
        ).get(transaction_id)
        if blocker is not None:
            raise LedgerValidationError(
                f"storno non consentito: {REVERSAL_BLOCKERS[blocker]}"
            )
        reversal_id = self._create_transaction(
            self._reversal_draft(original, transaction_date, transaction_time), conn
        )
        # The reversal belongs to the same counterparty, so merchant reports net out.
        conn.execute(
            """
            UPDATE transactions
            SET payee_id = (SELECT payee_id FROM transactions WHERE id = ? AND book_id = ?)
            WHERE id = ? AND book_id = ?
            """,
            (transaction_id, book_id, reversal_id, book_id),
        )
        return reversal_id

    @staticmethod
    def _reversal_draft(
        original: TransactionRecord, transaction_date: str, transaction_time: str | None
    ) -> TransactionDraft:
        return TransactionDraft(
            book_id=original.book_id,
            kind="REVERSAL",
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            currency_code=original.currency_code,
            description=f"Reversal of transaction {original.id}",
            entries=tuple(
                EntryDraft(
                    account_id=entry.account_id,
                    value_minor=-entry.value_minor,
                    quantity_minor=(
                        None if entry.quantity_minor is None else -entry.quantity_minor
                    ),
                    memo=f"Reversal of entry {entry.id}",
                )
                for entry in original.entries
            ),
            reverses_transaction_id=original.id,
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
                None
                if row["transaction_time"] is None
                else str(row["transaction_time"])
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
        normalized_kind, transaction_date, transaction_time, currency_code = (
            self._validate_draft(draft, conn)
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
                transaction_date,
                transaction_time,
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

    def _validate_draft(
        self, draft: TransactionDraft, conn: sqlite3.Connection
    ) -> tuple[str, str, str | None, str]:
        """Every posting rule, without writing: (kind, date, time, currency)."""
        normalized_kind = draft.kind.upper()
        if normalized_kind not in _TRANSACTION_KINDS:
            raise LedgerValidationError(f"unsupported transaction kind: {draft.kind}")
        transaction_date = self._validate_date(draft.transaction_date)
        transaction_time = None
        if draft.transaction_time is not None:
            transaction_time = self._validate_time(draft.transaction_time)
        currency_code = self._database.currency(draft.currency_code).code

        if len(draft.entries) < 2:
            raise LedgerValidationError("a transaction requires at least two entries")
        self._validate_original_amount(draft)
        self._validate_integer_values(draft.entries)
        if sum(entry.value_minor for entry in draft.entries) != 0:
            raise UnbalancedTransactionError(
                "transaction entry values must sum to zero"
            )

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
            already_reversed = conn.execute(
                "SELECT 1 FROM transactions WHERE reverses_transaction_id = ?",
                (draft.reverses_transaction_id,),
            ).fetchone()
            if already_reversed is not None:
                raise LedgerValidationError("transaction has already been reversed")
        return normalized_kind, transaction_date, transaction_time, currency_code

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

        missing = [
            account_id for account_id in account_ids if account_id not in accounts
        ]
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
            raise CrossBookReferenceError(
                f"account {account_id} belongs to another book"
            )
        if str(row["type"]) not in _BALANCE_TYPES:
            raise LedgerValidationError(
                "source/destination account must be an asset or liability"
            )
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
            raise CrossBookReferenceError(
                f"account {account_id} belongs to another book"
            )
        if str(row["type"]) != expected_type:
            raise LedgerValidationError(
                f"account {account_id} must be of type {expected_type}"
            )

    @staticmethod
    def _require_storage_range(value: int, field: str) -> None:
        if abs(value) > MAX_PERSISTED_MINOR:
            raise LedgerValidationError(f"{field} exceeds supported storage range")

    @staticmethod
    def _validate_integer_values(entries: tuple[EntryDraft, ...]) -> None:
        for entry in entries:
            if isinstance(entry.value_minor, bool) or not isinstance(
                entry.value_minor, int
            ):
                raise LedgerValidationError("entry value_minor must be an integer")
            LedgerService._require_storage_range(entry.value_minor, "entry value_minor")
            if entry.value_minor == 0:
                raise LedgerValidationError("entry value_minor cannot be zero")
            if entry.quantity_minor is not None:
                if isinstance(entry.quantity_minor, bool) or not isinstance(
                    entry.quantity_minor, int
                ):
                    raise LedgerValidationError(
                        "entry quantity_minor must be an integer or None"
                    )
                LedgerService._require_storage_range(
                    entry.quantity_minor, "entry quantity_minor"
                )

    @staticmethod
    def _validate_entry_semantics(entry: EntryDraft, account: sqlite3.Row) -> None:
        if bool(account["archived"]):
            raise AccountArchivedError(f"account {entry.account_id} is archived")
        if bool(account["placeholder"]):
            raise AccountPlaceholderError(
                f"account {entry.account_id} is a placeholder"
            )

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
        result = TrackingBoundaryPolicy.classify(
            tracking_start_date=str(account["tracking_start_date"]),
            tracking_start_time=(
                None
                if account["tracking_start_time"] is None
                else str(account["tracking_start_time"])
            ),
            transaction_date=draft.transaction_date,
            transaction_time=draft.transaction_time,
            opening_balance=normalized_kind == "OPENING_BALANCE",
        )
        if result.status is TrackingBoundaryStatus.BEFORE_BOUNDARY:
            raise TrackingBoundaryError(
                f"transaction precedes tracking start for account {account['id']}"
            )
        if result.status is TrackingBoundaryStatus.AMBIGUOUS:
            raise TrackingBoundaryAmbiguousError(
                f"time precision is insufficient for account {account['id']} tracking boundary"
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
        if draft.original_amount_minor is not None:
            if isinstance(draft.original_amount_minor, bool) or not isinstance(
                draft.original_amount_minor, int
            ):
                raise LedgerValidationError("original_amount_minor must be an integer")
            LedgerService._require_storage_range(
                draft.original_amount_minor, "original_amount_minor"
            )

    @staticmethod
    def _validate_date(value: str) -> str:
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as exc:
            raise LedgerValidationError("date must use ISO YYYY-MM-DD format") from exc

    @staticmethod
    def _validate_time(value: str) -> str:
        try:
            parsed = time.fromisoformat(value)
            if parsed.tzinfo is not None:
                raise ValueError("local time cannot include an offset")
            return parsed.isoformat()
        except (TypeError, ValueError) as exc:
            raise LedgerValidationError("time must use ISO HH:MM[:SS] format") from exc

    @staticmethod
    def _require_positive_minor(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise LedgerValidationError("amount_minor must be a positive integer")
        LedgerService._require_storage_range(value, "amount_minor")

    @staticmethod
    def _require_nonzero_minor(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value == 0:
            raise LedgerValidationError("amount_minor must be a non-zero integer")
        LedgerService._require_storage_range(value, "amount_minor")
