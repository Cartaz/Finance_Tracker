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


def test_loan_amortization_math_is_isolated_and_decimal_only() -> None:
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")
    policy = (CORE / "loan_policies.py").read_text(encoding="utf-8")

    assert "AmortizationPolicy" in service
    assert "Decimal" in policy
    assert "ROUND_HALF_UP" in policy
    assert "float(" not in service
    assert "float(" not in policy


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
    assert "currentLoanCapabilities.rateTypes" in frontend
    assert "currentLoanCapabilities.amortizationTypes" in frontend
    assert "currentLoanCapabilities.policyCombinations" in frontend
    assert "combination?.recastStrategies" in frontend
    assert 'state.accounts.filter((a) => a.type === "LIABILITY"' not in frontend
    assert 'state.accounts.filter((a) => a.type === "ASSET"' not in frontend


def test_forecast_consumes_canonical_loan_projection() -> None:
    loan = (CORE / "loan_service.py").read_text(encoding="utf-8")
    forecast = (CORE / "forecast_service.py").read_text(encoding="utf-8")

    assert "def project_payments(" in loan
    assert "def _project_remaining_rows(" in loan
    assert "AmortizationPolicy.installment(" in loan
    assert ".project_payments(" in forecast
    assert '"LOAN_INSTALLMENT"' in forecast
    assert 'flow_amount_minor = int(occurrence["interestMinor"])' in forecast
    assert "LedgerService" not in forecast


def test_loan_transport_fields_are_explicit_protocol_vocabulary() -> None:
    transport = (CORE / "transport.py").read_text(encoding="utf-8")
    for field in (
        '"annualRateBps"',
        '"currentAnnualRateBps"',
        '"nativeBalanceMinor"',
        '"originalPrincipalMinor"',
        '"outstandingPrincipalMinor"',
        '"fixedPaymentMinor"',
        '"nextPaymentMinor"',
        '"principalMinor"',
        '"interestMinor"',
        '"paymentMinor"',
        '"remainingPrincipalMinor"',
        '"totalInterestMinor"',
        '"totalPaidMinor"',
        '"flowBaseAmountMinor"',
    ):
        assert field in transport


def test_rate_history_and_payment_policy_are_not_ui_math() -> None:
    controller = (CORE / "app_controller.py").read_text(encoding="utf-8")
    service = (CORE / "loan_service.py").read_text(encoding="utf-8")
    frontend = (ROOT / "ui" / "web" / "app.js").read_text(encoding="utf-8")

    assert "def set_variable_rate(" in service
    assert "def post_custom_payment(" in service
    assert "def set_loan_variable_rate(" in controller
    assert "def post_custom_loan_payment(" in controller
    assert 'call("setLoanVariableRate"' in frontend
    assert 'call("postCustomLoanPayment"' in frontend
    assert "Math.pow(" not in frontend
    assert "parseFloat(" not in frontend


def test_database_still_delegates_schema_to_migration_layer() -> None:
    database = (CORE / "database.py").read_text(encoding="utf-8")
    catalog = (CORE / "migration_catalog.py").read_text(encoding="utf-8")

    assert "from core.migration_catalog import apply_migrations" in database
    assert "CREATE TABLE IF NOT EXISTS loans" not in database
    assert "CREATE TABLE IF NOT EXISTS loans" in catalog
    assert "CREATE TABLE loan_rate_revisions" in catalog
