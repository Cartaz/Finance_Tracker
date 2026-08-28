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


def test_ci_exercises_external_cwd_and_supported_python_range() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "cd /tmp" in workflow
    assert 'python-version: ["3.12", "3.14"]' in workflow


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
        assert page.acceptNavigationRequest(
            QUrl("qrc:///qtwebchannel/qwebchannel.js"), None, True
        )
        assert page.acceptNavigationRequest(QUrl("about:blank"), None, True)
        assert page.acceptNavigationRequest(QUrl("data:text/html,test"), None, True) is False
        assert page.acceptNavigationRequest(QUrl("javascript:alert(1)"), None, True) is False
    finally:
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def test_remote_subrequests_are_explicitly_blocked() -> None:
    window = (ROOT / "ui" / "window.py").read_text(encoding="utf-8")

    assert "class RemoteRequestBlocker" in window
    assert 'frozenset({"http", "https", "ftp", "ws", "wss"})' in window
    assert "ResourceTypeMainFrame" in window
    assert "not is_main_frame" in window
    assert "info.block(True)" in window
    assert "setUrlRequestInterceptor" in window


def test_frontend_contains_no_direct_remote_network_or_dynamic_code_api() -> None:
    frontend = "\n".join(
        (ROOT / "ui" / "web" / name).read_text(encoding="utf-8")
        for name in ("app.js", "backend-channel.js", "backup.js")
    )

    for forbidden in (
        "fetch(",
        "XMLHttpRequest(",
        "new WebSocket(",
        "EventSource(",
        "eval(",
        "new Function(",
    ):
        assert forbidden not in frontend


def test_backup_ui_discloses_destructive_restore_and_maintenance() -> None:
    index = (ROOT / "ui" / "web" / "index.html").read_text(encoding="utf-8")
    backup = (ROOT / "ui" / "web" / "backup.js").read_text(encoding="utf-8")

    assert 'data-view="tools"' in index
    assert 'id="tools-backup-panel"' in index
    assert 'id="backup-create"' in index
    assert 'id="backup-export"' in index
    assert 'id="backup-restore-file"' in index
    assert "backup dello stato corrente" in index
    assert "modalità manutenzione" in index
    assert "window.confirm(" in backup
    assert "maintenanceChanged.connect" in backup
    assert "requiresReload" in backup
