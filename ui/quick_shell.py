"""Native Qt Quick preview shell; production continues to use ui.window until parity."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from core.app_controller import AppController
from ui.backup_task_manager import BackupTaskManager
from ui.quick_adapter import QuickPreviewAdapter

_PREVIEW_QML = Path(__file__).resolve().parent / "qml" / "Preview.qml"


def launch_quick_preview(
    controller: AppController, backup_tasks: BackupTaskManager
) -> QQmlApplicationEngine:
    """Load a read-only screen backed by the real controller, or fail explicitly.

    Engine owns the QObject adapter. Caller retains the engine until app.exec()
    exits. The existing WebEngine window is never instantiated in preview mode.
    """
    QQuickStyle.setStyle("Basic")
    engine = QQmlApplicationEngine()
    adapter = QuickPreviewAdapter(controller, backup_tasks, parent=engine)
    engine.setInitialProperties({"backend": adapter})
    engine.load(QUrl.fromLocalFile(str(_PREVIEW_QML)))
    if not engine.rootObjects():
        raise RuntimeError(f"Qt Quick preview could not load: {_PREVIEW_QML}")
    return engine
