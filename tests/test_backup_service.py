from __future__ import annotations

import sqlite3

import pytest

from core.backup_service import BackupService
from core.book_service import BookService
from core.database import Database
from core.errors import BackupError, DatabaseIntegrityError


def _database(tmp_path):
    database = Database(tmp_path / "live.db")
    database.open()
    database.migrate()
    return database


def test_managed_backup_is_verified_listed_and_private(tmp_path) -> None:
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
        path = service.managed_path(str(created["name"]))
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        database.close()


def test_restore_replaces_live_state_and_preserves_pre_restore_safety_snapshot(
    tmp_path,
) -> None:
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
        assert result["safetyBackup"] == plan.safety_backup_name
        assert books.current_book().name == "Original"
        database.integrity_check()

        safety_db = Database(service.managed_path(plan.safety_backup_name))
        try:
            safety_db.open()
            assert BookService(safety_db).current_book().name == "Changed"
            safety_db.integrity_check()
        finally:
            safety_db.close()
    finally:
        database.close()


def test_finalize_restore_rolls_back_if_new_live_database_cannot_reopen(
    tmp_path, monkeypatch
) -> None:
    database = _database(tmp_path)
    try:
        books = BookService(database)
        book = books.create_personal_book(
            user_name="User", book_name="Original", currency_code="EUR"
        )
        service = BackupService(database, tmp_path / "backups")
        backup = service.create_managed_backup()
        with database.transaction() as tx:
            tx.execute("UPDATE books SET name='Keep me' WHERE id=?", (book.id,))
        plan = service.prepare_restore(service.managed_path(str(backup["name"])))

        original_open = database.open
        calls = 0

        def fail_first_reopen():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise DatabaseIntegrityError("simulated reopen failure")
            return original_open()

        monkeypatch.setattr(database, "open", fail_first_reopen)
        with pytest.raises(BackupError, match="previous database was restored"):
            service.finalize_restore(plan)

        assert BookService(database).current_book().name == "Keep me"
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


def test_prepare_restore_rejects_corrupt_file_before_safety_snapshot(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        service = BackupService(database, tmp_path / "backups")
        corrupt = tmp_path / "corrupt.sqlite3"
        corrupt.write_bytes(b"not-a-sqlite-database")

        with pytest.raises(BackupError):
            service.prepare_restore(corrupt)
        assert service.list_backups() == []
        database.integrity_check()
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
