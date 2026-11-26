from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from core.backup_controller import BackupController
from core.backup_service import RestorePlan
from core.errors import BackupError


class _BlockingBackupService:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.created = 0

    def list_backups(self):
        return []

    def create_managed_backup(self):
        self.created += 1
        return {"name": "backup.sqlite3"}

    def export_backup(self, destination: Path):
        return {"name": destination.name}

    def managed_path(self, name: str) -> Path:
        return Path(name)

    def prepare_restore(self, source: Path) -> RestorePlan:
        self.started.set()
        assert self.release.wait(timeout=2)
        return RestorePlan(
            source=source,
            staged_database=Path("staged.sqlite3"),
            source_schema_version=9,
            safety_backup_name="safety.sqlite3",
        )

    def cancel_restore(self, plan: RestorePlan) -> None:
        return None

    def finalize_restore(self, plan: RestorePlan):
        return {"restoredFrom": plan.source.name}


def test_backup_controller_blocks_parallel_operations_and_reserves_restore() -> None:
    service = _BlockingBackupService()
    controller = BackupController(service)  # type: ignore[arg-type]
    result: list[RestorePlan] = []

    thread = Thread(
        target=lambda: result.append(controller.prepare_external_restore(Path("source.sqlite3")))
    )
    thread.start()
    assert service.started.wait(timeout=2)

    with pytest.raises(BackupError):
        controller.create_backup()

    service.release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(result) == 1

    with pytest.raises(BackupError):
        controller.create_backup()

    controller.cancel_restore(result[0])
    assert controller.create_backup()["name"] == "backup.sqlite3"
