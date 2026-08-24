from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def test_loan_balance_has_no_parallel_persisted_state() -> None:
    migration = (CORE / "migration_catalog.py").read_text(encoding="utf-8")
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")

    assert "outstanding_principal_minor" not in migration
    assert "remaining_principal_minor" not in migration
    assert "native_balance(" in service


def test_loan_service_delegates_accounting_writes_to_ledger() -> None:
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")

    assert "LedgerService" in service
    assert ".create_transfer(" in service
    assert ".create_transaction(" in service
    assert "INSERT INTO transactions" not in service
    assert "INSERT INTO entries" not in service


def test_loan_amortization_uses_decimal_not_float() -> None:
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")

    assert "Decimal" in service
    assert "ROUND_HALF_UP" in service
    assert "float(" not in service


def test_database_still_delegates_schema_to_migration_layer() -> None:
    database = (CORE / "database.py").read_text(encoding="utf-8")
    catalog = (CORE / "migration_catalog.py").read_text(encoding="utf-8")

    assert "from core.migration_catalog import apply_migrations" in database
    assert "CREATE TABLE IF NOT EXISTS loans" not in database
    assert "CREATE TABLE IF NOT EXISTS loans" in catalog
