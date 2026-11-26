from __future__ import annotations

from core.backup_service import MANAGED_BACKUP_RETENTION, BackupService
from core.database import Database


def test_only_the_newest_managed_backups_are_kept(tmp_path) -> None:
    database = Database(tmp_path / "live.db")
    database.migrate()
    service = BackupService(database, tmp_path / "backups")
    exported = tmp_path / "backups" / "my-export.sqlite3"
    try:
        service.export_backup(exported)
        names = [service.create_managed_backup()["name"] for _ in range(MANAGED_BACKUP_RETENTION + 2)]
        kept = {item["name"] for item in service.list_backups()}
        assert kept == set(names[-MANAGED_BACKUP_RETENTION:])
        assert exported.exists(), "exports are never pruned"
    finally:
        database.close()


def test_restoring_the_oldest_backup_is_not_pruned_away(tmp_path) -> None:
    database = Database(tmp_path / "live.db")
    database.migrate()
    service = BackupService(database, tmp_path / "backups")
    try:
        names = [service.create_managed_backup()["name"] for _ in range(MANAGED_BACKUP_RETENTION)]
        plan = service.prepare_restore(service.managed_path(names[0]))
        result = service.finalize_restore(plan)
        assert result["restoredFrom"] == names[0]
    finally:
        database.close()
