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
    db = Database(tmp_path / "m10-controller.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    controller.setup({"userName": "User", "bookName": "Book", "currency": "EUR"})
    return db, accounts, controller, Bridge(controller)


def _accounts(accounts: AccountService, book_id: int):
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
    return liability, bank, interest


def test_loan_bridge_preserves_money_and_bps_precision(tmp_path) -> None:
    db, accounts, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        liability, bank, interest = _accounts(accounts, book_id)
        result = bridge.createLoan(
            {
                "name": "Large loan",
                "mode": "NEW_DISBURSEMENT",
                "liabilityAccountId": liability.id,
                "paymentAccountId": bank.id,
                "interestExpenseAccountId": interest.id,
                "annualRate": "5,25",
                "termMonths": "12",
                "firstDueDate": "2026-02-15",
                "fundingAccountId": bank.id,
                "principal": "90071992547409,93",
                "startDate": "2026-01-15",
            }
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["originalPrincipalMinor"] == "9007199254740993"
        assert data["outstandingPrincipalMinor"] == "9007199254740993"
        assert data["annualRateBps"] == "525"
        assert isinstance(data["fixedPaymentMinor"], str)

        listed = bridge.listLoans()
        assert listed["ok"] is True
        assert listed["data"][0]["originalPrincipalMinor"] == "9007199254740993"

        plan = bridge.getLoanPlan({"loanId": data["id"]})
        assert plan["ok"] is True
        assert isinstance(plan["data"]["rows"][0]["principalMinor"], str)
        assert isinstance(plan["data"]["totalInterestMinor"], str)
    finally:
        db.close()


def test_loan_bridge_rejects_signed_principal_and_signed_rate(tmp_path) -> None:
    db, accounts, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        liability, bank, interest = _accounts(accounts, book_id)
        common = {
            "name": "Loan",
            "mode": "NEW_DISBURSEMENT",
            "liabilityAccountId": liability.id,
            "paymentAccountId": bank.id,
            "interestExpenseAccountId": interest.id,
            "annualRate": "5,25",
            "termMonths": "12",
            "firstDueDate": "2026-02-15",
            "fundingAccountId": bank.id,
            "principal": "1000,00",
            "startDate": "2026-01-15",
        }
        signed_principal = bridge.createLoan({**common, "principal": "-1000,00"})
        assert signed_principal["ok"] is False
        assert signed_principal["error"]["code"] == "MoneyParseError"

        signed_rate = bridge.createLoan({**common, "annualRate": "+5,25"})
        assert signed_rate["ok"] is False
        assert signed_rate["error"]["code"] == "LoanError"
    finally:
        db.close()


def test_post_next_loan_payment_updates_ledger_and_transport(tmp_path) -> None:
    db, accounts, controller, bridge = _bridge_env(tmp_path)
    try:
        book_id = int(controller.initial_state()["book"]["id"])
        liability, bank, interest = _accounts(accounts, book_id)
        created = bridge.createLoan(
            {
                "name": "Loan",
                "mode": "NEW_DISBURSEMENT",
                "liabilityAccountId": liability.id,
                "paymentAccountId": bank.id,
                "interestExpenseAccountId": interest.id,
                "annualRate": "12,00",
                "termMonths": "12",
                "firstDueDate": "2026-02-15",
                "fundingAccountId": bank.id,
                "principal": "1200,00",
                "startDate": "2026-01-15",
            }
        )
        assert created["ok"] is True
        loan_id = created["data"]["id"]
        before = accounts.native_balance(book_id, liability.id)

        payment = bridge.postNextLoanPayment({"loanId": loan_id})
        assert payment["ok"] is True
        payload = payment["data"]["payment"]
        assert payload["interestMinor"] == "1200"
        assert isinstance(payload["principalMinor"], str)
        assert accounts.native_balance(book_id, liability.id) > before
        assert payment["data"]["state"]["book"]["id"] == book_id
    finally:
        db.close()
