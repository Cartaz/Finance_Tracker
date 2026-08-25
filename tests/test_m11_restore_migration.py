from __future__ import annotations

import sqlite3

from core.backup_service import BackupService
from core.database import Database
from core.migration_catalog import apply_migrations


def test_restore_preparation_migrates_older_backup_only_in_staging(tmp_path) -> None:
    live = Database(tmp_path / "live.db")
    live.open()
    live.migrate()
    try:
        source = tmp_path / "v8-backup.sqlite3"
        conn = sqlite3.connect(source, autocommit=False)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            apply_migrations(conn, current_version=0, target_version=8)
            conn.commit()
            assert conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0] == 8
        finally:
            conn.close()

        service = BackupService(live, tmp_path / "backups")
        plan = service.prepare_restore(source)
        try:
            assert plan.source_schema_version == 8

            source_check = sqlite3.connect(source)
            try:
                assert source_check.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0] == 8
            finally:
                source_check.close()

            staged_check = sqlite3.connect(plan.staged_database)
            try:
                assert staged_check.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0] == 9
                columns = {
                    row[1]
                    for row in staged_check.execute("PRAGMA table_info(loans)").fetchall()
                }
                assert {"rate_type", "amortization_type", "recast_strategy"} <= columns
            finally:
                staged_check.close()
        finally:
            service.cancel_restore(plan)
    finally:
        live.close()
