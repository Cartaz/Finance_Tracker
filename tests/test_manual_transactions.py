from __future__ import annotations

from pathlib import Path

from config.settings import Settings
from core.app_controller import AppController
from core.book_service import BookService
from core.fx_service import FxService
from core.payee_service import PayeeService
from core.reporting_service import ReportingService
from ui.bridge import Bridge

ROOT = Path(__file__).resolve().parents[1]


def _bridge(ledger_env) -> Bridge:
    fx = FxService(ledger_env.db)
    controller = AppController(
        ledger_env.db,
        Settings(),
        ledger_env.accounts,
        ledger_env.ledger,
        BookService(ledger_env.db),
        PayeeService(ledger_env.db),
        fx,
        ReportingService(ledger_env.db, fx, ledger_env.accounts),
    )
    return Bridge(controller)


def test_manual_income_and_transfer_cover_normal_salary_workflow(ledger_env) -> None:
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Conto corrente",
        currency_code="EUR",
        tracking_start_date="2026-08-01",
    )
    cash = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Contanti",
        currency_code="EUR",
        tracking_start_date="2026-08-01",
    )
    salary = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="INCOME",
        name="Stipendio",
    )
    bridge = _bridge(ledger_env)

    income = bridge.createIncome(
        {
            "destinationAccountId": bank.id,
            "incomeAccountId": salary.id,
            "amount": "1800,00",
            "date": "2026-08-28",
            "description": "Stipendio agosto",
        }
    )
    assert income["ok"] is True
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 180_000
    income_record = ledger_env.ledger.get_transaction(
        ledger_env.book_id, int(income["data"]["id"])
    )
    assert income_record.kind == "INCOME"
    assert income_record.description == "Stipendio agosto"

    transfer = bridge.createTransfer(
        {
            "sourceAccountId": bank.id,
            "destinationAccountId": cash.id,
            "amount": "100,00",
            "date": "2026-08-28",
            "description": "Prelievo contanti",
        }
    )
    assert transfer["ok"] is True
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 170_000
    assert ledger_env.accounts.native_balance(ledger_env.book_id, cash.id) == 10_000
    transfer_record = ledger_env.ledger.get_transaction(
        ledger_env.book_id, int(transfer["data"]["id"])
    )
    assert transfer_record.kind == "TRANSFER"
    assert transfer_record.description == "Prelievo contanti"

    snapshot = bridge.getSnapshot()
    assert snapshot["ok"] is True
    transactions = snapshot["data"]["transactions"]
    transfer_payload = next(item for item in transactions if item["kind"] == "TRANSFER")
    income_payload = next(item for item in transactions if item["kind"] == "INCOME")

    assert transfer_payload["amountMinor"] == "10000"
    assert transfer_payload["sourceAccountNames"] == ["Conto corrente"]
    assert transfer_payload["destinationAccountNames"] == ["Contanti"]
    assert income_payload["amountMinor"] == "180000"
    assert income_payload["sourceAccountNames"] == []
    assert income_payload["destinationAccountNames"] == ["Conto corrente"]


def test_manual_transfer_rejects_currency_mismatch_without_mutation(ledger_env) -> None:
    eur = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="EUR",
        currency_code="EUR",
        tracking_start_date="2026-08-01",
    )
    usd = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="USD",
        currency_code="USD",
        tracking_start_date="2026-08-01",
    )
    bridge = _bridge(ledger_env)

    result = bridge.createTransfer(
        {
            "sourceAccountId": eur.id,
            "destinationAccountId": usd.id,
            "amount": "10,00",
            "date": "2026-08-28",
        }
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "LedgerValidationError"
    assert ledger_env.accounts.native_balance(ledger_env.book_id, eur.id) == 0
    assert ledger_env.accounts.native_balance(ledger_env.book_id, usd.id) == 0


def test_manual_transaction_ui_is_static_and_backend_capability_driven() -> None:
    index = (ROOT / "ui" / "web" / "index.html").read_text(encoding="utf-8")
    frontend = (ROOT / "ui" / "web" / "manual-transactions.js").read_text(
        encoding="utf-8"
    )
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")

    assert '<script src="manual-transactions.js"></script>' in index
    assert 'id="income-form" class="form-card embedded-form"' in index
    assert 'id="transfer-form" class="form-card embedded-form"' in index
    assert "Nuova entrata" in index
    assert "Nuovo giroconto" in index
    assert 'call("createIncome", data)' in frontend
    assert 'call("createTransfer", data)' in frontend
    assert "source.postingCapabilities?.[kind]" in frontend
    assert 'eligibleCounters(accountId, "INCOME")' in frontend
    assert 'eligibleCounters(sourceId, "TRANSFER")' in frontend
    assert "document.createElement(" not in frontend
    assert "replaceChild(" not in frontend
    assert ".currency ===" not in frontend
    assert "def createIncome" in bridge
    assert "def createTransfer" in bridge


def test_transaction_list_renders_account_flow_and_exact_amount() -> None:
    frontend = (ROOT / "ui" / "web" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "web" / "scroll-regions.css").read_text(
        encoding="utf-8"
    )

    assert "sourceAccountNames" in frontend
    assert "destinationAccountNames" in frontend
    assert 'class="transaction-accounts"' in frontend
    assert 'class="transaction-amount"' in frontend
    assert "money(t.amountMinor, t.currency_code)" in frontend
    assert " → " in frontend
    assert "#transactions-list .transaction-row" in styles
    assert "#recent .transaction-accounts" in styles
    assert "#recent .transaction-amount" in styles
