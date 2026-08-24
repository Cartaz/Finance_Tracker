from __future__ import annotations

import sqlite3

from core.migrations import apply_migrations as apply_legacy_migrations

_LEGACY_SCHEMA_VERSION = 7

_SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    liability_account_id INTEGER NOT NULL,
    payment_account_id INTEGER NOT NULL,
    interest_expense_account_id INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    original_principal_minor INTEGER NOT NULL CHECK (original_principal_minor > 0),
    annual_rate_bps INTEGER NOT NULL CHECK (annual_rate_bps BETWEEN 0 AND 100000),
    term_months INTEGER NOT NULL CHECK (term_months BETWEEN 1 AND 600),
    first_due_date TEXT NOT NULL,
    origination_transaction_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, book_id),
    UNIQUE (book_id, liability_account_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (liability_account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (payment_account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (interest_expense_account_id, book_id) REFERENCES accounts(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (currency_code) REFERENCES currencies(code) ON DELETE RESTRICT,
    FOREIGN KEY (origination_transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS loan_payments (
    loan_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    installment_number INTEGER NOT NULL CHECK (installment_number >= 1),
    due_date TEXT NOT NULL,
    principal_minor INTEGER NOT NULL CHECK (principal_minor > 0),
    interest_minor INTEGER NOT NULL CHECK (interest_minor >= 0),
    payment_minor INTEGER NOT NULL CHECK (payment_minor > 0),
    transaction_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (loan_id, installment_number),
    UNIQUE (book_id, transaction_id),
    FOREIGN KEY (loan_id, book_id) REFERENCES loans(id, book_id) ON DELETE RESTRICT,
    FOREIGN KEY (transaction_id, book_id) REFERENCES transactions(id, book_id) ON DELETE RESTRICT,
    CHECK (payment_minor = principal_minor + interest_minor)
);
CREATE INDEX IF NOT EXISTS idx_loans_book_name
    ON loans(book_id, name COLLATE NOCASE, id);
CREATE INDEX IF NOT EXISTS idx_loan_payments_book_loan
    ON loan_payments(book_id, loan_id, installment_number);
CREATE TRIGGER IF NOT EXISTS trg_loans_account_types_insert
BEFORE INSERT ON loans
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = NEW.liability_account_id AND a.book_id = NEW.book_id
          AND a.type = 'LIABILITY' AND a.currency_code = NEW.currency_code
    ) THEN RAISE(ABORT, 'loan liability must match book and currency') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = NEW.payment_account_id AND a.book_id = NEW.book_id
          AND a.type = 'ASSET' AND a.currency_code = NEW.currency_code
    ) THEN RAISE(ABORT, 'loan payment account must match book and currency') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = NEW.interest_expense_account_id AND a.book_id = NEW.book_id
          AND a.type = 'EXPENSE'
    ) THEN RAISE(ABORT, 'loan interest account must be an expense account') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_loans_account_types_update
BEFORE UPDATE OF book_id, liability_account_id, payment_account_id,
                 interest_expense_account_id, currency_code ON loans
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = NEW.liability_account_id AND a.book_id = NEW.book_id
          AND a.type = 'LIABILITY' AND a.currency_code = NEW.currency_code
    ) THEN RAISE(ABORT, 'loan liability must match book and currency') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = NEW.payment_account_id AND a.book_id = NEW.book_id
          AND a.type = 'ASSET' AND a.currency_code = NEW.currency_code
    ) THEN RAISE(ABORT, 'loan payment account must match book and currency') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = NEW.interest_expense_account_id AND a.book_id = NEW.book_id
          AND a.type = 'EXPENSE'
    ) THEN RAISE(ABORT, 'loan interest account must be an expense account') END;
END;
"""


def apply_migrations(
    connection: sqlite3.Connection,
    *,
    current_version: int,
    target_version: int,
) -> None:
    """Apply the immutable historical catalog plus current extension migrations."""
    legacy_target = min(target_version, _LEGACY_SCHEMA_VERSION)
    if current_version < legacy_target:
        apply_legacy_migrations(
            connection,
            current_version=current_version,
            target_version=legacy_target,
        )
    if current_version < 8 <= target_version:
        connection.executescript(_SCHEMA_V8)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at, description) VALUES (8, datetime('now'), ?)",
            ("Fixed-rate loan contracts and ledger-linked payments",),
        )
