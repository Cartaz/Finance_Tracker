from __future__ import annotations

from PySide6.QtCore import QUrl

from ui.window import LocalOnlyPage


def test_local_page_blocks_remote_navigation(qtbot) -> None:
    page = LocalOnlyPage()
    try:
        assert page.acceptNavigationRequest(QUrl("file:///tmp/index.html"), None, True)
        assert not page.acceptNavigationRequest(QUrl("https://example.com"), None, True)
    finally:
        page.deleteLater()
