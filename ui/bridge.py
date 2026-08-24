from __future__ import annotations

from PySide6.QtCore import QObject, Slot

from core.app_controller import AppController


class Bridge(QObject):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller

    @Slot(result="QVariant")
    def getInitialState(self) -> dict[str, object]:
        return self._controller.initial_state()
