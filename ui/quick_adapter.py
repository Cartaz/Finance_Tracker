"""Narrow, read-only UI adapter for the first Qt Quick migration milestone."""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QObject, Property, Signal, Slot

from core.app_controller import AppController
from core.errors import FinanceTrackerError
from ui.backup_task_manager import BackupTaskManager

log = logging.getLogger(__name__)


class QuickPreviewAdapter(QObject):
    """Expose presentation text, not financial state or calculations, to QML.

    This experimental surface reads the existing controller. It neither writes
    the ledger nor replaces the production WebEngine frontend during Q1.
    """

    dataChanged = Signal()
    busyChanged = Signal()
    errorOccurred = Signal(str)

    def __init__(
        self,
        controller: AppController,
        backup_tasks: BackupTaskManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._backup_tasks = backup_tasks
        self._book_name = ""
        self._currency = ""
        self._net_worth_minor = ""
        self._error_message = ""
        backup_tasks.maintenanceChanged.connect(self._on_maintenance_changed)
        backup_tasks.finished.connect(self._on_task_finished)
        self.refresh()

    @Property(str, notify=dataChanged)
    def bookName(self) -> str:
        return self._book_name

    @Property(str, notify=dataChanged)
    def currency(self) -> str:
        return self._currency

    @Property(str, notify=dataChanged)
    def netWorthMinor(self) -> str:
        return self._net_worth_minor

    @Property(str, notify=dataChanged)
    def errorMessage(self) -> str:
        return self._error_message

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._backup_tasks.active

    def _report_error(self, message: str) -> None:
        self._error_message = message
        self.dataChanged.emit()
        self.errorOccurred.emit(message)

    @Slot()
    def refresh(self) -> None:
        if self._backup_tasks.active:
            self._report_error("Operazione di backup o ripristino in corso.")
            return
        try:
            initial = self._controller.initial_state()
            book = initial["book"]
            if book is None:
                book_name = "Book non configurato"
                currency = str(initial["bookCurrency"])
                net_worth = "—"
            else:
                today = date.today()
                report = self._controller.dashboard(
                    {
                        "startDate": today.replace(day=1).isoformat(),
                        "endDate": today.isoformat(),
                        "asOfDate": today.isoformat(),
                    }
                )
                book_name = str(book["name"])
                currency = str(report["baseCurrency"])
                amount = report["overview"]["netWorthMinor"]
                # Never coerce money to a QML/JavaScript Number.
                net_worth = "FX mancanti" if amount is None else str(amount)
        except (FinanceTrackerError, TypeError, ValueError, KeyError) as exc:
            self._report_error(str(exc))
            return
        except Exception:
            log.exception("Unexpected QML preview refresh failure")
            self._report_error("Errore inatteso; consultare i log.")
            return
        self._book_name = book_name
        self._currency = currency
        self._net_worth_minor = net_worth
        self._error_message = ""
        self.dataChanged.emit()

    @Slot()
    def explainBusy(self) -> None:
        self._report_error(
            "Impossibile chiudere durante un backup o ripristino in corso."
        )

    @Slot(bool)
    def _on_maintenance_changed(self, _active: bool) -> None:
        self.busyChanged.emit()

    @Slot("QVariant")
    def _on_task_finished(self, _result: object) -> None:
        self.busyChanged.emit()
        # A restored database invalidates all previously presented values.
        if not self._backup_tasks.active:
            self.refresh()
