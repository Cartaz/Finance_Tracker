from pathlib import Path

import pytest

from core.database import Database
from core.errors import UnsupportedCurrencyError


def test_migration_enables_foundation_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "finance.db")
    try:
        conn = db.open()
        db.migrate()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 1
        assert db.currency("EUR").minor_unit_digits == 2
        assert db.currency("JPY").minor_unit_digits == 0
        assert db.currency("KWD").minor_unit_digits == 3
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
        finally:
            restored.close()
    finally:
        db.close()
