from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.constants import DATABASE_PATH, SCHEMA_VERSION
from core.errors import DatabaseIntegrityError, UnsupportedCurrencyError
from core.money import CurrencySpec

_CURRENCIES = (
    ("EUR", "Euro", "€", 2),
    ("USD", "US Dollar", "$", 2),
    ("GBP", "Pound Sterling", "£", 2),
    ("CHF", "Swiss Franc", "CHF", 2),
    ("JPY", "Japanese Yen", "¥", 0),
    ("KWD", "Kuwaiti Dinar", "KWD", 3),
    ("BHD", "Bahraini Dinar", "BHD", 3),
    ("OMR", "Omani Rial", "OMR", 3),
    ("KRW", "South Korean Won", "₩", 0),
)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT,
    minor_unit_digits INTEGER NOT NULL CHECK (minor_unit_digits >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    base_currency_code TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (base_currency_code) REFERENCES currencies(code) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS book_members (
    book_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'EDITOR', 'VIEWER')),
    PRIMARY KEY (book_id, user_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_books_currency ON books(base_currency_code);
CREATE INDEX IF NOT EXISTS idx_book_members_user ON book_members(user_id);
"""


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
        conn = self.connection
        current = (
            conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
            if self._table_exists("schema_migrations")
            else 0
        )

        if current > SCHEMA_VERSION:
            raise DatabaseIntegrityError(
                f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
            )
        if current == 0:
            with self.transaction() as tx:
                tx.executescript(_SCHEMA_V1)
                tx.executemany(
                    "INSERT OR IGNORE INTO currencies(code, name, symbol, minor_unit_digits) VALUES (?, ?, ?, ?)",
                    _CURRENCIES,
                )
                tx.execute(
                    "INSERT INTO schema_migrations(version, applied_at, description) VALUES (1, datetime('now'), ?)",
                    ("Initial foundation schema",),
                )

    def _table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def currency(self, code: str) -> CurrencySpec:
        row = self.connection.execute(
            "SELECT code, minor_unit_digits FROM currencies WHERE code=? AND active=1",
            (code.upper(),),
        ).fetchone()
        if row is None:
            raise UnsupportedCurrencyError(f"unsupported currency: {code}")
        return CurrencySpec(row["code"], row["minor_unit_digits"])

    def integrity_check(self) -> None:
        result = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise DatabaseIntegrityError(f"SQLite integrity_check failed: {result}")
        fk_rows = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise DatabaseIntegrityError("SQLite foreign_key_check reported violations")

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
