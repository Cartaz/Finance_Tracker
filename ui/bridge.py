from __future__ import annotations

from PySide6.QtCore import QObject, Slot

from core.app_controller import AppController
from core.errors import FinanceTrackerError


class Bridge(QObject):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller

    def _call(self, function, *args):
        try:
            return {"ok": True, "data": function(*args)}
        except (FinanceTrackerError, TypeError, ValueError) as exc:
            return self._controller.error_payload(exc)

    @Slot(result="QVariant")
    def getInitialState(self):
        return self._call(self._controller.initial_state)

    @Slot(result="QVariant")
    def getSnapshot(self):
        return self._call(self._controller.snapshot)

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
