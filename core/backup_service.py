from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config.constants import BACKUP_DIR, SCHEMA_VERSION
from core.database import Database
from core.errors import BackupError

log = logging.getLogger(__name__)

_BACKUP_SUFFIX = ".sqlite3"
_BACKUP_PREFIX = "finance-tracker-"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    name: str
    path: Path
    size_bytes: int
    modified_utc: str
    schema_version: int

    def payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "sizeBytes": self.size_bytes,
            "modifiedUtc": self.modified_utc,
            "schemaVersion": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class RestorePlan:
    source: Path
    staged_database: Path
    source_schema_version: int
    safety_backup_name: str


class BackupService:
    """Owns verified backup files and fail-safe restore preparation/finalization."""

    def __init__(self, database: Database, backup_dir: Path = BACKUP_DIR) -> None:
        self._database = database
        self._backup_dir = backup_dir

    def list_backups(self) -> list[dict[str, object]]:
        """List managed backups without running a full integrity scan on the UI path."""
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        items: list[BackupInfo] = []
        for path in self._backup_dir.glob(f"{_BACKUP_PREFIX}*{_BACKUP_SUFFIX}"):
            if not path.is_file():
                continue
            try:
                schema_version = self._read_schema_version(path)
            except BackupError as exc:
                log.warning("Ignoring unreadable managed backup %s: %s", path, exc)
                continue
            stat = path.stat()
            items.append(
                BackupInfo(
                    name=path.name,
                    path=path,
                    size_bytes=stat.st_size,
                    modified_utc=datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat(),
                    schema_version=schema_version,
                )
            )
        items.sort(key=lambda item: item.modified_utc, reverse=True)
        return [item.payload() for item in items]

    def backup_to(self, destination: Path) -> dict[str, object]:
        """Create one verified snapshot at the exact destination path."""
        destination = destination.expanduser().resolve()
        if destination == self._database.path.expanduser().resolve():
            raise BackupError("backup destination cannot be the live database")
        self._backup_live_database(destination)
        return self.inspect(destination).payload()

    def create_managed_backup(self) -> dict[str, object]:
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = self._backup_dir / f"{_BACKUP_PREFIX}{stamp}{_BACKUP_SUFFIX}"
        return self.backup_to(destination)

    def export_backup(self, destination: Path) -> dict[str, object]:
        destination = destination.expanduser().resolve()
        if destination.suffix.lower() != _BACKUP_SUFFIX:
            destination = destination.with_suffix(_BACKUP_SUFFIX)
        return self.backup_to(destination)

    def managed_path(self, name: str) -> Path:
        if not name or Path(name).name != name:
            raise BackupError("invalid managed backup identifier")
        path = (self._backup_dir / name).resolve()
        root = self._backup_dir.resolve()
        if (
            path.parent != root
            or not name.startswith(_BACKUP_PREFIX)
            or not name.endswith(_BACKUP_SUFFIX)
        ):
            raise BackupError("invalid managed backup identifier")
        if not path.is_file():
            raise BackupError("backup file does not exist")
        return path

    def inspect(self, source: Path) -> BackupInfo:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise BackupError("backup file does not exist")
        schema_version = self._verify_sqlite_file(source)
        stat = source.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        return BackupInfo(
            name=source.name,
            path=source,
            size_bytes=stat.st_size,
            modified_utc=modified,
            schema_version=schema_version,
        )

    def prepare_restore(self, source: Path) -> RestorePlan:
        source = source.expanduser().resolve()
        if source == self._database.path.expanduser().resolve():
            raise BackupError("cannot restore the live database onto itself")
        source_schema = self._verify_sqlite_file(source)
        safety = self.create_managed_backup()
        staging = (
            self._database.path.parent
            / f".{self._database.path.name}.restore-{uuid4().hex}.tmp"
        )
        try:
            self._copy_sqlite_database(source, staging)
            staged = Database(staging)
            try:
                staged.open()
                staged.migrate()
                staged.integrity_check()
            finally:
                staged.close()
        except Exception:
            staging.unlink(missing_ok=True)
            raise
        return RestorePlan(
            source=source,
            staged_database=staging,
            source_schema_version=source_schema,
            safety_backup_name=str(safety["name"]),
        )

    def cancel_restore(self, plan: RestorePlan) -> None:
        plan.staged_database.unlink(missing_ok=True)

    def finalize_restore(self, plan: RestorePlan) -> dict[str, object]:
        """Perform only the short live-file swap after worker-side verification."""
        staging = plan.staged_database
        if not staging.is_file():
            raise BackupError("prepared restore database is missing")
        if self._read_schema_version(staging) != SCHEMA_VERSION:
            raise BackupError("prepared restore database is not at the current schema")

        live = self._database.path
        live.parent.mkdir(parents=True, exist_ok=True)
        rollback = live.parent / f".{live.name}.rollback-{uuid4().hex}.tmp"

        self._database.checkpoint()
        self._database.close()
        self._remove_sidecars(live)

        try:
            if live.exists():
                live.replace(rollback)
            staging.replace(live)
            self._remove_sidecars(live)
            self._database.open()
        except Exception as exc:
            self._database.close()
            failed = live.parent / f".{live.name}.failed-{uuid4().hex}.tmp"
            if live.exists():
                live.replace(failed)
            if rollback.exists():
                rollback.replace(live)
            self._remove_sidecars(live)
            try:
                self._database.open()
            except Exception as rollback_exc:
                raise BackupError(
                    "restore failed and the previous database could not be reopened"
                ) from rollback_exc
            finally:
                failed.unlink(missing_ok=True)
            raise BackupError("restore failed; previous database was restored") from exc
        else:
            rollback.unlink(missing_ok=True)

        return {
            "restoredFrom": plan.source.name,
            "safetyBackup": plan.safety_backup_name,
            "sourceSchemaVersion": plan.source_schema_version,
            "schemaVersion": SCHEMA_VERSION,
        }

    def _backup_live_database(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            self._copy_sqlite_database(self._database.path, temp)
            self._verify_sqlite_file(temp, require_current_schema=True)
            os.replace(temp, destination)
            self._restrict_file_permissions(destination)
        finally:
            temp.unlink(missing_ok=True)

    @classmethod
    def _copy_sqlite_database(cls, source: Path, destination: Path) -> None:
        if not source.is_file():
            raise BackupError("source database does not exist")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        source_conn = cls._connect_readonly(source)
        target_conn = sqlite3.connect(destination, autocommit=True)
        try:
            source_conn.backup(target_conn)
        except sqlite3.Error as exc:
            raise BackupError(f"SQLite backup failed: {exc}") from exc
        finally:
            target_conn.close()
            source_conn.close()

    @classmethod
    def _verify_sqlite_file(
        cls, path: Path, *, require_current_schema: bool = False
    ) -> int:
        schema_version = cls._read_schema_version(path)
        conn = cls._connect_readonly(path)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise BackupError(f"backup integrity_check failed: {integrity}")
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise BackupError("backup foreign_key_check reported violations")
        except sqlite3.Error as exc:
            raise BackupError(f"backup verification failed: {exc}") from exc
        finally:
            conn.close()
        if require_current_schema and schema_version != SCHEMA_VERSION:
            raise BackupError(
                f"prepared database schema {schema_version} does not match current schema {SCHEMA_VERSION}"
            )
        return schema_version

    @classmethod
    def _read_schema_version(cls, path: Path) -> int:
        conn = cls._connect_readonly(path)
        try:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if table is None:
                raise BackupError("file is not a Finance Tracker database")
            schema_version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
            )
        except sqlite3.Error as exc:
            raise BackupError(f"backup schema inspection failed: {exc}") from exc
        finally:
            conn.close()
        if schema_version <= 0:
            raise BackupError("backup schema version is invalid")
        if schema_version > SCHEMA_VERSION:
            raise BackupError(
                f"backup schema {schema_version} is newer than supported schema {SCHEMA_VERSION}"
            )
        return schema_version

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        if not path.is_file():
            raise BackupError("backup file does not exist")
        mode = "?mode=ro"
        try:
            return sqlite3.connect(
                f"{path.resolve().as_uri()}{mode}",
                uri=True,
                autocommit=True,
            )
        except sqlite3.Error as exc:
            raise BackupError(f"cannot open backup database read-only: {exc}") from exc

    @staticmethod
    def _restrict_file_permissions(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError as exc:
            log.warning("Could not restrict backup permissions for %s: %s", path, exc)

    @staticmethod
    def _remove_sidecars(path: Path) -> None:
        Path(f"{path}-wal").unlink(missing_ok=True)
        Path(f"{path}-shm").unlink(missing_ok=True)
