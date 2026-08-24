from __future__ import annotations

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from ui.bridge import Bridge


def test_reconciliation_bridge_preserves_large_imported_minor_units(tmp_path) -> None:
    db = Database(tmp_path / "m6-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    try:
        controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
        book_id = int(controller.initial_state()["book"]["id"])
        bank = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Bank",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        bridge = Bridge(controller)
        imported = bridge.importCsv(
            {
                "accountId": bank.id,
                "sourceName": "Bank",
                "reviewMode": "FULL_REVIEW",
                "csvText": (
                    "date,amount,currency,description,external_id\n"
                    "2026-06-01,90071992547409.93,EUR,Huge,huge-1\n"
                ),
            }
        )
        assert imported["ok"] is True
        rows = bridge.getImportBatchRows({"batchId": imported["data"]["batchId"]})
        assert rows["ok"] is True
        amount = rows["data"][0]["amount_minor"]
        assert amount == "9007199254740993"
        assert isinstance(amount, str)
    finally:
        db.close()
