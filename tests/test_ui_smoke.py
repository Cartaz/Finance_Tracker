from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from ui.window import LocalOnlyPage

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_local_page_accepts_local_frontend() -> None:
    app = QApplication.instance() or QApplication([])
    page = LocalOnlyPage()
    try:
        assert page.acceptNavigationRequest(QUrl("file:///tmp/index.html"), None, True)
        assert page.acceptNavigationRequest(QUrl("qrc:///qtwebchannel/qwebchannel.js"), None, True)
    finally:
        page.deleteLater()
        app.processEvents()


def test_currency_controls_are_populated_from_backend_metadata() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert index.count('<select name="currency" required></select>') == 3
    assert "initial.currencies" in app_js
    assert "minorUnitDigits" in app_js
    assert "currencySpecs.get(currency)" in app_js
    assert 'style: "currency"' not in app_js


def test_percentage_formatting_uses_bigint() -> None:
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "BigInt(String(bps))" in app_js
    assert "Math.abs(bps)" not in app_js
    assert "Math.floor(Math.abs(bps)" not in app_js
