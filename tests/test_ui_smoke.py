from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from ui.window import LocalOnlyPage

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_local_page_accepts_local_frontend() -> None:
    app = QApplication.instance() or QApplication([])
    page = LocalOnlyPage()
    try:
        assert page.acceptNavigationRequest(QUrl("file:///tmp/index.html"), None, True)
        assert page.acceptNavigationRequest(
            QUrl("qrc:///qtwebchannel/qwebchannel.js"), None, True
        )
    finally:
        page.deleteLater()
        app.processEvents()


def test_currency_controls_are_populated_from_backend_metadata() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert index.count('<select name="currency" required></select>') == 3
    assert "initial.currencies" in app_js
    assert "minorUnitDigits" in app_js
    assert "currencySpecs.get(currency)" in app_js
    assert 'style: "currency"' not in app_js


def test_percentage_formatting_uses_bigint() -> None:
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "BigInt(String(bps))" in app_js
    assert "Math.abs(bps)" not in app_js
    assert "Math.floor(Math.abs(bps)" not in app_js


def test_reconciliation_keeps_selected_batch_after_actions() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-view="reconciliation"' in index
    assert 'let currentBatchId = null;' in app_js
    assert 'currentBatchId = String(batchId);' in app_js
    assert 'if (currentBatchId) await loadImportBatch(currentBatchId);' in app_js
    assert '.import-batch:focus' not in app_js


def test_reconciliation_ui_uses_structured_candidates_and_safe_file_payload() -> None:
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-transaction-id="${candidate.id}"' in app_js
    assert 'delete data["import-file"]' in app_js
    assert '"TRACKING_AMBIGUOUS"' in app_js
    assert (
        'const blocked = ["OUTSIDE_TRACKING", "TRACKING_AMBIGUOUS", "AMBIGUOUS"]'
        in app_js
    )
    assert "postingKind: postingKind?.value" in app_js
    assert "counterAccountId: counter.value" in app_js
    assert "initial.reconciliationReviewMode" in app_js


def test_scheduled_ui_is_backend_driven_and_uses_posting_capabilities() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-view="scheduled"' in index
    assert 'id="scheduled-form"' in index
    assert 'id="post-due-scheduled"' in index
    assert 'call("listScheduledTransactions")' in app_js
    assert 'call("createScheduledTransaction"' in app_js
    assert 'call("postDueScheduled"' in app_js
    assert 'call("setScheduledActive"' in app_js
    assert "source.postingCapabilities?.[kind]" in app_js
    assert "optionsForAccountIds" in app_js
    assert 'a.type === "INCOME"' not in app_js
    assert 'a.currency === source.currency' not in app_js
    assert "setInterval(" not in app_js
    assert "setTimeout(() => $(\"toast\")" in app_js


def test_budget_ui_uses_backend_budget_status_and_bigint_money() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-view="budgets"' in index
    assert 'id="budget-form"' in index
    assert 'id="budget-period"' in index
    assert 'id="budget-category"' in index
    assert 'call("getBudgetStatus"' in app_js
    assert 'call("setBudget"' in app_js
    assert 'call("deleteBudget"' in app_js
    assert "report.totalSpentMinor" in app_js
    assert "report.totalRemainingMinor" in app_js
    assert "item.usageBps" in app_js
    assert "parseFloat(" not in app_js
    assert "Number(item.spentMinor" not in app_js


def test_forecast_ui_is_backend_driven_and_explicit_about_assumptions() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-view="forecast"' in index
    assert 'id="forecast-start"' in index
    assert 'id="forecast-end"' in index
    assert 'id="forecast-granularity"' in index
    assert 'call("getForecast"' in app_js
    assert "report.totalInflowMinor" in app_js
    assert "report.totalOutflowMinor" in app_js
    assert "report.totalNetMinor" in app_js
    assert "report.buckets" in app_js
    assert "report.occurrences" in app_js
    assert "transazioni programmate attive" in index
    assert "non viene previsto il cambio futuro" in index
    assert "ultimo tasso FX noto" in index
    assert "Math.random(" not in app_js
    assert "parseFloat(" not in app_js
