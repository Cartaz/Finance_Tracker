from __future__ import annotations

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.payee_service import PayeeService
from ui.bridge import Bridge


def _env(tmp_path):
    db = Database(tmp_path / "generalized-bridge.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    controller = AppController(
        db,
        Settings(),
        accounts,
        ledger,
        BookService(db),
        PayeeService(db),
    )
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    book_id = int(controller.initial_state()["book"]["id"])
    liability = accounts.create_account(
        book_id=book_id,
        account_type="LIABILITY",
        name="Loan",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    bank = accounts.create_account(
        book_id=book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    interest = accounts.create_account(
        book_id=book_id,
        account_type="EXPENSE",
        name="Interest",
    )
    return db, accounts, Bridge(controller), book_id, liability, bank, interest


def test_bridge_creates_variable_italian_loan_and_updates_rate(tmp_path) -> None:
    db, _, bridge, _, liability, bank, interest = _env(tmp_path)
    try:
        capabilities = bridge.getLoanCapabilities()
        assert capabilities["ok"] is True
        assert capabilities["data"]["rateTypes"] == ["FIXED", "VARIABLE"]
        assert capabilities["data"]["amortizationTypes"] == [
            "FRENCH",
            "ITALIAN",
            "BULLET",
        ]

        created = bridge.createLoan(
            {
                "name": "Variable Italian",
                "mode": "NEW_DISBURSEMENT",
                "liabilityAccountId": liability.id,
                "paymentAccountId": bank.id,
                "interestExpenseAccountId": interest.id,
                "rateType": "VARIABLE",
                "amortizationType": "ITALIAN",
                "recastStrategy": "REDUCE_PAYMENT",
                "annualRate": "4,00",
                "termMonths": "12",
                "firstDueDate": "2026-02-15",
                "fundingAccountId": bank.id,
                "principal": "12000,00",
                "startDate": "2026-01-15",
            }
        )
        assert created["ok"] is True
        loan_id = created["data"]["id"]
        assert created["data"]["rateType"] == "VARIABLE"
        assert created["data"]["amortizationType"] == "ITALIAN"
        assert created["data"]["currentAnnualRateBps"] == "400"

        revised = bridge.setLoanVariableRate(
            {"loanId": loan_id, "effectiveDate": "2026-07-01", "annualRate": "8,50"}
        )
        assert revised["ok"] is True
        assert revised["data"]["annualRateBps"] == "850"
        history = bridge.getLoanRateRevisions({"loanId": loan_id})
        assert history["ok"] is True
        assert [item["annualRateBps"] for item in history["data"]] == ["400", "850"]
    finally:
        db.close()


def test_custom_payment_uses_unsigned_magnitude_and_recasts(tmp_path) -> None:
    db, accounts, bridge, book_id, liability, bank, interest = _env(tmp_path)
    try:
        created = bridge.createLoan(
            {
                "name": "Flexible payment",
                "mode": "NEW_DISBURSEMENT",
                "liabilityAccountId": liability.id,
                "paymentAccountId": bank.id,
                "interestExpenseAccountId": interest.id,
                "rateType": "FIXED",
                "amortizationType": "FRENCH",
                "recastStrategy": "REDUCE_PAYMENT",
                "annualRate": "6,00",
                "termMonths": "12",
                "firstDueDate": "2026-02-15",
                "fundingAccountId": bank.id,
                "principal": "12000,00",
                "startDate": "2026-01-15",
            }
        )
        assert created["ok"] is True
        loan_id = created["data"]["id"]
        before = accounts.native_balance(book_id, liability.id)

        signed = bridge.postCustomLoanPayment(
            {"loanId": loan_id, "amount": "-1500,00", "recastStrategy": "REDUCE_PAYMENT"}
        )
        assert signed["ok"] is False
        assert signed["error"]["code"] == "MoneyParseError"

        custom = bridge.postCustomLoanPayment(
            {"loanId": loan_id, "amount": "1500,00", "recastStrategy": "REDUCE_PAYMENT"}
        )
        assert custom["ok"] is True
        assert custom["data"]["payment"]["paymentKind"] == "CUSTOM"
        assert isinstance(custom["data"]["payment"]["principalMinor"], str)
        assert accounts.native_balance(book_id, liability.id) > before
    finally:
        db.close()
