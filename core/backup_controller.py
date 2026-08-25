from __future__ import annotations

from pathlib import Path

from core.backup_service import BackupService, RestorePlan


class BackupController:
    """Coordinates backup/restore workflows without owning persistence semantics."""

    def __init__(self, service: BackupService) -> None:
        self._service = service

    def list_backups(self) -> list[dict[str, object]]:
        return self._service.list_backups()

    def create_backup(self) -> dict[str, object]:
        return self._service.create_managed_backup()

    def export_backup(self, destination: Path) -> dict[str, object]:
        return self._service.export_backup(destination)

    def prepare_managed_restore(self, name: str) -> RestorePlan:
        return self._service.prepare_restore(self._service.managed_path(name))

    def prepare_external_restore(self, source: Path) -> RestorePlan:
        return self._service.prepare_restore(source)

    def cancel_restore(self, plan: RestorePlan) -> None:
        self._service.cancel_restore(plan)

    def finalize_restore(self, plan: RestorePlan) -> dict[str, object]:
        return self._service.finalize_restore(plan)
