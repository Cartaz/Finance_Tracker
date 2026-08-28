from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot

from core.app_controller import AppController
from core.errors import BackupError, FinanceTrackerError
from ui.backup_task_manager import BackupTaskManager

log = logging.getLogger(__name__)


class Bridge(QObject):
    backupTaskFinished = Signal("QVariant")
    maintenanceChanged = Signal(bool)

    def __init__(
        self,
        controller: AppController,
        backup_tasks: BackupTaskManager | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._backup_tasks = backup_tasks
        if self._backup_tasks is not None:
            self._backup_tasks.finished.connect(self.backupTaskFinished.emit)
            self._backup_tasks.maintenanceChanged.connect(self.maintenanceChanged.emit)

    def set_file_dialogs(
        self,
        *,
        export_picker: Callable[[], str | None],
        restore_picker: Callable[[], str | None],
    ) -> None:
        if self._backup_tasks is not None:
            self._backup_tasks.set_file_dialogs(
                export_picker=export_picker,
                restore_picker=restore_picker,
            )

    def _call(self, function, *args):
        if self._backup_tasks is not None and self._backup_tasks.maintenance:
            return self._controller.error_payload(
                BackupError("database restore is in progress")
            )
        return self._invoke(function, *args)

    def _backup_call(self, function, *args):
        return self._invoke(function, *args)

    def _invoke(self, function, *args):
        try:
            return {"ok": True, "data": function(*args)}
        except (FinanceTrackerError, TypeError, ValueError) as exc:
            return self._controller.error_payload(exc)
        except Exception as exc:
            log.error(
                "unexpected QWebChannel bridge failure",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return {
                "ok": False,
                "error": {
                    "code": "UnexpectedApplicationError",
                    "message": "Unexpected application failure; see logs for details",
                },
            }

    def _require_backup_tasks(self) -> BackupTaskManager:
        if self._backup_tasks is None:
            raise BackupError("backup service is unavailable")
        return self._backup_tasks

    @Slot(result="QVariant")
    def listBackups(self):
        try:
            manager = self._require_backup_tasks()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._call(manager.list_backups)

    @Slot(result="QVariant")
    def startManagedBackup(self):
        try:
            manager = self._require_backup_tasks()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._backup_call(manager.start_managed_backup)

    @Slot(result="QVariant")
    def startExportBackup(self):
        try:
            manager = self._require_backup_tasks()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._backup_call(manager.start_export_backup)

    @Slot(str, result="QVariant")
    def startManagedRestore(self, name: str):
        try:
            manager = self._require_backup_tasks()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._backup_call(manager.start_managed_restore, name)

    @Slot(result="QVariant")
    def startExternalRestore(self):
        try:
            manager = self._require_backup_tasks()
        except FinanceTrackerError as exc:
            return self._controller.error_payload(exc)
        return self._backup_call(manager.start_external_restore)

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

    @Slot("QVariant", result="QVariant")
    def createIncome(self, payload):
        return self._call(self._controller.create_income, dict(payload or {}))

    @Slot("QVariant", result="QVariant")
    def createTransfer(self, payload):
        return self._call(self._controller.create_transfer, dict(payload or {}))

    @Slot(str, result="QVariant")
    def suggestPayees(self, query: str):
        return self._call(self._controller.suggest_payees, query)

    @Slot(str, result="QVariant")
    def createPayee(self, name: str):
        return self._call(self._controller.create_payee, name)
