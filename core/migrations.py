from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from core.currency_registry import DEFAULT_CURRENCIES


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    description: str
    script: str
    seed_currencies: bool = False


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

MIGRATIONS = (
    Migration(1, "Initial foundation schema", _SCHEMA_V1, seed_currencies=True),
    Migration(2, "Ledger core schema", _SCHEMA_V2),
    Migration(3, "Payees, aliases and transaction payee metadata", _SCHEMA_V3),
    Migration(4, "Book-scoped historical FX rates for reporting", _SCHEMA_V4),
    Migration(5, "CSV import staging and zero-trust reconciliation", _SCHEMA_V5),
    Migration(6, "Scheduled transaction templates and posted occurrences", _SCHEMA_V6),
)


def apply_migrations(
    connection: sqlite3.Connection,
    *,
    current_version: int,
    target_version: int,
) -> None:
    for migration in MIGRATIONS:
        if not current_version < migration.version <= target_version:
            continue
        connection.executescript(migration.script)
        if migration.seed_currencies:
            connection.executemany(
                "INSERT OR IGNORE INTO currencies(code, name, symbol, minor_unit_digits) VALUES (?, ?, ?, ?)",
                DEFAULT_CURRENCIES,
            )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at, description) VALUES (?, datetime('now'), ?)",
            (migration.version, migration.description),
        )
