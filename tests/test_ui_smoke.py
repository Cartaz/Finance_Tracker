from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from ui.window import LocalOnlyPage


def test_local_page_accepts_local_frontend() -> None:
    app = QApplication.instance() or QApplication([])
    page = LocalOnlyPage()
    try:
        assert page.acceptNavigationRequest(QUrl("file:///tmp/index.html"), None, True)
        assert page.acceptNavigationRequest(QUrl("qrc:///qtwebchannel/qwebchannel.js"), None, True)
    finally:
        page.deleteLater()
        app.processEvents()
