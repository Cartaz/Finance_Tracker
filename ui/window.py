from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

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

        self._view = QWebEngineView(self)
        self._page = LocalOnlyPage(self._view)
        self._view.setPage(self._page)

        self._channel = QWebChannel(self._page)
        self._channel.registerObject("backend", bridge)
        self._page.setWebChannel(self._channel)

        index_path = Path(__file__).resolve().parent / "web" / "index.html"
        self._view.setUrl(QUrl.fromLocalFile(str(index_path)))
        self.setCentralWidget(self._view)
