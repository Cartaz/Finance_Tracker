from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from config.constants import BACKUP_DIR
from ui.bridge import Bridge


class LocalOnlyPage(QWebEnginePage):
    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # type: ignore[override]
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return False
        return url.scheme() in {"file", "qrc", "data", "about"}


class MainWindow(QMainWindow):
    def __init__(self, bridge: Bridge) -> None:
        super().__init__()
        self.setWindowTitle("Finance Tracker")
        self.setMinimumSize(1200, 800)
        self.resize(1440, 900)
        self._restore_maintenance = False

        self._view = QWebEngineView(self)
        self._page = LocalOnlyPage(self._view)
        self._view.setPage(self._page)

        self._channel = QWebChannel(self._page)
        self._channel.registerObject("backend", bridge)
        self._page.setWebChannel(self._channel)

        bridge.maintenanceChanged.connect(self._set_restore_maintenance)
        bridge.set_file_dialogs(
            export_picker=self.choose_backup_export_path,
            restore_picker=self.choose_restore_path,
        )

        index_path = Path(__file__).resolve().parent / "web" / "index.html"
        self._view.setUrl(QUrl.fromLocalFile(str(index_path)))
        self.setCentralWidget(self._view)

    def _set_restore_maintenance(self, active: bool) -> None:
        self._restore_maintenance = bool(active)

    def choose_backup_export_path(self) -> str | None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta backup Finance Tracker",
            str(BACKUP_DIR / "finance-tracker-backup.sqlite3"),
            "Finance Tracker backup (*.sqlite3)",
        )
        return selected or None

    def choose_restore_path(self) -> str | None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Ripristina backup Finance Tracker",
            str(BACKUP_DIR),
            "Finance Tracker backup (*.sqlite3);;SQLite database (*.db *.sqlite *.sqlite3)",
        )
        return selected or None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._restore_maintenance or QThreadPool.globalInstance().activeThreadCount() > 0:
            QMessageBox.information(
                self,
                "Operazione in corso",
                "Attendi il completamento del backup o del ripristino prima di chiudere Finance Tracker.",
            )
            event.ignore()
            return
        super().closeEvent(event)
