from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.app_controller import AppController
from core.errors import BackupError, FinanceTrackerError, ValidationError
from ui.backup_task_manager import BackupTaskManager
from ui.formatting import format_money, format_percent_bps

log = logging.getLogger(__name__)


def _plain_payload(payload: object) -> object:
    """Convert a QML object argument (QJSValue) into plain Python data."""
    to_variant = getattr(payload, "toVariant", None)
    if callable(to_variant):
        return to_variant()
    return payload


class Bridge(QObject):
    """The single backend object exposed to QML.

    It validates transport shape, converts QML values and delegates. Business
    rules, SQL and financial arithmetic stay in core services.
    """

    backupTaskFinished = Signal("QVariant")
    maintenanceChanged = Signal(bool)
    busyChanged = Signal()

    def __init__(
        self,
        controller: AppController,
        backup_tasks: BackupTaskManager | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._backup_tasks = backup_tasks
        # Minor-unit digits are static metadata. Caching them keeps money
        # formatting from opening SQLite read snapshots on the GUI connection,
        # in particular while a background worker owns the database.
        self._currency_digits: dict[str, int] = {}
        if self._backup_tasks is not None:
            self._backup_tasks.finished.connect(self._on_task_finished)
            self._backup_tasks.maintenanceChanged.connect(self._on_maintenance_changed)

    def set_file_dialogs(
        self,
        *,
        export_picker: Callable[[], str | None],
        restore_picker: Callable[[], str | None],
        csv_picker: Callable[[], str | None] | None = None,
    ) -> None:
        if self._backup_tasks is not None:
            self._backup_tasks.set_file_dialogs(
                export_picker=export_picker,
                restore_picker=restore_picker,
                csv_picker=csv_picker,
            )

    @Property(bool, notify=maintenanceChanged)
    def maintenance(self) -> bool:
        return self._backup_tasks is not None and self._backup_tasks.maintenance

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        """Owned persistence work is active and the window must not close."""
        return self._backup_tasks is not None and self._backup_tasks.active

    def _on_task_finished(self, result: object) -> None:
        self.busyChanged.emit()
        self.backupTaskFinished.emit(result)

    def _on_maintenance_changed(self, active: bool) -> None:
        self.busyChanged.emit()
        self.maintenanceChanged.emit(active)

    def _call(self, function, *args):
        if self._backup_tasks is not None and self._backup_tasks.maintenance:
            return self._controller.error_payload(
                BackupError("database maintenance operation is in progress")
            )
        return self._invoke(function, *args)

    def _task_call(self, function, *args):
        result = self._invoke(function, *args)
        self.busyChanged.emit()
        return result

    def _payload_call(self, function, payload):
        def validated_call():
            data = _plain_payload(payload)
            if not isinstance(data, dict):
                raise ValidationError("payload must be an object")
            return function(data)

        return self._call(validated_call)

    def _invoke(self, function, *args):
        try:
            return {"ok": True, "data": function(*args)}
        except (FinanceTrackerError, TypeError, ValueError) as exc:
            return self._controller.error_payload(exc)
        except Exception as exc:
            log.error(
                "unexpected backend bridge failure",
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

    # Presentation formatting: exact integers never become JavaScript numbers.

    @Slot("QVariant", str, result=str)
    def formatMoney(self, minor, currency: str) -> str:
        if minor is None or minor == "":
            return format_money(None, currency, 0)
        if not currency:
            return "—"
        try:
            return format_money(minor, currency, self._digits_for(currency))
        except (FinanceTrackerError, TypeError, ValueError):
            log.warning("cannot format money value for currency %r", currency)
            return "—"

    def _digits_for(self, currency: str) -> int:
        digits = self._currency_digits.get(currency)
        if digits is None:
            if self.maintenance:
                raise BackupError("currency metadata unavailable during maintenance")
            digits = self._controller.currency_digits(currency)
            self._currency_digits[currency] = digits
        return digits

    def _remember_currencies(self, result: dict) -> dict:
        if result.get("ok"):
            for item in result["data"].get("currencies", []):
                self._currency_digits[str(item["code"])] = int(item["minorUnitDigits"])
        return result

    @Slot("QVariant", result=str)
    def formatPercentBps(self, bps) -> str:
        try:
            return format_percent_bps(bps)
        except (TypeError, ValueError):
            return "—"

    # Backup, restore and CSV staging run as owned background tasks.

    @Slot(result="QVariant")
    def listBackups(self):
        return self._call(lambda: self._require_backup_tasks().list_backups())

    @Slot(result="QVariant")
    def startManagedBackup(self):
        return self._task_call(
            lambda: self._require_backup_tasks().start_managed_backup()
        )

    @Slot(result="QVariant")
    def startExportBackup(self):
        return self._task_call(
            lambda: self._require_backup_tasks().start_export_backup()
        )

    @Slot(str, result="QVariant")
    def startManagedRestore(self, name: str):
        return self._task_call(
            lambda: self._require_backup_tasks().start_managed_restore(name)
        )

    @Slot(result="QVariant")
    def startExternalRestore(self):
        return self._task_call(
            lambda: self._require_backup_tasks().start_external_restore()
        )

    @Slot("QVariant", result="QVariant")
    def startCsvImport(self, payload):
        def start(data):
            manager = self._require_backup_tasks()
            if manager.active:
                raise BackupError(
                    "another persistence operation is already in progress"
                )
            return manager.start_csv_import(self._controller.csv_import_task(data))

        result = self._payload_call(start, payload)
        self.busyChanged.emit()
        return result

    # Application state and domain workflows.

    @Slot(result="QVariant")
    def getInitialState(self):
        return self._remember_currencies(self._call(self._controller.initial_state))

    @Slot(result="QVariant")
    def getSnapshot(self):
        return self._call(self._controller.snapshot)

    @Slot("QVariant", result="QVariant")
    def getDashboard(self, payload):
        return self._payload_call(self._controller.dashboard, payload)

    @Slot("QVariant", result="QVariant")
    def getForecast(self, payload):
        return self._payload_call(self._controller.forecast, payload)

    @Slot(result="QVariant")
    def getLoanCapabilities(self):
        return self._call(self._controller.loan_capabilities)

    @Slot("QVariant", result="QVariant")
    def createLoan(self, payload):
        return self._payload_call(self._controller.create_loan, payload)

    @Slot(result="QVariant")
    def listLoans(self):
        return self._call(self._controller.list_loans)

    @Slot("QVariant", result="QVariant")
    def getLoanPlan(self, payload):
        return self._payload_call(self._controller.loan_plan, payload)

    @Slot("QVariant", result="QVariant")
    def getLoanPayments(self, payload):
        return self._payload_call(self._controller.loan_payments, payload)

    @Slot("QVariant", result="QVariant")
    def getLoanRateRevisions(self, payload):
        return self._payload_call(self._controller.loan_rate_revisions, payload)

    @Slot("QVariant", result="QVariant")
    def setLoanVariableRate(self, payload):
        return self._payload_call(self._controller.set_loan_variable_rate, payload)

    @Slot("QVariant", result="QVariant")
    def postNextLoanPayment(self, payload):
        return self._payload_call(self._controller.post_next_loan_payment, payload)

    @Slot("QVariant", result="QVariant")
    def postCustomLoanPayment(self, payload):
        return self._payload_call(self._controller.post_custom_loan_payment, payload)

    @Slot("QVariant", result="QVariant")
    def getAccountHistory(self, payload):
        return self._payload_call(self._controller.account_history, payload)

    @Slot("QVariant", result="QVariant")
    def setBudget(self, payload):
        return self._payload_call(self._controller.set_budget, payload)

    @Slot("QVariant", result="QVariant")
    def getBudgetStatus(self, payload):
        return self._payload_call(self._controller.budget_status, payload)

    @Slot("QVariant", result="QVariant")
    def deleteBudget(self, payload):
        return self._payload_call(self._controller.delete_budget, payload)

    @Slot("QVariant", result="QVariant")
    def setFxRate(self, payload):
        return self._payload_call(self._controller.set_fx_rate, payload)

    @Slot(result="QVariant")
    def listFxRates(self):
        return self._call(self._controller.list_fx_rates)

    @Slot(result="QVariant")
    def listImportBatches(self):
        return self._call(self._controller.list_import_batches)

    @Slot("QVariant", result="QVariant")
    def getImportBatchRows(self, payload):
        return self._payload_call(self._controller.import_batch_rows, payload)

    @Slot("QVariant", result="QVariant")
    def linkImportRow(self, payload):
        return self._payload_call(self._controller.link_import_row, payload)

    @Slot("QVariant", result="QVariant")
    def postImportRow(self, payload):
        return self._payload_call(self._controller.post_import_row, payload)

    @Slot("QVariant", result="QVariant")
    def ignoreImportRow(self, payload):
        return self._payload_call(self._controller.ignore_import_row, payload)

    @Slot("QVariant", result="QVariant")
    def createScheduledTransaction(self, payload):
        return self._payload_call(
            self._controller.create_scheduled_transaction, payload
        )

    @Slot(result="QVariant")
    def listScheduledTransactions(self):
        return self._call(self._controller.list_scheduled_transactions)

    @Slot("QVariant", result="QVariant")
    def setScheduledActive(self, payload):
        return self._payload_call(self._controller.set_scheduled_active, payload)

    @Slot("QVariant", result="QVariant")
    def postDueScheduled(self, payload):
        return self._payload_call(self._controller.post_due_scheduled, payload)

    @Slot("QVariant", result="QVariant")
    def setup(self, payload):
        return self._payload_call(self._controller.setup, payload)

    @Slot("QVariant", result="QVariant")
    def createAccount(self, payload):
        return self._payload_call(self._controller.create_account, payload)

    @Slot("QVariant", result="QVariant")
    def createExpense(self, payload):
        return self._payload_call(self._controller.create_expense, payload)

    @Slot("QVariant", result="QVariant")
    def createIncome(self, payload):
        return self._payload_call(self._controller.create_income, payload)

    @Slot("QVariant", result="QVariant")
    def createTransfer(self, payload):
        return self._payload_call(self._controller.create_transfer, payload)

    @Slot(str, result="QVariant")
    def suggestPayees(self, query: str):
        return self._call(self._controller.suggest_payees, query)

    @Slot(str, result="QVariant")
    def createPayee(self, name: str):
        return self._call(self._controller.create_payee, name)
