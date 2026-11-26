from __future__ import annotations

from core.account_service import AccountService
from core.book_service import BookService
from core.database import Database
from core.ledger_service import LedgerService
from core.loan_service import LoanService


def test_bullet_interest_payment_does_not_reduce_principal_until_maturity(tmp_path) -> None:
    db = Database(tmp_path / "bullet.db")
    db.open()
    db.migrate()
    try:
        book = BookService(db).create_personal_book(
            user_name="User", book_name="Book", currency_code="EUR"
        )
        accounts = AccountService(db)
        ledger = LedgerService(db)
        liability = accounts.create_account(
            book_id=book.id,
            account_type="LIABILITY",
            name="Bullet",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        bank = accounts.create_account(
            book_id=book.id,
            account_type="ASSET",
            name="Bank",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
        )
        interest = accounts.create_account(
            book_id=book.id,
            account_type="EXPENSE",
            name="Interest",
        )
        service = LoanService(db, accounts, ledger)
        loan = service.create_loan(
            book_id=book.id,
            name="Bullet loan",
            liability_account_id=liability.id,
            payment_account_id=bank.id,
            interest_expense_account_id=interest.id,
            annual_rate_bps=1200,
            term_months=3,
            first_due_date="2026-02-01",
            mode="NEW_DISBURSEMENT",
            principal_minor=90_000,
            funding_account_id=bank.id,
            start_date="2026-01-02",
            amortization_type="BULLET",
        )
        before = accounts.native_balance(book.id, liability.id)
        first = service.post_next_payment(book_id=book.id, loan_id=loan.id)
        assert first["principalMinor"] == 0
        assert first["interestMinor"] == 900
        assert first["paymentMinor"] == 900
        assert accounts.native_balance(book.id, liability.id) == before

        second = service.post_next_payment(book_id=book.id, loan_id=loan.id)
        assert second["principalMinor"] == 0
        final = service.post_next_payment(book_id=book.id, loan_id=loan.id)
        assert final["principalMinor"] == 90_000
        assert final["status"]["closed"] is True
        assert accounts.native_balance(book.id, liability.id) == 0
    finally:
        db.close()
