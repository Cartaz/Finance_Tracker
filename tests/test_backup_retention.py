from __future__ import annotations

from core.backup_service import MANAGED_BACKUP_RETENTION, BackupService
from core.database import Database


def test_only_the_newest_managed_backups_are_kept(tmp_path) -> None:
    database = Database(tmp_path / "live.db")
    database.migrate()
    service = BackupService(database, tmp_path / "backups")
    # Exports may live in the same folder and even share the prefix.
    exported = tmp_path / "backups" / "finance-tracker-2026-01-01.sqlite3"
    try:
        service.export_backup(exported)
        names = [service.create_managed_backup()["name"] for _ in range(MANAGED_BACKUP_RETENTION + 2)]
        listed = {item["name"] for item in service.list_backups()}
        # The export stays listed (and restorable); only managed stamps are pruned.
        assert listed == set(names[-MANAGED_BACKUP_RETENTION:]) | {exported.name}
        assert exported.exists()
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
