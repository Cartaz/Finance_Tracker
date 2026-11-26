"""Native Qt Quick shell: QML engine ownership and native file selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QFileDialog

from config.constants import BACKUP_DIR
from ui.bridge import Bridge

QML_ROOT = Path(__file__).resolve().parent / "qml"
MAIN_QML = QML_ROOT / "Main.qml"


class QuickShell:
    """Owns the QML engine for the lifetime of the application.

    QML only receives the single backend object. Filesystem access happens
    exclusively through native dialogs owned here; QML never sees a path.
    """

    def __init__(self, bridge: Bridge, backup_dir: Path = BACKUP_DIR) -> None:
        self._bridge = bridge
        self._backup_dir = backup_dir
        bridge.set_file_dialogs(
            export_picker=self.choose_backup_export_path,
            restore_picker=self.choose_restore_path,
            csv_picker=self.choose_csv_path,
        )
        QQuickStyle.setStyle("Basic")
        self.engine = QQmlApplicationEngine()
        self.engine.setInitialProperties({"backend": bridge})

    def load(self) -> None:
        self.engine.load(QUrl.fromLocalFile(str(MAIN_QML)))
        if not self.engine.rootObjects():
            raise RuntimeError(f"Qt Quick interface could not load: {MAIN_QML}")

    def close(self) -> None:
        """Destroy windows and the engine before QApplication is destroyed.

        Qt Quick's render loop must not outlive its windows; relying on
        Python's teardown order can crash the process on exit.
        """
        for root in self.engine.rootObjects():
            root.deleteLater()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    @property
    def root(self):
        return self.engine.rootObjects()[0]

    def choose_backup_export_path(self) -> str | None:
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        selected, _ = QFileDialog.getSaveFileName(
            None,
            "Esporta backup Finance Tracker",
            str(self._backup_dir / "finance-tracker-backup.sqlite3"),
            "Finance Tracker backup (*.sqlite3)",
        )
        return selected or None

    def choose_restore_path(self) -> str | None:
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        selected, _ = QFileDialog.getOpenFileName(
            None,
            "Ripristina backup Finance Tracker",
            str(self._backup_dir),
            "Finance Tracker backup (*.sqlite3);;SQLite database (*.db *.sqlite *.sqlite3)",
        )
        return selected or None

    def choose_csv_path(self) -> str | None:
        selected, _ = QFileDialog.getOpenFileName(
            None,
            "Importa CSV bancario",
            str(Path.home()),
            "CSV bancario (*.csv *.txt);;Tutti i file (*)",
        )
        return selected or None
