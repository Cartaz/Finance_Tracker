from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def test_loan_balance_has_no_parallel_persisted_state() -> None:
    migration = (CORE / "migrations.py").read_text(encoding="utf-8")
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


def test_loan_amortization_math_is_isolated_and_decimal_only() -> None:
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")
    policy = (CORE / "loan_policies.py").read_text(encoding="utf-8")

    assert "AmortizationPolicy" in service
    assert "Decimal" in policy
    assert "ROUND_HALF_UP" in policy
    assert "float(" not in service
    assert "float(" not in policy


def test_loan_qml_renders_backend_capabilities_without_financial_rules() -> None:
    frontend = (ROOT / "ui" / "qml" / "pages" / "LoansPage.qml").read_text(encoding="utf-8")

    assert 'app.call("getLoanCapabilities")' in frontend
    # Eligible accounts and policies come from the backend, never from types
    # or arithmetic in QML.
    for forbidden in ('"LIABILITY"', '"ASSET"', "Math.pow(", "parseFloat("):
        assert forbidden not in frontend


def test_forecast_consumes_the_loan_service_projection() -> None:
    forecast = (CORE / "forecast_service.py").read_text(encoding="utf-8")

    assert ".project_payments(" in forecast
    assert "AmortizationPolicy" not in forecast
    assert "LedgerService" not in forecast


@pytest.mark.parametrize(
    "field",
    [
        "annualRateBps",
        "currentAnnualRateBps",
        "nativeBalanceMinor",
        "originalPrincipalMinor",
        "outstandingPrincipalMinor",
        "fixedPaymentMinor",
        "nextPaymentMinor",
        "principalMinor",
        "interestMinor",
        "paymentMinor",
        "remainingPrincipalMinor",
        "totalInterestMinor",
        "totalPaidMinor",
        "flowBaseAmountMinor",
    ],
)
def test_loan_financial_fields_cross_the_ui_boundary_exactly(field) -> None:
    from core.transport import TransportSerializer

    beyond_js = 2**53 + 1
    assert TransportSerializer.serialize({"rows": [{field: beyond_js}]}) == {
        "rows": [{field: str(beyond_js)}]
    }


def test_database_still_delegates_schema_to_migration_layer() -> None:
    database = (CORE / "database.py").read_text(encoding="utf-8")
    catalog = (CORE / "migrations.py").read_text(encoding="utf-8")

    assert "from core.migrations import apply_migrations" in database
    assert "CREATE TABLE IF NOT EXISTS loans" not in database
    assert "CREATE TABLE IF NOT EXISTS loans" in catalog
    assert "CREATE TABLE loan_rate_revisions" in catalog
