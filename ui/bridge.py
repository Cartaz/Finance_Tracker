from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from core.app_controller import AppController
from core.backup_controller import BackupController
from core.backup_service import RestorePlan
from core.errors import BackupError, FinanceTrackerError
from ui.background_task import BackgroundTask

log = logging.getLogger(__name__)


class Bridge(QObject):
    backupTaskFinished = Signal("QVariant")
    maintenanceChanged = Signal(bool)

    def __init__(
        self,
        controller: AppController,
        backup_controller: BackupController | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._backup = backup_controller
        self._thread_pool = QThreadPool.globalInstance()
        self._tasks: dict[str, BackgroundTask] = {}
        self._task_operations: dict[str, str] = {}
        self._maintenance = False
        self._export_picker: Callable[[], str | None] | None = None
        self._restore_picker: Callable[[], str | None] | None = None

    def set_file_dialogs(
        self,
        *,
        export_picker: Callable[[], str | None],
        restore_picker: Callable[[], str | None],
    ) -> None:
        self._export_picker = export_picker
        self._restore_picker = restore_picker

    def _call(self, function, *args):
        if self._maintenance:
            return self._controller.error_payload(
                BackupError("database restore is in progress")
            )
        try:
            return {"ok": True, "data": function(*args)}
        except (FinanceTrackerError, TypeError, ValueError) as exc:
            return self._controller.error_payload(exc)

    def _require_backup(self) -> BackupController:
        if self._backup is None:
            raise BackupError("backup service is unavailable")
        return self._backup

    def _start_background(self, operation: str, function, *, maintenance: bool = False):
        if maintenance and self._maintenance:
            return self._controller.error_payload(
                BackupError("database restore is already in progress")
            )
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
        return {"ok": True, "data": {"taskId": task_id, "operation": operation}}

    @Slot(str, object)
    def _on_task_succeeded(self, task_id: str, result: object) -> None:
        operation = self._task_operations.pop(task_id, "UNKNOWN")
        self._tasks.pop(task_id, None)
        if operation.startswith("RESTORE_"):
            try:
                if not isinstance(result, RestorePlan):
                    raise BackupError("restore preparation returned an invalid plan")
                data = self._require_backup().finalize_restore(result)
            except Exception as exc:
                self._finish_restore_failure(task_id, operation, exc)
                return
            self._maintenance = False
            self.maintenanceChanged.emit(False)
            self.backupTaskFinished.emit(
                {
                    "taskId": task_id,
                    "operation": operation,
                    "ok": True,
                    "data": data,
                    "requiresReload": True,
                }
            )
            return
        self.backupTaskFinished.emit(
            {"taskId": task_id, "operation": operation, "ok": True, "data": result}
        )

    @Slot(str, object)
    def _on_task_failed(self, task_id: str, exc: object) -> None:
        operation = self._task_operations.pop(task_id, "UNKNOWN")
        self._tasks.pop(task_id, None)
        if operation.startswith("RESTORE_"):
            self._finish_restore_failure(task_id, operation, exc)
            return
        self.backupTaskFinished.emit(
            {
                "taskId": task_id,
                "operation": operation,
                **self._background_error(exc),
            }
        )

    def _finish_restore_failure(self, task_id: str, operation: str, exc: object) -> None:
        self._maintenance = False
        self.maintenanceChanged.emit(False)
        self.backupTaskFinished.emit(
            {
                "taskId": task_id,
                "operation": operation,
                **self._background_error(exc),
            }
        )

    def _background_error(self, exc: object) -> dict[str, object]:
        if isinstance(exc, (FinanceTrackerError, TypeError, ValueError)):
            payload = self._controller.error_payload(exc)
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

    @Slot(result="QVariant")
    def listBackups(self):
        return self._call(self._require_backup().list_backups)

    @Slot(result="QVariant")
    def startManagedBackup(self):
        try:
            backup = self._require_backup()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._start_background("BACKUP_CREATE", backup.create_backup)

    @Slot(result="QVariant")
    def startExportBackup(self):
        try:
            backup = self._require_backup()
            if self._export_picker is None:
                raise BackupError("native export dialog is unavailable")
            selected = self._export_picker()
            if not selected:
                return {"ok": True, "data": {"cancelled": True}}
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._start_background(
            "BACKUP_EXPORT",
            lambda: backup.export_backup(Path(selected)),
        )

    @Slot(str, result="QVariant")
    def startManagedRestore(self, name: str):
        try:
            backup = self._require_backup()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._start_background(
            "RESTORE_MANAGED",
            lambda: backup.prepare_managed_restore(name),
            maintenance=True,
        )

    @Slot(result="QVariant")
    def startExternalRestore(self):
        try:
            backup = self._require_backup()
            if self._restore_picker is None:
                raise BackupError("native restore dialog is unavailable")
            selected = self._restore_picker()
            if not selected:
                return {"ok": True, "data": {"cancelled": True}}
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._start_background(
            "RESTORE_EXTERNAL",
            lambda: backup.prepare_external_restore(Path(selected)),
            maintenance=True,
        )

    @Slot(result="QVariant")
    def getInitialState(self):
        return self._call(self._controller.initial_state)

    @Slot(result="QVariant")
    def getSnapshot(self):
        return self._call(self._controller.snapshot)

    @Slot("QVariant", result="QVariant")
    def getDashboard(self, payload):
        return self._call(self._controller.dashboard, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def getForecast(self, payload):
        return self._call(self._controller.forecast, dict(payload or {}))

    @Slot(result="QVariant")
    def getLoanCapabilities(self):
        return self._call(self._controller.loan_capabilities)

    @Slot("QVariant", result="QVariant")
    def createLoan(self, payload):
        return self._call(self._controller.create_loan, dict(payload or {}))

    @Slot(result="QVariant")
    def listLoans(self):
        return self._call(self._controller.list_loans)

    @Slot("QVariant", result="QVariant")
    def getLoanPlan(self, payload):
        return self._call(self._controller.loan_plan, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def getLoanPayments(self, payload):
        return self._call(self._controller.loan_payments, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def getLoanRateRevisions(self, payload):
        return self._call(self._controller.loan_rate_revisions, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def setLoanVariableRate(self, payload):
        return self._call(self._controller.set_loan_variable_rate, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def postNextLoanPayment(self, payload):
        return self._call(self._controller.post_next_loan_payment, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def postCustomLoanPayment(self, payload):
        return self._call(self._controller.post_custom_loan_payment, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def getAccountHistory(self, payload):
        return self._call(self._controller.account_history, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def setBudget(self, payload):
        return self._call(self._controller.set_budget, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def getBudgetStatus(self, payload):
        return self._call(self._controller.budget_status, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def deleteBudget(self, payload):
        return self._call(self._controller.delete_budget, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def setFxRate(self, payload):
        return self._call(self._controller.set_fx_rate, dict(payload or {}))

    @Slot(result="QVariant")
    def listFxRates(self):
        return self._call(self._controller.list_fx_rates)

    @Slot("QVariant", result="QVariant")
    def importCsv(self, payload):
        return self._call(self._controller.import_csv, dict(payload or {}))

    @Slot(result="QVariant")
    def listImportBatches(self):
        return self._call(self._controller.list_import_batches)

    @Slot("QVariant", result="QVariant")
    def getImportBatchRows(self, payload):
        return self._call(self._controller.import_batch_rows, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def linkImportRow(self, payload):
        return self._call(self._controller.link_import_row, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def postImportRow(self, payload):
        return self._call(self._controller.post_import_row, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def ignoreImportRow(self, payload):
        return self._call(self._controller.ignore_import_row, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def createScheduledTransaction(self, payload):
        return self._call(
            self._controller.create_scheduled_transaction, dict(payload or {})
        )

    @Slot(result="QVariant")
    def listScheduledTransactions(self):
        return self._call(self._controller.list_scheduled_transactions)

    @Slot("QVariant", result="QVariant")
    def setScheduledActive(self, payload):
        return self._call(self._controller.set_scheduled_active, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def postDueScheduled(self, payload):
        return self._call(self._controller.post_due_scheduled, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def setup(self, payload):
        return self._call(self._controller.setup, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def createAccount(self, payload):
        return self._call(self._controller.create_account, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def createExpense(self, payload):
        return self._call(self._controller.create_expense, dict(payload or {}))

    @Slot(str, result="QVariant")
    def suggestPayees(self, query: str):
        return self._call(self._controller.suggest_payees, query)

    @Slot(str, result="QVariant")
    def createPayee(self, name: str):
        return self._call(self._controller.create_payee, name)
