"""Backup/restore architecture: ownership boundaries and GUI-thread limits.

Boundaries are checked on imports and forbidden APIs; lifecycle rules are
checked by running the real services, not by matching source text.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.backup_service import BackupService
from core.database import Database

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
UI = ROOT / "ui"


def _imported_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
    return names


def test_backup_restore_is_owned_by_core_services_not_the_app_controller() -> None:
    controller_imports = _imported_names(CORE / "app_controller.py")
    assert not {"core.backup_service", "core.backup_controller"} & controller_imports


def test_bridge_and_qml_delegate_threads_files_and_sqlite() -> None:
    bridge_imports = _imported_names(UI / "bridge.py")
    for forbidden in ("sqlite3", "QFileDialog", "QThreadPool", "uuid", "RestorePlan"):
        assert forbidden not in bridge_imports, forbidden
    qml = "\n".join(path.read_text(encoding="utf-8") for path in (UI / "qml").rglob("*.qml"))
    assert "FileDialog" not in qml
    assert "file:" not in qml


def test_shell_registers_every_native_picker(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from ui.shell import QuickShell

    QApplication.instance() or QApplication([])

    class Bridge:
        def __init__(self) -> None:
            self.pickers: dict = {}

        def set_file_dialogs(self, **pickers) -> None:
            self.pickers = pickers

    bridge = Bridge()
    shell = QuickShell(bridge, tmp_path)  # type: ignore[arg-type]
    try:
        assert set(bridge.pickers) == {"export_picker", "restore_picker", "csv_picker"}
        assert all(callable(picker) for picker in bridge.pickers.values())
    finally:
        shell.close()


def _live(tmp_path: Path) -> tuple[Database, BackupService]:
    database = Database(tmp_path / "live.db")
    database.migrate()
    return database, BackupService(database, tmp_path / "backups")


def test_gui_thread_paths_never_run_a_full_integrity_scan(tmp_path, monkeypatch) -> None:
    database, service = _live(tmp_path)
    try:
        service.create_managed_backup()
        plan = service.prepare_restore(service.managed_path(service.list_backups()[0]["name"]))

        def forbidden(*_args, **_kwargs):
            raise AssertionError("full integrity scan on the GUI thread")

        monkeypatch.setattr(BackupService, "_verify_sqlite_file", forbidden)
        monkeypatch.setattr(Database, "integrity_check", forbidden)
        assert len(service.list_backups()) == 2  # original + pre-restore safety snapshot
        result = service.finalize_restore(plan)
        assert result["safetyBackup"]
    finally:
        database.close()


def test_external_restore_sources_are_never_modified(tmp_path) -> None:
    database, service = _live(tmp_path)
    try:
        source = tmp_path / "external.sqlite3"
        service.backup_to(source)
        source.chmod(0o444)
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        plan = service.prepare_restore(source)
        service.cancel_restore(plan)
        assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    finally:
        source.chmod(0o644)
        database.close()


def test_restore_preparation_refuses_the_live_database_itself(tmp_path) -> None:
    from core.errors import BackupError

    database, service = _live(tmp_path)
    try:
        with pytest.raises(BackupError, match="onto itself"):
            service.prepare_restore(database.path)
    finally:
        database.close()
