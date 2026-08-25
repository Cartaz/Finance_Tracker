from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from core.backup_controller import BackupController
from core.backup_service import RestorePlan
from core.errors import BackupError, FinanceTrackerError
from ui.background_task import BackgroundTask

log = logging.getLogger(__name__)


class BackupTaskManager(QObject):
    """Owns Qt background-task and maintenance lifecycle for backup/restore."""

    finished = Signal("QVariant")
    maintenanceChanged = Signal(bool)

    def __init__(
        self,
        controller: BackupController,
        error_payload: Callable[[Exception], dict[str, object]],
    ) -> None:
        super().__init__()
        self._controller = controller
        self._error_payload = error_payload
        self._thread_pool = QThreadPool.globalInstance()
        self._tasks: dict[str, BackgroundTask] = {}
        self._task_operations: dict[str, str] = {}
        self._maintenance = False
        self._export_picker: Callable[[], str | None] | None = None
        self._restore_picker: Callable[[], str | None] | None = None

    @property
    def maintenance(self) -> bool:
        return self._maintenance

    def set_file_dialogs(
        self,
        *,
        export_picker: Callable[[], str | None],
        restore_picker: Callable[[], str | None],
    ) -> None:
        self._export_picker = export_picker
        self._restore_picker = restore_picker

    def list_backups(self) -> list[dict[str, object]]:
        return self._controller.list_backups()

    def start_managed_backup(self) -> dict[str, object]:
        return self._start_background("BACKUP_CREATE", self._controller.create_backup)

    def start_export_backup(self) -> dict[str, object]:
        if self._export_picker is None:
            raise BackupError("native export dialog is unavailable")
        selected = self._export_picker()
        if not selected:
            return {"cancelled": True}
        return self._start_background(
            "BACKUP_EXPORT",
            lambda: self._controller.export_backup(Path(selected)),
        )

    def start_managed_restore(self, name: str) -> dict[str, object]:
        return self._start_background(
            "RESTORE_MANAGED",
            lambda: self._controller.prepare_managed_restore(name),
            maintenance=True,
        )

    def start_external_restore(self) -> dict[str, object]:
        if self._restore_picker is None:
            raise BackupError("native restore dialog is unavailable")
        selected = self._restore_picker()
        if not selected:
            return {"cancelled": True}
        return self._start_background(
            "RESTORE_EXTERNAL",
            lambda: self._controller.prepare_external_restore(Path(selected)),
            maintenance=True,
        )

    def _start_background(
        self,
        operation: str,
        function: Callable[[], object],
        *,
        maintenance: bool = False,
    ) -> dict[str, object]:
        if self._tasks or self._maintenance:
            raise BackupError("another backup or restore operation is already in progress")
        task_id = uuid4().hex
        worker = BackgroundTask(task_id, function)
        worker.signals.succeeded.connect(self._on_task_succeeded)
        worker.signals.failed.connect(self._on_task_failed)
        self._tasks[task_id] = worker
        self._task_operations[task_id] = operation
        if maintenance:
            self._maintenance = True
            self.maintenanceChanged.emit(True)
        self._thread_pool.start(worker)
        return {"taskId": task_id, "operation": operation}

    @Slot(str, object)
    def _on_task_succeeded(self, task_id: str, result: object) -> None:
        operation = self._task_operations.pop(task_id, "UNKNOWN")
        self._tasks.pop(task_id, None)
        if operation.startswith("RESTORE_"):
            try:
                if not isinstance(result, RestorePlan):
                    raise BackupError("restore preparation returned an invalid plan")
                data = self._controller.finalize_restore(result)
            except BaseException as exc:
                self._finish_restore_failure(task_id, operation, exc)
                return
            self._set_maintenance(False)
            self.finished.emit(
                {
                    "taskId": task_id,
                    "operation": operation,
                    "ok": True,
                    "data": data,
                    "requiresReload": True,
                }
            )
            return
        self.finished.emit(
            {"taskId": task_id, "operation": operation, "ok": True, "data": result}
        )

    @Slot(str, object)
    def _on_task_failed(self, task_id: str, exc: object) -> None:
        operation = self._task_operations.pop(task_id, "UNKNOWN")
        self._tasks.pop(task_id, None)
        if operation.startswith("RESTORE_"):
            self._finish_restore_failure(task_id, operation, exc)
            return
        self.finished.emit(
            {
                "taskId": task_id,
                "operation": operation,
                **self._background_error(exc),
            }
        )

    def _finish_restore_failure(self, task_id: str, operation: str, exc: object) -> None:
        self._set_maintenance(False)
        self.finished.emit(
            {
                "taskId": task_id,
                "operation": operation,
                **self._background_error(exc),
            }
        )

    def _set_maintenance(self, active: bool) -> None:
        if self._maintenance == active:
            return
        self._maintenance = active
        self.maintenanceChanged.emit(active)

    def _background_error(self, exc: object) -> dict[str, object]:
        if isinstance(exc, (FinanceTrackerError, TypeError, ValueError)):
            payload = self._error_payload(exc)
            return {"ok": False, "error": payload["error"]}
        if isinstance(exc, BaseException):
            log.error(
                "background backup task failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        return {
            "ok": False,
            "error": {
                "code": "UnexpectedBackupError",
                "message": "Unexpected backup/restore failure; see logs for details",
            },
        }
