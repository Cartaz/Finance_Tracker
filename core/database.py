from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.constants import DATABASE_PATH, SCHEMA_VERSION
from core.errors import DatabaseIntegrityError, UnsupportedCurrencyError
from core.money import CurrencySpec

_CURRENCIES = (
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

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT,
    minor_unit_digits INTEGER NOT NULL CHECK (minor_unit_digits >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    base_currency_code TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (base_currency_code) REFERENCES currencies(code) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS book_members (
    book_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'EDITOR', 'VIEWER')),
    PRIMARY KEY (book_id, user_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_books_currency ON books(base_currency_code);
CREATE INDEX IF NOT EXISTS idx_book_members_user ON book_members(user_id);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    parent_id INTEGER,
    type TEXT NOT NULL CHECK (type IN ('ASSET', 'LIABILITY', 'INCOME', 'EXPENSE', 'EQUITY')),
    name TEXT NOT NULL,
    currency_code TEXT,
    tracking_start_date TEXT,
    tracking_start_time TEXT,
    placeholder INTEGER NOT NULL DEFAULT 0 CHECK (placeholder IN (0, 1)),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, book_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (currency_code) REFERENCES currencies(code) ON DELETE RESTRICT,
    FOREIGN KEY (parent_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    CHECK (
        (type IN ('ASSET', 'LIABILITY') AND currency_code IS NOT NULL AND tracking_start_date IS NOT NULL)
        OR
        (type IN ('INCOME', 'EXPENSE', 'EQUITY') AND currency_code IS NULL AND tracking_start_date IS NULL AND tracking_start_time IS NULL)
    )
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('EXPENSE', 'INCOME', 'TRANSFER', 'OPENING_BALANCE', 'ADJUSTMENT', 'REFUND', 'REVERSAL')
    ),
    transaction_date TEXT NOT NULL,
    transaction_time TEXT,
    currency_code TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    original_amount_minor INTEGER,
    original_currency_code TEXT,
    reverses_transaction_id INTEGER,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, book_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (currency_code) REFERENCES currencies(code) ON DELETE RESTRICT,
    FOREIGN KEY (original_currency_code) REFERENCES currencies(code) ON DELETE RESTRICT,
    FOREIGN KEY (reverses_transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
    CHECK (
        (original_amount_minor IS NULL AND original_currency_code IS NULL)
        OR
        (original_amount_minor IS NOT NULL AND original_currency_code IS NOT NULL)
    )
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    quantity_minor INTEGER,
    value_minor INTEGER NOT NULL CHECK (value_minor <> 0),
    posted_date TEXT,
    posted_time TEXT,
    memo TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_accounts_book_parent ON accounts(book_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_accounts_book_type ON accounts(book_id, type);
CREATE INDEX IF NOT EXISTS idx_transactions_book_date ON transactions(book_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_entries_transaction ON entries(transaction_id);
CREATE INDEX IF NOT EXISTS idx_entries_account ON entries(book_id, account_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_single_reversal
    ON transactions(reverses_transaction_id)
    WHERE reverses_transaction_id IS NOT NULL;
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS payees (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, book_id),
    UNIQUE (book_id, normalized_name),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS payee_aliases (
    id INTEGER PRIMARY KEY,
    payee_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    match_type TEXT NOT NULL CHECK (match_type IN ('EXACT', 'PREFIX')),
    created_at TEXT NOT NULL,
    UNIQUE (book_id, normalized_alias),
    FOREIGN KEY (payee_id, book_id) REFERENCES payees(id, book_id) ON DELETE RESTRICT
);
ALTER TABLE transactions ADD COLUMN payee_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_payees_book_name ON payees(book_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_payee_aliases_book_alias ON payee_aliases(book_id, normalized_alias);
CREATE INDEX IF NOT EXISTS idx_transactions_book_payee ON transactions(book_id, payee_id);
CREATE TRIGGER IF NOT EXISTS trg_transactions_payee_insert
BEFORE INSERT ON transactions
WHEN NEW.payee_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM payees p WHERE p.id = NEW.payee_id AND p.book_id = NEW.book_id
    ) THEN RAISE(ABORT, 'invalid transaction payee for book') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_transactions_payee_update
BEFORE UPDATE OF payee_id, book_id ON transactions
WHEN NEW.payee_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM payees p WHERE p.id = NEW.payee_id AND p.book_id = NEW.book_id
    ) THEN RAISE(ABORT, 'invalid transaction payee for book') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_payees_delete_restrict
BEFORE DELETE ON payees
WHEN EXISTS (SELECT 1 FROM transactions t WHERE t.payee_id = OLD.id AND t.book_id = OLD.book_id)
BEGIN
    SELECT RAISE(ABORT, 'payee is referenced by transactions');
END;
"""

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS fx_rates (
    book_id INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    rate_date TEXT NOT NULL,
    rate_text TEXT NOT NULL CHECK (length(rate_text) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (book_id, currency_code, rate_date),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (currency_code) REFERENCES currencies(code) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_fx_rates_lookup
    ON fx_rates(book_id, currency_code, rate_date DESC);
"""

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    review_mode TEXT NOT NULL CHECK (review_mode IN ('FULL_REVIEW', 'ASSISTED_REVIEW')),
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    UNIQUE (id, book_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS import_rows (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    transaction_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor <> 0),
    currency_code TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    external_id TEXT,
    fingerprint TEXT NOT NULL,
    review_state TEXT NOT NULL CHECK (review_state IN (
        'MATCHED', 'REVIEW_REQUIRED', 'SUGGESTED', 'AMBIGUOUS', 'UNMATCHED',
        'DUPLICATE_REVIEW', 'OUTSIDE_TRACKING', 'TRACKING_AMBIGUOUS', 'POSTED', 'IGNORED'
    )),
    matched_transaction_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, row_number),
    FOREIGN KEY (batch_id, book_id) REFERENCES import_batches(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (currency_code) REFERENCES currencies(code) ON DELETE RESTRICT,
    FOREIGN KEY (matched_transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconciliation_links (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    transaction_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (book_id, account_id, source_name, external_id),
    UNIQUE (book_id, account_id, transaction_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_import_batches_book_account ON import_batches(book_id, account_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_import_rows_batch_state ON import_rows(batch_id, review_state, row_number);
CREATE INDEX IF NOT EXISTS idx_import_rows_external ON import_rows(book_id, external_id) WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_import_rows_batch_external_unique
    ON import_rows(batch_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_import_rows_fingerprint ON import_rows(book_id, fingerprint);
CREATE INDEX IF NOT EXISTS idx_reconciliation_links_external
    ON reconciliation_links(book_id, account_id, source_name, external_id);
"""

_SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS scheduled_transactions (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('EXPENSE', 'INCOME', 'REFUND', 'TRANSFER')),
    source_account_id INTEGER NOT NULL,
    counter_account_id INTEGER NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency_code TEXT NOT NULL,
    frequency TEXT NOT NULL CHECK (frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')),
    interval_count INTEGER NOT NULL CHECK (interval_count BETWEEN 1 AND 365),
    start_date TEXT NOT NULL,
    next_due_date TEXT NOT NULL,
    end_date TEXT,
    description TEXT NOT NULL DEFAULT '',
    payee_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, book_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (counter_account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (currency_code) REFERENCES currencies(code) ON DELETE RESTRICT,
    FOREIGN KEY (payee_id, book_id) REFERENCES payees(id, book_id) ON DELETE RESTRICT,
    CHECK (end_date IS NULL OR end_date >= start_date),
    CHECK (next_due_date >= start_date)
);
CREATE TABLE IF NOT EXISTS scheduled_occurrences (
    schedule_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    transaction_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (schedule_id, due_date),
    FOREIGN KEY (schedule_id, book_id) REFERENCES scheduled_transactions(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_scheduled_due
    ON scheduled_transactions(book_id, active, next_due_date);
CREATE INDEX IF NOT EXISTS idx_scheduled_occurrence_transaction
    ON scheduled_occurrences(book_id, transaction_id);
"""


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None

    def open(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, autocommit=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if enabled != 1:
            conn.close()
            raise DatabaseIntegrityError("SQLite foreign key enforcement could not be enabled")
        journal_mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            conn.close()
            raise DatabaseIntegrityError(f"SQLite WAL mode unavailable: {journal_mode}")
        conn.autocommit = False
        self._connection = conn
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self.open()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def migrate(self) -> None:
        current = self._current_schema_version()
        if current > SCHEMA_VERSION:
            raise DatabaseIntegrityError(
                f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
            )
        if current < 1:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V1)
                tx.executemany(
                    "INSERT OR IGNORE INTO currencies(code, name, symbol, minor_unit_digits) VALUES (?, ?, ?, ?)",
                    _CURRENCIES,
                )
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (1, datetime('now'), ?)",
                    ("Initial foundation schema",),
                )
            current = 1
        if current < 2:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V2)
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (2, datetime('now'), ?)",
                    ("Ledger core schema",),
                )
            current = 2
        if current < 3:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V3)
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (3, datetime('now'), ?)",
                    ("Payees, aliases and transaction payee metadata",),
                )
            current = 3
        if current < 4:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V4)
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (4, datetime('now'), ?)",
                    ("Book-scoped historical FX rates for reporting",),
                )
            current = 4
        if current < 5:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V5)
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (5, datetime('now'), ?)",
                    ("CSV import staging and zero-trust reconciliation",),
                )
            current = 5
        if current < 6:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V6)
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (6, datetime('now'), ?)",
                    ("Scheduled transaction templates and posted occurrences",),
                )

    def _current_schema_version(self) -> int:
        if not self._table_exists("schema_migrations"):
            return 0
        return int(
            self.connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )

    def _table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def currency(self, code: str) -> CurrencySpec:
        row = self.connection.execute(
            "SELECT code, minor_unit_digits FROM currencies WHERE code=? AND active=1",
            (code.upper(),),
        ).fetchone()
        if row is None:
            raise UnsupportedCurrencyError(f"unsupported currency: {code}")
        return CurrencySpec(row["code"], row["minor_unit_digits"])

    def integrity_check(self) -> None:
        result = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise DatabaseIntegrityError(f"SQLite integrity_check failed: {result}")
        fk_rows = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise DatabaseIntegrityError("SQLite foreign_key_check reported violations")

    def backup_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(destination.suffix + ".tmp")
        if temp.exists():
            temp.unlink()
        source = self.connection
        source.commit()
        target = sqlite3.connect(temp, autocommit=True)
        try:
            source.backup(target)
        finally:
            target.close()
        verify = sqlite3.connect(temp, autocommit=True)
        try:
            verify.execute("PRAGMA foreign_keys = ON")
            integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise DatabaseIntegrityError(f"backup integrity_check failed: {integrity}")
            violations = verify.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise DatabaseIntegrityError("backup foreign_key_check reported violations")
        finally:
            verify.close()
        temp.replace(destination)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
