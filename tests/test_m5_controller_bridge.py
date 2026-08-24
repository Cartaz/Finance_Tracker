from __future__ import annotations

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.fx_service import FxService
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from core.reporting_service import ReportingService
from ui.bridge import Bridge


def _controller(tmp_path):
    db = Database(tmp_path / "controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    fx = FxService(db)
    reporting = ReportingService(db, fx, accounts)
    controller = AppController(
        db,
        Settings(),
        accounts,
        ledger,
        books,
        payees,
        fx,
        reporting,
    )
    return db, accounts, ledger, controller


def test_initial_state_exposes_all_canonical_currency_specs(tmp_path) -> None:
    db, _accounts, _ledger, controller = _controller(tmp_path)
    try:
        initial = controller.initial_state()
        by_code = {item["code"]: item["minorUnitDigits"] for item in initial["currencies"]}
        assert by_code == {
            "BHD": 3,
            "CHF": 2,
            "EUR": 2,
            "GBP": 2,
            "JPY": 0,
            "KRW": 0,
            "KWD": 3,
            "OMR": 3,
            "USD": 2,
        }

        controller.setup({"userName": "User", "bookName": "Book", "currency": "KWD"})
        assert controller.initial_state()["book"]["currency"] == "KWD"
    finally:
        db.close()


def test_controller_and_bridge_transport_minor_units_as_strings(tmp_path) -> None:
    db, accounts, ledger, controller = _controller(tmp_path)
    try:
        controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
        book_id = int(controller.initial_state()["book"]["id"])
        asset = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Large",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
            tracking_start_time="00:00:00",
        )
        equity = accounts.create_account(
            book_id=book_id,
            account_type="EQUITY",
            name="Equity",
        )
        huge = 9_007_199_254_740_993
        ledger.create_opening_balance(
            book_id=book_id,
            account_id=asset.id,
            equity_account_id=equity.id,
            quantity_minor=huge,
            currency_code="EUR",
            transaction_date="2026-01-01",
            transaction_time="00:00:00",
        )

        snapshot = controller.snapshot()
        balance = next(item for item in snapshot["accounts"] if item["id"] == asset.id)
        assert balance["balanceMinor"] == str(huge)

        dashboard = controller.dashboard(
            {
                "startDate": "2026-01-01",
                "endDate": "2026-01-31",
                "asOfDate": "2026-01-31",
            }
        )
        assert dashboard["overview"]["netWorthMinor"] == str(huge)
        assert isinstance(dashboard["overview"]["netWorthMinor"], str)

        bridge = Bridge(controller)
        bridged = bridge.getDashboard(
            {
                "startDate": "2026-01-01",
                "endDate": "2026-01-31",
                "asOfDate": "2026-01-31",
            }
        )
        assert bridged["ok"] is True
        assert bridged["data"]["overview"]["netWorthMinor"] == str(huge)
    finally:
        db.close()


def test_bridge_returns_domain_errors_for_invalid_reporting_and_fx(tmp_path) -> None:
    db, _accounts, _ledger, controller = _controller(tmp_path)
    try:
        controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
        bridge = Bridge(controller)
        bad_report = bridge.getDashboard(
            {
                "startDate": "2026-02-01",
                "endDate": "2026-01-01",
                "asOfDate": "2026-01-31",
            }
        )
        assert bad_report["ok"] is False
        assert bad_report["error"]["code"] == "ReportingError"

        bad_fx = bridge.setFxRate(
            {"currency": "USD", "date": "bad", "rate": "1.2"}
        )
        assert bad_fx["ok"] is False
        assert bad_fx["error"]["code"] == "FxRateError"
    finally:
        db.close()
