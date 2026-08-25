from __future__ import annotations

import sqlite3

import pytest

from core.backup_service import BackupService
from core.book_service import BookService
from core.database import Database
from core.errors import BackupError


def _database(tmp_path):
    database = Database(tmp_path / "live.db")
    database.open()
    database.migrate()
    return database


def test_managed_backup_is_verified_and_listed(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        BookService(database).create_personal_book(
            user_name="User", book_name="Original", currency_code="EUR"
        )
        service = BackupService(database, tmp_path / "backups")
        created = service.create_managed_backup()
        listed = service.list_backups()

        assert created["name"].startswith("finance-tracker-")
        assert created["name"].endswith(".sqlite3")
        assert created["schemaVersion"] > 0
        assert listed == [created]
    finally:
        database.close()


def test_restore_replaces_live_state_with_verified_backup(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        books = BookService(database)
        book = books.create_personal_book(
            user_name="User", book_name="Original", currency_code="EUR"
        )
        service = BackupService(database, tmp_path / "backups")
        backup = service.create_managed_backup()

        with database.transaction() as tx:
            tx.execute("UPDATE books SET name='Changed' WHERE id=?", (book.id,))
        assert books.current_book().name == "Changed"

        plan = service.prepare_restore(service.managed_path(str(backup["name"])))
        result = service.finalize_restore(plan)

        assert result["restoredFrom"] == backup["name"]
        assert books.current_book().name == "Original"
        database.integrity_check()
    finally:
        database.close()


def test_prepare_restore_rejects_non_finance_tracker_database(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        foreign = tmp_path / "foreign.sqlite3"
        conn = sqlite3.connect(foreign)
        try:
            conn.execute("CREATE TABLE unrelated(value TEXT)")
            conn.commit()
        finally:
            conn.close()

        service = BackupService(database, tmp_path / "backups")
        with pytest.raises(BackupError, match="not a Finance Tracker"):
            service.prepare_restore(foreign)
    finally:
        database.close()


def test_prepare_restore_rejects_newer_schema_without_touching_live_db(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        books = BookService(database)
        books.create_personal_book(
            user_name="User", book_name="Live", currency_code="EUR"
        )
        service = BackupService(database, tmp_path / "backups")
        backup = service.create_managed_backup()
        source = service.managed_path(str(backup["name"]))

        conn = sqlite3.connect(source)
        try:
            conn.execute("INSERT INTO schema_migrations(version) VALUES (999)")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(BackupError, match="newer than supported"):
            service.prepare_restore(source)
        assert books.current_book().name == "Live"
        database.integrity_check()
    finally:
        database.close()
