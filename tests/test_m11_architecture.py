from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
UI = ROOT / "ui"
WEB = UI / "web"


def test_backup_restore_has_one_deep_core_owner() -> None:
    service = (CORE / "backup_service.py").read_text(encoding="utf-8")
    controller = (CORE / "backup_controller.py").read_text(encoding="utf-8")
    app_controller = (CORE / "app_controller.py").read_text(encoding="utf-8")

    assert "class BackupService" in service
    assert "def prepare_restore(" in service
    assert "def finalize_restore(" in service
    assert "class BackupController" in controller
    assert "prepare_restore" not in app_controller
    assert "finalize_restore" not in app_controller


def test_restore_is_staged_verified_and_has_safety_backup_before_swap() -> None:
    service = (CORE / "backup_service.py").read_text(encoding="utf-8")

    prepare = service.index("def prepare_restore(")
    safety = service.index("self.create_managed_backup()", prepare)
    staging = service.index("staged.migrate()", prepare)
    integrity = service.index("staged.integrity_check()", prepare)
    finalize = service.index("def finalize_restore(")
    replace = service.index("staging.replace(live)", finalize)

    assert prepare < safety < staging < integrity < finalize < replace
    assert "rollback.replace(live)" in service
    assert '"safetyBackup"' in service


def test_backup_work_is_off_gui_thread_and_restore_enters_maintenance() -> None:
    bridge = (UI / "bridge.py").read_text(encoding="utf-8")
    worker = (UI / "background_task.py").read_text(encoding="utf-8")

    assert "QThreadPool" in bridge
    assert "BackgroundTask(" in bridge
    assert '"RESTORE_MANAGED"' in bridge
    assert '"RESTORE_EXTERNAL"' in bridge
    assert "maintenance=True" in bridge
    assert "if self._maintenance" in bridge
    assert "class BackgroundTask(QRunnable)" in worker


def test_native_shell_owns_backup_file_selection() -> None:
    window = (UI / "window.py").read_text(encoding="utf-8")
    bridge = (UI / "bridge.py").read_text(encoding="utf-8")
    frontend = (WEB / "backup.js").read_text(encoding="utf-8")

    assert "QFileDialog.getSaveFileName" in window
    assert "QFileDialog.getOpenFileName" in window
    assert "set_file_dialogs(" in window
    assert "Path(selected)" in bridge
    assert "QFileDialog" not in frontend
    assert "file://" not in frontend


def test_frontend_uses_one_shared_qwebchannel_instance() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    adapter = (WEB / "backend-channel.js").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    backup = (WEB / "backup.js").read_text(encoding="utf-8")

    assert index.index('src="backend-channel.js"') < index.index('src="app.js"')
    assert "financeTrackerBackend" in adapter
    assert "finance-backend-ready" in adapter
    assert app.count("new QWebChannel(") == 1
    assert "new QWebChannel(" not in backup
    assert "financeTrackerBackend" in backup


def test_backup_catalog_does_not_run_full_integrity_check_on_ui_path() -> None:
    service = (CORE / "backup_service.py").read_text(encoding="utf-8")
    start = service.index("def list_backups(")
    end = service.index("def create_managed_backup(", start)
    body = service[start:end]

    assert "_read_schema_version" in body
    assert "_verify_sqlite_file" not in body
    assert "integrity_check" not in body
