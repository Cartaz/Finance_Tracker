from __future__ import annotations

from pathlib import Path
from threading import Lock

from core.backup_service import BackupService, RestorePlan
from core.errors import BackupError


class BackupController:
    """Coordinates backup/restore workflows without owning persistence semantics."""

    def __init__(self, service: BackupService) -> None:
        self._service = service
        self._operation_lock = Lock()
        self._operation_active = False
        self._restore_in_progress = False

    def list_backups(self) -> list[dict[str, object]]:
        return self._service.list_backups()

    def create_backup(self) -> dict[str, object]:
        self._begin_operation()
        try:
            return self._service.create_managed_backup()
        finally:
            self._end_operation()

    def export_backup(self, destination: Path) -> dict[str, object]:
        self._begin_operation()
        try:
            return self._service.export_backup(destination)
        finally:
            self._end_operation()

    def prepare_managed_restore(self, name: str) -> RestorePlan:
        self._begin_restore()
        try:
            plan = self._service.prepare_restore(self._service.managed_path(name))
        except Exception:
            self._abort_restore_state()
            raise
        self._end_operation(keep_restore=True)
        return plan

    def prepare_external_restore(self, source: Path) -> RestorePlan:
        self._begin_restore()
        try:
            plan = self._service.prepare_restore(source)
        except Exception:
            self._abort_restore_state()
            raise
        self._end_operation(keep_restore=True)
        return plan

    def cancel_restore(self, plan: RestorePlan) -> None:
        try:
            self._service.cancel_restore(plan)
        finally:
            self._abort_restore_state()

    def finalize_restore(self, plan: RestorePlan) -> dict[str, object]:
        with self._operation_lock:
            if not self._restore_in_progress:
                raise BackupError("no prepared restore is in progress")
            if self._operation_active:
                raise BackupError("another backup or restore operation is already in progress")
            self._operation_active = True
        try:
            return self._service.finalize_restore(plan)
        finally:
            self._abort_restore_state()

    def _begin_operation(self) -> None:
        with self._operation_lock:
            if self._operation_active or self._restore_in_progress:
                raise BackupError("another backup or restore operation is already in progress")
            self._operation_active = True

    def _begin_restore(self) -> None:
        with self._operation_lock:
            if self._operation_active or self._restore_in_progress:
                raise BackupError("another backup or restore operation is already in progress")
            self._operation_active = True
            self._restore_in_progress = True

    def _end_operation(self, *, keep_restore: bool = False) -> None:
        with self._operation_lock:
            self._operation_active = False
            if not keep_restore:
                self._restore_in_progress = False

    def _abort_restore_state(self) -> None:
        with self._operation_lock:
            self._operation_active = False
            self._restore_in_progress = False
