from __future__ import annotations

from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_loan_ui_uses_backend_capabilities_and_backend_financial_results() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-view="loans"' in index
    assert 'id="loan-form"' in index
    assert 'id="loan-list"' in index
    assert 'id="loan-detail"' in index
    assert 'call("getLoanCapabilities"' in app_js
    assert 'call("createLoan"' in app_js
    assert 'call("listLoans"' in app_js
    assert 'call("getLoanPlan"' in app_js
    assert 'call("postNextLoanPayment"' in app_js
    assert "currentLoanCapabilities.targets" in app_js
    assert "target?.paymentAccountIds" in app_js
    assert "target?.fundingAccountIds" in app_js
    assert 'state.accounts.filter((a) => a.type === "LIABILITY"' not in app_js
    assert 'state.accounts.filter((a) => a.type === "ASSET"' not in app_js
    assert "loan.outstandingPrincipalMinor" in app_js
    assert "loan.fixedPaymentMinor" in app_js
    assert "row.principalMinor" in app_js
    assert "row.interestMinor" in app_js
    assert "parseFloat(" not in app_js
    assert "Math.pow(" not in app_js


def test_loan_ui_discloses_m10_contract_scope() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert "prestiti ammortizzati mensilmente a tasso fisso" in index
    assert "saldo reale del conto LIABILITY" in index
