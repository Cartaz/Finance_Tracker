from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWidgets import QApplication

from ui.window import LocalOnlyPage

ROOT = Path(__file__).resolve().parents[1]


def test_installer_repairs_venv_and_verifies_webengine() -> None:
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "venv_usable()" in installer
    assert "Creating or repairing virtual environment" in installer
    assert "requirements-dev.txt" in installer
    assert "QWebEngineView" in installer
    assert ".venv/bin/python main.py" in installer


def test_ci_uses_current_node24_actions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow


def test_remote_navigation_stays_outside_embedded_webview(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    page = LocalOnlyPage()
    opened: list[QUrl] = []
    monkeypatch.setattr(
        "ui.window.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )
    try:
        remote = QUrl("https://example.com/path")
        assert page.acceptNavigationRequest(remote, None, True) is False
        assert opened == [remote]
        assert page.acceptNavigationRequest(QUrl("file:///tmp/index.html"), None, True)
    finally:
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def test_backup_ui_discloses_destructive_restore_and_maintenance() -> None:
    index = (ROOT / "ui" / "web" / "index.html").read_text(encoding="utf-8")
    backup = (ROOT / "ui" / "web" / "backup.js").read_text(encoding="utf-8")

    assert 'data-view="backup"' in index
    assert 'id="backup-create"' in index
    assert 'id="backup-export"' in index
    assert 'id="backup-restore-file"' in index
    assert "backup dello stato corrente" in index
    assert "modalità manutenzione" in index
    assert "window.confirm(" in backup
    assert "maintenanceChanged.connect" in backup
    assert "requiresReload" in backup
