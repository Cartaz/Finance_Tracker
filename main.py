from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from config.constants import BACKUP_DIR, CONFIG_DIR, DATA_DIR, LOG_DIR
from config.settings import SettingsStore
from core.backup_controller import BackupController
from core.backup_service import BackupService
from core.composition import build_controller
from core.database import Database
from ui.backup_task_manager import BackupTaskManager
from ui.bridge import Bridge
from ui.shell import QuickShell

log = logging.getLogger(__name__)


def _ensure_directories() -> None:
    for path in (DATA_DIR, CONFIG_DIR, BACKUP_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError as exc:
            log.warning("Could not restrict directory permissions for %s: %s", path, exc)


def _configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            RotatingFileHandler(
                LOG_DIR / "finance-tracker.log",
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    database = Database()
    try:
        _ensure_directories()
        _configure_logging()
        settings = SettingsStore().load()
        database.open()
        database.migrate()
        database.integrity_check()
        backup_controller = BackupController(BackupService(database, BACKUP_DIR))
        app = QApplication(sys.argv)
        app.setApplicationName("Finance Tracker")
        controller = build_controller(database, settings)
        backup_tasks = BackupTaskManager(backup_controller, controller.error_payload)
        bridge = Bridge(controller, backup_tasks)
        shell = QuickShell(bridge, BACKUP_DIR)
        try:
            shell.load()
            return app.exec()
        finally:
            shell.close()
    except Exception:
        log.exception("Finance Tracker failed to start")
        return 1
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
