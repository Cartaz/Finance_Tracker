import sqlite3
from pathlib import Path

import pytest

from config.constants import SCHEMA_VERSION
from core.account_service import AccountService
from core.currency_registry import DEFAULT_CURRENCIES
from core.database import Database
from core.errors import UnsupportedCurrencyError
from core.ledger_service import LedgerService
from core.migrations import _SCHEMA_V1, _SCHEMA_V2


def test_migration_enables_current_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "finance.db")
    try:
        conn = db.open()
        db.migrate()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "accounts",
            "transactions",
            "entries",
            "payees",
            "payee_aliases",
            "fx_rates",
            "import_batches",
            "import_rows",
            "reconciliation_links",
            "scheduled_transactions",
            "scheduled_occurrences",
            "budgets",
            "loans",
            "loan_payments",
            "loan_rate_revisions",
        } <= tables
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
        }
        assert "payee_id" in columns
        loan_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(loans)").fetchall()
        }
        assert {"rate_type", "amortization_type", "recast_strategy"} <= loan_columns
        assert db.currency("EUR").minor_unit_digits == 2
        assert db.currency("JPY").minor_unit_digits == 0
        assert db.currency("KWD").minor_unit_digits == 3
        db.integrity_check()
    finally:
        db.close()


def test_existing_v2_database_with_ledger_data_upgrades_to_current_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "finance.db"
    db = Database(path)
    db.open()
    with db.transaction() as conn:
        conn.executescript(_SCHEMA_V1)
        conn.executemany(
            "INSERT OR IGNORE INTO currencies(code, name, symbol, minor_unit_digits) VALUES (?, ?, ?, ?)",
            DEFAULT_CURRENCIES,
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at, description) VALUES (1, datetime('now'), 'v1 fixture')"
        )
        conn.executescript(_SCHEMA_V2)
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at, description) VALUES (2, datetime('now'), 'v2 fixture')"
        )
        user_id = int(
            conn.execute(
                "INSERT INTO users(name, created_at, updated_at) VALUES ('User', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        book_id = int(
            conn.execute(
                "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('Book', 'EUR', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO book_members(book_id, user_id, role) VALUES (?, ?, 'OWNER')",
            (book_id, user_id),
        )

    accounts = AccountService(db)
    ledger = LedgerService(db)
    bank = accounts.create_account(
        book_id=book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    expense = accounts.create_account(
        book_id=book_id,
        account_type="EXPENSE",
        name="Groceries",
    )
    equity = accounts.create_account(
        book_id=book_id,
        account_type="EQUITY",
        name="Opening",
    )
    ledger.create_opening_balance(
        book_id=book_id,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=100_000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="00:00:00",
    )
    ledger.create_expense(
        book_id=book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=1_500,
        currency_code="EUR",
        transaction_date="2026-08-26",
    )
    assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
    assert db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
    assert "payee_id" not in {
        row[1] for row in db.connection.execute("PRAGMA table_info(transactions)").fetchall()
    }
    db.close()

    upgraded = Database(path)
    try:
        upgraded.open()
        upgraded.migrate()
        assert upgraded.connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == SCHEMA_VERSION
        assert upgraded.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert upgraded.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 4
        columns = {
            row[1]
            for row in upgraded.connection.execute(
                "PRAGMA table_info(transactions)"
            ).fetchall()
        }
        assert "payee_id" in columns
        for table in (
            "fx_rates",
            "import_batches",
            "import_rows",
            "reconciliation_links",
            "scheduled_transactions",
            "scheduled_occurrences",
            "budgets",
            "loans",
            "loan_payments",
            "loan_rate_revisions",
        ):
            assert upgraded.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        upgraded.integrity_check()
    finally:
        upgraded.close()


def test_import_rows_cannot_reference_batch_from_another_book(tmp_path: Path) -> None:
    db = Database(tmp_path / "cross-book.db")
    db.open()
    db.migrate()
    try:
        with db.transaction() as conn:
            user_id = int(
                conn.execute(
                    "INSERT INTO users(name, created_at, updated_at) VALUES ('User', datetime('now'), datetime('now'))"
                ).lastrowid
            )
            book_a = int(
                conn.execute(
                    "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('A','EUR',datetime('now'),datetime('now'))"
                ).lastrowid
            )
            book_b = int(
                conn.execute(
                    "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('B','EUR',datetime('now'),datetime('now'))"
                ).lastrowid
            )
            conn.executemany(
                "INSERT INTO book_members(book_id,user_id,role) VALUES (?,?,'OWNER')",
                ((book_a, user_id), (book_b, user_id)),
            )
        accounts = AccountService(db)
        account_a = accounts.create_account(
            book_id=book_a,
            account_type="ASSET",
            name="A Bank",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        with db.transaction() as conn:
            batch_id = int(
                conn.execute(
                    "INSERT INTO import_batches(book_id,account_id,source_name,review_mode,imported_at,row_count) VALUES (?,?,?,'FULL_REVIEW',datetime('now'),1)",
                    (book_a, account_a.id, "bank"),
                ).lastrowid
            )
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO import_rows(
                    batch_id,book_id,row_number,transaction_date,amount_minor,currency_code,
                    description,fingerprint,review_state,created_at
                ) VALUES (?,?,1,'2026-01-02',-100,'EUR','x','f','REVIEW_REQUIRED',datetime('now'))
                """,
                (batch_id, book_b),
            )
        assert db.connection.execute("SELECT COUNT(*) FROM import_rows").fetchone()[0] == 0
        db.integrity_check()
    finally:
        db.close()


def test_unknown_currency_is_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path / "finance.db")
    try:
        db.open()
        db.migrate()
        with pytest.raises(UnsupportedCurrencyError):
            db.currency("ZZZ")
    finally:
        db.close()


def test_backup_is_verified_snapshot(tmp_path: Path) -> None:
    db = Database(tmp_path / "finance.db")
    backup = tmp_path / "backups" / "snapshot.db"
    try:
        db.open()
        db.migrate()
        db.backup_to(backup)
        assert backup.exists()
        restored = Database(backup)
        try:
            restored.open()
            restored.integrity_check()
            assert restored.currency("EUR").code == "EUR"
            assert restored.connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0] == SCHEMA_VERSION
        finally:
            restored.close()
    finally:
        db.close()
