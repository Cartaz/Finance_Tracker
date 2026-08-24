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


def test_loan_creation_capabilities_are_backend_owned() -> None:
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")
    controller = (CORE / "app_controller.py").read_text(encoding="utf-8")
    frontend = (ROOT / "ui" / "web" / "app.js").read_text(encoding="utf-8")

    assert "def creation_capabilities(" in service
    assert "def loan_capabilities(" in controller
    assert 'call("getLoanCapabilities"' in frontend
    assert "target?.allowedModes" in frontend
    assert "target?.paymentAccountIds" in frontend
    assert "target?.fundingAccountIds" in frontend
    assert 'state.accounts.filter((a) => a.type === "LIABILITY"' not in frontend
    assert 'state.accounts.filter((a) => a.type === "ASSET"' not in frontend


def test_forecast_consumes_canonical_loan_projection() -> None:
    loan = (CORE / "loan_service.py").read_text(encoding="utf-8")
    forecast = (CORE / "forecast_service.py").read_text(encoding="utf-8")

    assert "def project_payments(" in loan
    assert "def _next_payment_terms(" in loan
    assert ".project_payments(" in forecast
    assert '"LOAN_INSTALLMENT"' in forecast
    assert 'flow_amount_minor = int(occurrence["interestMinor"])' in forecast
    assert "LedgerService" not in forecast


def test_loan_transport_fields_are_explicit_protocol_vocabulary() -> None:
    transport = (CORE / "transport.py").read_text(encoding="utf-8")
    for field in (
        '"annualRateBps"',
        '"nativeBalanceMinor"',
        '"originalPrincipalMinor"',
        '"outstandingPrincipalMinor"',
        '"fixedPaymentMinor"',
        '"principalMinor"',
        '"interestMinor"',
        '"paymentMinor"',
        '"remainingPrincipalMinor"',
        '"totalInterestMinor"',
        '"totalPaidMinor"',
        '"flowBaseAmountMinor"',
    ):
        assert field in transport


def test_database_still_delegates_schema_to_migration_layer() -> None:
    database = (CORE / "database.py").read_text(encoding="utf-8")
    catalog = (CORE / "migration_catalog.py").read_text(encoding="utf-8")

    assert "from core.migration_catalog import apply_migrations" in database
    assert "CREATE TABLE IF NOT EXISTS loans" not in database
    assert "CREATE TABLE IF NOT EXISTS loans" in catalog
