"""The committed bug-hunting fixtures, run automatically instead of by hand."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.backup_service import BackupService
from core.errors import BackupError, ReconciliationAmbiguousError, ReconciliationError
from core.payee_service import PayeeService
from core.reconciliation_service import ReconciliationService

FIXTURES = Path(__file__).resolve().parents[1] / "bug-hunting-test"


@pytest.fixture
def import_file(ledger_env):
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    service = ReconciliationService(
        ledger_env.db, ledger_env.accounts, ledger_env.ledger, PayeeService(ledger_env.db)
    )

    def run(name: str):
        return service.import_csv_file(
            book_id=ledger_env.book_id,
            account_id=bank.id,
            source_name="Bug hunting",
            csv_path=FIXTURES / name,
            review_mode="FULL_REVIEW",
        )

    return run


def test_valid_italian_semicolon_csv_is_staged(import_file, ledger_env) -> None:
    result = import_file("bug-hunting-test-reconciliation-valid-italian-semicolon.csv")
    assert result["rowCount"] == 3
    rows = ledger_env.db.connection.execute(
        "SELECT transaction_date, amount_minor, description FROM import_rows ORDER BY row_number"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("2026-08-01", -4550, "Spesa supermercato"),
        ("2026-08-02", 250000, "Stipendio"),
        ("2026-08-03", -1230, "Caffè e pranzo"),
    ]


@pytest.mark.parametrize(
    ("name", "error", "message"),
    [
        ("bug-hunting-test-reconciliation-ambiguous-headers.csv", ReconciliationAmbiguousError, "multiple candidate columns"),
        ("bug-hunting-test-reconciliation-duplicate-external-id.csv", ReconciliationAmbiguousError, "duplicate external id"),
        ("bug-hunting-test-reconciliation-wrong-currency.csv", ReconciliationError, "does not match account currency"),
        ("bug-hunting-test-reconciliation-zero-amount.csv", ReconciliationError, "zero amount"),
    ],
)
def test_invalid_csv_fixtures_fail_without_staging(import_file, ledger_env, name, error, message) -> None:
    with pytest.raises(error, match=message):
        import_file(name)
    assert ledger_env.db.connection.execute("SELECT COUNT(*) FROM import_rows").fetchone()[0] == 0


def test_non_sqlite_restore_source_is_rejected_before_the_live_database(ledger_env, tmp_path) -> None:
    live_before = ledger_env.db.path.read_bytes()
    service = BackupService(ledger_env.db, tmp_path / "backups")
    with pytest.raises(BackupError):
        service.prepare_restore(FIXTURES / "bug-hunting-test-invalid-not-sqlite.sqlite3")
    assert ledger_env.db.path.read_bytes() == live_before
    assert service.list_backups() == []
