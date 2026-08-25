from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class BackgroundTaskSignals(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, object)


class BackgroundTask(QRunnable):
    def __init__(self, task_id: str, function: Callable[[], Any]) -> None:
        super().__init__()
        self.task_id = task_id
        self.function = function
        self.signals = BackgroundTaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(self.task_id, exc)
        else:
            self.signals.succeeded.emit(self.task_id, result)
