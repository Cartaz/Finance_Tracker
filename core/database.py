from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.constants import DATABASE_PATH, SCHEMA_VERSION
from core.currency_registry import CurrencyRegistry
from core.errors import DatabaseIntegrityError
from core.migration_catalog import apply_migrations
from core.money import CurrencySpec


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None

    def open(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, autocommit=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if enabled != 1:
            conn.close()
            raise DatabaseIntegrityError("SQLite foreign key enforcement could not be enabled")
        journal_mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            conn.close()
            raise DatabaseIntegrityError(f"SQLite WAL mode unavailable: {journal_mode}")
        conn.autocommit = False
        self._connection = conn
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self.open()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def migrate(self) -> None:
        current = self._current_schema_version()
        if current > SCHEMA_VERSION:
            raise DatabaseIntegrityError(
                f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
            )
        if current == SCHEMA_VERSION:
            return
        with self.transaction() as tx:
            apply_migrations(
                tx,
                current_version=current,
                target_version=SCHEMA_VERSION,
            )

    def _current_schema_version(self) -> int:
        if not self._table_exists("schema_migrations"):
            return 0
        return int(
            self.connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )

    def _table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def currency(self, code: str) -> CurrencySpec:
        """Compatibility facade; currency semantics live in CurrencyRegistry."""
        return CurrencyRegistry(self.connection).get(code)

    def integrity_check(self) -> None:
        result = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise DatabaseIntegrityError(f"SQLite integrity_check failed: {result}")
        fk_rows = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise DatabaseIntegrityError("SQLite foreign_key_check reported violations")

    def checkpoint(self) -> None:
        """Flush committed WAL pages before a native database-file swap."""
        if self._connection is None:
            return
        self._connection.commit()
        row = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and int(row[0]) != 0:
            raise DatabaseIntegrityError("SQLite WAL checkpoint could not complete")

    def backup_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(destination.suffix + ".tmp")
        if temp.exists():
            temp.unlink()
        source = self.connection
        source.commit()
        target = sqlite3.connect(temp, autocommit=True)
        try:
            source.backup(target)
        finally:
            target.close()
        verify = sqlite3.connect(temp, autocommit=True)
        try:
            verify.execute("PRAGMA foreign_keys = ON")
            integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise DatabaseIntegrityError(f"backup integrity_check failed: {integrity}")
            violations = verify.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise DatabaseIntegrityError("backup foreign_key_check reported violations")
        finally:
            verify.close()
        temp.replace(destination)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
