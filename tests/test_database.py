from pathlib import Path

import pytest

from core.account_service import AccountService
from core.database import _CURRENCIES, _SCHEMA_V1, _SCHEMA_V2, Database
from core.errors import UnsupportedCurrencyError
from core.ledger_service import LedgerService


def test_migration_enables_m6_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "finance.db")
    try:
        conn = db.open()
        db.migrate()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 5
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
        } <= tables
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
        }
        assert "payee_id" in columns
        assert db.currency("EUR").minor_unit_digits == 2
        assert db.currency("JPY").minor_unit_digits == 0
        assert db.currency("KWD").minor_unit_digits == 3
        db.integrity_check()
    finally:
        db.close()


def test_existing_v2_database_with_ledger_data_upgrades_to_v5(
    tmp_path: Path,
) -> None:
    path = tmp_path / "finance.db"
    db = Database(path)
    db.open()
    with db.transaction() as conn:
        conn.executescript(_SCHEMA_V1)
        conn.executemany(
            "INSERT OR IGNORE INTO currencies(code, name, symbol, minor_unit_digits) VALUES (?, ?, ?, ?)",
            _CURRENCIES,
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
        ).fetchone()[0] == 5
        assert upgraded.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert upgraded.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 4
        columns = {
            row[1]
            for row in upgraded.connection.execute(
                "PRAGMA table_info(transactions)"
            ).fetchall()
        }
        assert "payee_id" in columns
        assert upgraded.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE payee_id IS NOT NULL"
        ).fetchone()[0] == 0
        assert upgraded.connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 0
        assert upgraded.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 0
        assert upgraded.connection.execute("SELECT COUNT(*) FROM import_rows").fetchone()[0] == 0
        assert upgraded.connection.execute("SELECT COUNT(*) FROM reconciliation_links").fetchone()[0] == 0
        upgraded.integrity_check()
    finally:
        upgraded.close()


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
            ).fetchone()[0] == 5
        finally:
            restored.close()
    finally:
        db.close()
