"""End-to-end workflows driven through the real Qt Quick interface.

The tests click real QML buttons and fill real QML fields against a real
SQLite database. Any QML runtime warning (binding errors, type errors,
unqualified failures) fails the test.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import (
    Q_ARG,
    Q_RETURN_ARG,
    QMetaObject,
    QObject,
    QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.backup_controller import BackupController
from core.backup_service import BackupService
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from ui.backup_task_manager import BackupTaskManager
from ui.bridge import Bridge
from ui.shell import QuickShell


class QmlHarness:
    def __init__(self, tmp_path: Path, settings: Settings | None = None) -> None:
        self.app = QApplication.instance() or QApplication([])
        self.messages: list[str] = []
        self._previous_handler = qInstallMessageHandler(self._capture)
        self.database = Database(tmp_path / "ui.db")
        self.database.migrate()
        self.controller = AppController(
            self.database,
            settings or Settings(),
            AccountService(self.database),
            LedgerService(self.database),
            BookService(self.database),
            PayeeService(self.database),
        )
        self.tasks = BackupTaskManager(
            BackupController(BackupService(self.database, tmp_path / "backups")),
            self.controller.error_payload,
        )
        self.bridge = Bridge(self.controller, self.tasks)
        self.shell = QuickShell(self.bridge, tmp_path / "backups")
        self.csv_path: Path | None = None
        self.restore_path: Path | None = None
        self.bridge.set_file_dialogs(
            export_picker=lambda: str(tmp_path / "export.sqlite3"),
            restore_picker=lambda: None if self.restore_path is None else str(self.restore_path),
            csv_picker=lambda: None if self.csv_path is None else str(self.csv_path),
        )
        self.finished: list[dict] = []
        self.bridge.backupTaskFinished.connect(self.finished.append)
        self.shell.load()
        self.root = self.shell.root
        self.pump()

    def _capture(self, mode, context, message) -> None:
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            self.messages.append(message)

    def close(self) -> None:
        self.root.close()
        self.shell.close()
        self.pump()
        qInstallMessageHandler(self._previous_handler)
        self.database.close()

    def pump(self) -> None:
        for _ in range(3):
            self.app.processEvents()

    def find(self, name: str) -> QObject:
        found = self.root.findChild(QObject, name) or self._find_item(
            self.root.contentItem(), name
        )
        assert found is not None, f"QML object not found: {name}"
        return found

    def _find_item(self, item: QQuickItem, name: str) -> QObject | None:
        # Repeater/ListView delegates are visual children, not QObject children.
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = self._find_item(child, name)
            if found is not None:
                return found
        return None

    def set_text(self, name: str, value: str) -> None:
        self.find(name).setProperty("text", value)

    def choose(self, name: str, value: object) -> None:
        selected = QMetaObject.invokeMethod(
            self.find(name), "select", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", str(value))
        )
        assert selected, f"{name} has no option {value!r}"
        self.pump()

    def click(self, name: str, expected_toast: str | None = None) -> None:
        button = self.find(name)
        assert button.property("enabled"), f"{name} is disabled"
        QMetaObject.invokeMethod(button, "clicked")
        self.pump()
        if expected_toast is not None:
            assert self.toast() == (expected_toast, False)

    def navigate(self, view: str) -> None:
        self.click(f"nav-{view}")

    def toast(self) -> tuple[str, bool]:
        return (
            self.find("toastText").property("text"),
            bool(self.find("toast").property("bad")),
        )

    def wait_for_task(self, count: int, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        while len(self.finished) < count and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        assert len(self.finished) >= count, "background task did not finish"
        self.pump()
        return self.finished[count - 1]

    def list_count(self, name: str) -> int:
        return int(self.find(name).property("count"))

    def qml_warnings(self) -> list[str]:
        return [message for message in self.messages if ".qml" in message or "qrc:" in message]


@pytest.fixture
def ui(tmp_path):
    harness = QmlHarness(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


def _setup_book(ui: QmlHarness) -> None:
    assert ui.find("bridgeStatus").property("text") == "Backend connesso"
    assert ui.root.property("hasBook") is False
    ui.set_text("setupUserName", "Audit")
    ui.set_text("setupBookName", "UI audit")
    ui.choose("setupCurrency", "EUR")
    ui.click("setupSubmit", "Book creato")
    assert ui.root.property("hasBook") is True


def _create_structure(ui: QmlHarness) -> None:
    ui.navigate("accounts")
    ui.set_text("accountName", "Bank")
    ui.set_text("trackingDate", "2026-01-01")
    ui.set_text("openingBalance", "1000")
    ui.click("accountSubmit", "Conto creato")
    ui.set_text("accountName", "Cash")
    ui.set_text("trackingDate", "2026-01-01")
    ui.click("accountSubmit", "Conto creato")
    ui.set_text("categoryName", "Food")
    ui.choose("categoryType", "EXPENSE")
    ui.click("categorySubmit", "Categoria creata")
    ui.set_text("categoryName", "Salary")
    ui.choose("categoryType", "INCOME")
    ui.click("categorySubmit", "Categoria creata")
    assert ui.list_count("accountsList") == 2


def test_first_run_manual_postings_and_csv_import(ui, tmp_path):
    _setup_book(ui)
    _create_structure(ui)

    ui.navigate("transactions")
    ui.set_text("expenseAmount", "10")
    ui.set_text("expenseDate", "2026-09-30")
    ui.set_text("expenseDescription", "UI expense")
    ui.click("expenseSubmit", "Spesa registrata")
    ui.set_text("incomeAmount", "100")
    ui.set_text("incomeDate", "2026-09-30")
    ui.click("incomeSubmit", "Entrata registrata")
    ui.set_text("transferAmount", "20")
    ui.set_text("transferDate", "2026-09-30")
    ui.click("transferSubmit", "Giroconto registrato")
    assert ui.list_count("transactionsList") == 4

    snapshot = ui.controller.snapshot()
    balances = [a["balanceMinor"] for a in snapshot["accounts"] if a["type"] == "ASSET"]
    assert balances == ["107000", "2000"]

    csv_file = tmp_path / "audit.csv"
    csv_file.write_text("date,amount,externalid\n2026-09-30,-5,ui-csv\n", encoding="utf-8")
    ui.csv_path = csv_file
    ui.navigate("tools")
    ui.set_text("importSource", "Audit CSV")
    # The worker may finish within the click's event pump, replacing the
    # transient "in corso" toast; only the final outcome is asserted.
    ui.click("importSubmit")
    result = ui.wait_for_task(1)
    assert result["ok"] is True, result
    assert ui.toast() == ("Importate 1 righe", False)
    assert ui.list_count("importRows") == 1

    ui.navigate("dashboard")
    net_worth = ui.find("metricNetWorth").property("value")
    assert net_worth == "1.090,00 EUR"

    ui.database.integrity_check()
    assert ui.qml_warnings() == []


def test_budget_schedule_loan_forecast_fx_and_restore(ui, tmp_path):
    _setup_book(ui)
    _create_structure(ui)

    ui.navigate("budgets")
    ui.set_text("budgetPeriod", "2026-09")
    QMetaObject.invokeMethod(ui.find("budgetsPage"), "reload")
    ui.set_text("budgetAmount", "300")
    ui.click("budgetSubmit", "Budget salvato")
    assert ui.list_count("budgetList") == 1

    ui.navigate("scheduled")
    ui.set_text("scheduledAmount", "12,30")
    ui.set_text("scheduledStart", "2026-02-01")
    ui.set_text("scheduledDescription", "Abbonamento")
    ui.click("scheduledSubmit", "Programmazione creata")
    assert ui.list_count("scheduledList") == 1
    ui.set_text("scheduledAsOf", "2026-03-15")
    ui.click("postDueScheduled", "2 scadenze registrate")

    ui.navigate("accounts")
    ui.choose("accountType", "LIABILITY")
    ui.set_text("accountName", "Mutuo")
    ui.set_text("trackingDate", "2026-01-01")
    ui.click("accountSubmit", "Conto creato")
    ui.navigate("loans")
    ui.set_text("loanName", "Prestito UI")
    ui.choose("loanMode", "NEW_DISBURSEMENT")
    ui.set_text("loanRate", "5")
    ui.set_text("loanPrincipal", "1200")
    ui.click("loanSubmit", "Prestito creato")
    assert ui.list_count("loanList") == 1

    ui.navigate("forecast")
    assert ui.find("forecastOccurrences").property("count") > 0

    ui.navigate("tools")
    ui.choose("fxCurrency", "USD")
    ui.set_text("fxDate", "2026-01-01")
    ui.set_text("fxRate", "0,92")
    ui.click("fxSubmit", "Tasso FX salvato")

    ui.click("backupCreate", "Creazione backup avviata")
    created = ui.wait_for_task(1)
    assert created["ok"] is True, created
    assert ui.list_count("backupList") == 1
    backup_name = created["data"]["name"]

    # A mutation after the backup must disappear after restoring it.
    ui.navigate("accounts")
    ui.set_text("accountName", "After backup")
    ui.set_text("trackingDate", "2026-01-01")
    ui.click("accountSubmit", "Conto creato")
    ui.find("transactionsPage").setProperty("payeeId", "5")
    ui.choose("accountCurrency", "USD")
    started = ui.bridge.startManagedRestore(backup_name)
    assert started["ok"] is True
    assert ui.bridge.busy is True
    ui.root.close()
    ui.pump()
    assert ui.root.property("visible") is True, "close must be blocked during restore"
    restored = ui.wait_for_task(2)
    assert restored["ok"] is True and restored["requiresReload"] is True
    assert ui.toast()[0].startswith("Ripristino completato.")
    names = [a["name"] for a in ui.controller.snapshot()["accounts"]]
    assert "After backup" not in names
    assert ui.list_count("accountsList") == 3
    assert ui.find("transactionsPage").property("payeeId") == ""
    assert ui.find("accountCurrency").property("value") == "EUR"
    assert ui.qml_warnings() == []


def test_backend_errors_are_reported_without_mutation(ui):
    _setup_book(ui)
    _create_structure(ui)
    ui.navigate("transactions")
    ui.set_text("expenseAmount", "-5")
    ui.set_text("expenseDate", "2026-09-30")
    ui.click("expenseSubmit")
    message, bad = ui.toast()
    assert bad is True
    assert "sign" in message
    assert ui.list_count("transactionsList") == 1
    assert ui.qml_warnings() == []


def test_csv_review_mode_defaults_to_the_configured_setting(tmp_path):
    harness = QmlHarness(tmp_path, Settings(reconciliation_review_mode="ASSISTED_REVIEW"))
    try:
        _setup_book(harness)
        harness.navigate("tools")
        assert harness.find("importReviewMode").property("value") == "ASSISTED_REVIEW"
        assert harness.qml_warnings() == []
    finally:
        harness.close()


def test_failed_startup_shows_a_retry_state(tmp_path, monkeypatch):
    original = AppController.initial_state
    calls = {"count": 0}

    def flaky(self):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("database temporarily unavailable")
        return original(self)

    monkeypatch.setattr(AppController, "initial_state", flaky)
    harness = QmlHarness(tmp_path)
    try:
        assert harness.find("bootError").property("visible") is True
        assert harness.root.property("ready") is False
        harness.click("bootRetry")
        assert harness.find("bootError").property("visible") is False
        assert harness.root.property("ready") is True
        assert harness.qml_warnings() == []
    finally:
        harness.close()


def test_restart_with_existing_book_loads_the_dashboard(tmp_path):
    first = QmlHarness(tmp_path)
    try:
        _setup_book(first)
        _create_structure(first)
    finally:
        first.close()
    second = QmlHarness(tmp_path)
    try:
        assert second.root.property("hasBook") is True
        assert second.find("metricNetWorth").property("value") == "1.000,00 EUR"
        assert second.find("toast").property("visible") is False
        assert second.qml_warnings() == []
    finally:
        second.close()


def test_form_choices_survive_data_refreshes(ui):
    _setup_book(ui)
    _create_structure(ui)
    ui.choose("accountType", "LIABILITY")
    ui.click("accountSubmit")  # no name: rejected, choices must stay intact
    ui.choose("accountType", "ASSET")
    ui.choose("openingDirection", "NEGATIVE")
    ui.click("refreshButton")
    assert ui.find("openingDirection").property("value") == "NEGATIVE"
    ui.set_text("accountName", "Overdraft")
    ui.set_text("trackingDate", "2026-01-01")
    ui.set_text("openingBalance", "500")
    ui.click("accountSubmit", "Conto creato")
    overdraft = [a for a in ui.controller.snapshot()["accounts"] if a["name"] == "Overdraft"]
    assert overdraft[0]["balanceMinor"] == "-50000"
    assert ui.find("openingDirection").property("value") == "POSITIVE"

    ui.choose("accountType", "LIABILITY")
    ui.set_text("accountName", "Mutuo variabile")
    ui.set_text("trackingDate", "2026-01-01")
    ui.click("accountSubmit", "Conto creato")
    ui.navigate("loans")
    ui.set_text("loanName", "Variabile")
    ui.choose("loanMode", "NEW_DISBURSEMENT")
    ui.choose("loanRateType", "VARIABLE")
    ui.set_text("loanRate", "4")
    ui.set_text("loanPrincipal", "1200")
    ui.click("loanSubmit", "Prestito creato")
    ui.set_text("rateEffective", "2027-05-01")
    ui.click("refreshButton")
    assert ui.find("rateEffective").property("text") == "2027-05-01"
    assert ui.qml_warnings() == []


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [("2026-01-31", 1, "2026-02-28"), ("2026-08-31", 6, "2027-02-28"), ("2024-01-31", 1, "2024-02-29"), ("2026-05-15", 1, "2026-06-15")],
)
def test_month_arithmetic_clamps_to_month_end(ui, start, months, expected):
    result = QMetaObject.invokeMethod(
        ui.root, "addMonths", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", start), Q_ARG("QVariant", months)
    )
    assert result == expected


def test_budget_with_missing_fx_reports_it_without_a_misleading_label(ui):
    _setup_book(ui)
    _create_structure(ui)
    ui.set_text("accountName", "Dollars")
    ui.choose("accountCurrency", "USD")
    ui.set_text("trackingDate", "2026-01-01")
    ui.set_text("openingBalance", "100")
    ui.click("accountSubmit", "Conto creato")
    ui.navigate("transactions")
    dollars = [a for a in ui.controller.snapshot()["accounts"] if a["name"] == "Dollars"][0]
    ui.choose("expenseAccount", dollars["id"])
    ui.set_text("expenseAmount", "5")
    ui.set_text("expenseDate", "2026-09-10")
    ui.click("expenseSubmit", "Spesa registrata")
    ui.navigate("budgets")
    ui.set_text("budgetPeriod", "2026-09")
    QMetaObject.invokeMethod(ui.find("budgetsPage"), "reload")
    ui.set_text("budgetAmount", "300")
    ui.click("budgetSubmit", "Budget salvato")
    row = ui.find("budgetRow-0")
    assert row.property("value") == "FX mancante"
    assert ui.qml_warnings() == []
