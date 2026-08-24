from dataclasses import dataclass
from pathlib import Path

import pytest

from core.account_service import AccountService
from core.database import Database
from core.ledger_service import LedgerService


@dataclass(slots=True)
class LedgerEnv:
    db: Database
    accounts: AccountService
    ledger: LedgerService
    book_id: int
    other_book_id: int


@pytest.fixture
def ledger_env(tmp_path: Path) -> LedgerEnv:
    db = Database(tmp_path / "finance.db")
    db.open()
    db.migrate()
    with db.transaction() as conn:
        user_id = int(
            conn.execute(
                "INSERT INTO users(name, created_at, updated_at) VALUES ('User', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        book_id = int(
            conn.execute(
                "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('Primary', 'EUR', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        other_book_id = int(
            conn.execute(
                "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('Other', 'EUR', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        conn.executemany(
            "INSERT INTO book_members(book_id, user_id, role) VALUES (?, ?, 'OWNER')",
            ((book_id, user_id), (other_book_id, user_id)),
        )
    env = LedgerEnv(db, AccountService(db), LedgerService(db), book_id, other_book_id)
    try:
        yield env
    finally:
        db.close()
