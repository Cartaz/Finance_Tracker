from __future__ import annotations

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from ui.bridge import Bridge


def _bridge_env(tmp_path):
    db = Database(tmp_path / "m6-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    return db, accounts, ledger, controller, Bridge(controller)


def test_reconciliation_bridge_preserves_large_imported_minor_units(tmp_path) -> None:
    db, accounts, _ledger, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        bank = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Bank",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
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


def test_reconciliation_bridge_posts_expense_refund_and_transfer_explicitly(tmp_path) -> None:
    db, accounts, _ledger, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        bank = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Bank",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        savings = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Savings",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        expense = accounts.create_account(
            book_id=book_id,
            account_type="EXPENSE",
            name="Expense",
        )
        imported = bridge.importCsv(
            {
                "accountId": bank.id,
                "sourceName": "Bank",
                "reviewMode": "FULL_REVIEW",
                "csvText": (
                    "date,amount,currency,description,external_id\n"
                    "2026-06-02,-10.00,EUR,Purchase,p-1\n"
                    "2026-06-03,2.00,EUR,Refund,p-2\n"
                    "2026-06-04,-5.00,EUR,Move to savings,p-3\n"
                ),
            }
        )
        rows = bridge.getImportBatchRows({"batchId": imported["data"]["batchId"]})["data"]

        expense_result = bridge.postImportRow(
            {
                "rowId": rows[0]["id"],
                "postingKind": "EXPENSE",
                "counterAccountId": expense.id,
            }
        )
        refund_result = bridge.postImportRow(
            {
                "rowId": rows[1]["id"],
                "postingKind": "REFUND",
                "counterAccountId": expense.id,
            }
        )
        transfer_result = bridge.postImportRow(
            {
                "rowId": rows[2]["id"],
                "postingKind": "TRANSFER",
                "counterAccountId": savings.id,
            }
        )
        assert expense_result["ok"] is True
        assert refund_result["ok"] is True
        assert transfer_result["ok"] is True
        assert accounts.native_balance(book_id, bank.id) == -1300
        assert accounts.native_balance(book_id, savings.id) == 500

        kinds = [
            row[0]
            for row in db.connection.execute(
                "SELECT kind FROM transactions ORDER BY id"
            ).fetchall()
        ]
        assert kinds == ["EXPENSE", "REFUND", "TRANSFER"]
    finally:
        db.close()
