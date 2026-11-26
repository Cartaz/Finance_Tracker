from __future__ import annotations

from pathlib import Path

import pytest

from core.backup_service import RestorePlan
from core.errors import BackupError, FinanceTrackerError
from ui.backup_task_manager import BackupTaskManager


class _ImmediatePool:
    def __init__(self) -> None:
        self.workers = []

    def start(self, worker) -> None:
        self.workers.append(worker)


class _BackupController:
    def __init__(self) -> None:
        self.finalized = 0

    def list_backups(self):
        return []

    def create_backup(self):
        return {"name": "one.sqlite3"}

    def export_backup(self, destination: Path):
        return {"name": destination.name}

    def prepare_managed_restore(self, name: str) -> RestorePlan:
        return RestorePlan(
            source=Path(name),
            staged_database=Path("staged.sqlite3"),
            source_schema_version=9,
            safety_backup_name="safety.sqlite3",
        )

    def prepare_external_restore(self, source: Path) -> RestorePlan:
        return self.prepare_managed_restore(source.name)

    def finalize_restore(self, plan: RestorePlan):
        self.finalized += 1
        return {
            "restoredFrom": plan.source.name,
            "safetyBackup": plan.safety_backup_name,
        }


def _error_payload(exc: Exception) -> dict[str, object]:
    if isinstance(exc, FinanceTrackerError):
        return {
            "ok": False,
            "error": {"code": type(exc).__name__, "message": str(exc)},
        }
    raise exc


def test_manager_serializes_background_jobs_and_tracks_owned_activity() -> None:
    manager = BackupTaskManager(_BackupController(), _error_payload)  # type: ignore[arg-type]
    pool = _ImmediatePool()
    manager._thread_pool = pool  # type: ignore[assignment]

    assert manager.active is False
    first = manager.start_managed_backup()
    assert first["operation"] == "BACKUP_CREATE"
    assert manager.active is True
    with pytest.raises(BackupError):
        manager.start_managed_backup()

    pool.workers.pop().run()
    assert manager.active is False
    second = manager.start_managed_backup()
    assert second["operation"] == "BACKUP_CREATE"
    assert manager.active is True


def test_restore_emits_maintenance_until_finalize_and_requires_reload() -> None:
    controller = _BackupController()
    manager = BackupTaskManager(controller, _error_payload)  # type: ignore[arg-type]
    pool = _ImmediatePool()
    manager._thread_pool = pool  # type: ignore[assignment]
    maintenance: list[bool] = []
    results: list[dict[str, object]] = []
    manager.maintenanceChanged.connect(maintenance.append)
    manager.finished.connect(results.append)

    started = manager.start_managed_restore("source.sqlite3")
    assert started["operation"] == "RESTORE_MANAGED"
    assert manager.maintenance is True
    assert manager.active is True
    assert maintenance == [True]

    pool.workers.pop().run()

    assert controller.finalized == 1
    assert manager.maintenance is False
    assert manager.active is False
    assert maintenance == [True, False]
    assert results[-1]["ok"] is True
    assert results[-1]["requiresReload"] is True
    assert results[-1]["data"]["safetyBackup"] == "safety.sqlite3"
