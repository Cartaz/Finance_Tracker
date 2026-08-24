from __future__ import annotations

from pathlib import Path

from core.account_service import AccountService
from core.database import Database
from core.forecast_service import ForecastService
from core.fx_service import FxService
from core.ledger_service import LedgerService
from core.loan_service import LoanService
from core.payee_service import PayeeService
from core.scheduled_transaction_service import ScheduledTransactionService


def test_forecast_includes_loan_installments_without_double_counting_principal(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "forecast-loan.db")
    db.open()
    db.migrate()
    try:
        with db.transaction() as conn:
            user_id = int(
                conn.execute(
                    "INSERT INTO users(name, created_at, updated_at) VALUES ('User', datetime('now'), datetime('now'))"
                ).lastrowid
            )
            book_id = int(
                conn.execute(
                    "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('Book','EUR',datetime('now'),datetime('now'))"
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO book_members(book_id,user_id,role) VALUES (?,?,'OWNER')",
                (book_id, user_id),
            )
        accounts = AccountService(db)
        ledger = LedgerService(db)
        payees = PayeeService(db)
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
        loans = LoanService(db, accounts, ledger)
        loan = loans.create_loan(
            book_id=book_id,
            name="Loan",
            liability_account_id=liability.id,
            payment_account_id=bank.id,
            interest_expense_account_id=interest.id,
            annual_rate_bps=1200,
            term_months=12,
            first_due_date="2026-02-15",
            mode="NEW_DISBURSEMENT",
            principal_minor=120_000,
            funding_account_id=bank.id,
            start_date="2026-01-15",
        )
        scheduled = ScheduledTransactionService(db, accounts, ledger, payees)
        forecast = ForecastService(scheduled, FxService(db), loans)

        report = forecast.cash_flow_forecast(
            book_id=book_id,
            start_date="2026-02-01",
            end_date="2026-02-28",
        )

        assert report["scheduledOnly"] is False
        assert report["sources"] == ["SCHEDULED_TRANSACTIONS", "LOAN_INSTALLMENTS"]
        assert report["loanInstallmentCount"] == 1
        occurrence = report["occurrences"][0]
        assert occurrence["source"] == "LOAN_INSTALLMENT"
        assert occurrence["loanId"] == loan.id
        assert occurrence["amountMinor"] == occurrence["principalMinor"] + occurrence["interestMinor"]
        assert occurrence["interestMinor"] == 1_200
        assert occurrence["baseAmountMinor"] == occurrence["amountMinor"]
        assert occurrence["flowBaseAmountMinor"] == occurrence["interestMinor"]
        assert report["totalOutflowMinor"] == 1_200
        assert report["totalNetMinor"] == -1_200
    finally:
        db.close()


def test_loan_projection_and_posting_share_final_installment_math(tmp_path: Path) -> None:
    db = Database(tmp_path / "final-installment.db")
    db.open()
    db.migrate()
    try:
        with db.transaction() as conn:
            user_id = int(conn.execute("INSERT INTO users(name,created_at,updated_at) VALUES ('U',datetime('now'),datetime('now'))").lastrowid)
            book_id = int(conn.execute("INSERT INTO books(name,base_currency_code,created_at,updated_at) VALUES ('B','EUR',datetime('now'),datetime('now'))").lastrowid)
            conn.execute("INSERT INTO book_members(book_id,user_id,role) VALUES (?,?,'OWNER')", (book_id, user_id))
        accounts = AccountService(db)
        ledger = LedgerService(db)
        liability = accounts.create_account(book_id=book_id, account_type="LIABILITY", name="L", currency_code="EUR", tracking_start_date="2026-01-01")
        bank = accounts.create_account(book_id=book_id, account_type="ASSET", name="A", currency_code="EUR", tracking_start_date="2026-01-01")
        interest = accounts.create_account(book_id=book_id, account_type="EXPENSE", name="I")
        loans = LoanService(db, accounts, ledger)
        loan = loans.create_loan(
            book_id=book_id,
            name="Short",
            liability_account_id=liability.id,
            payment_account_id=bank.id,
            interest_expense_account_id=interest.id,
            annual_rate_bps=777,
            term_months=2,
            first_due_date="2026-02-15",
            mode="NEW_DISBURSEMENT",
            principal_minor=10_001,
            funding_account_id=bank.id,
            start_date="2026-01-15",
        )
        first = loans.post_next_payment(book_id=book_id, loan_id=loan.id)
        projected = loans.project_payments(book_id=book_id, start_date="2026-03-01", end_date="2026-03-31")
        assert len(projected) == 1
        last = projected[0]
        posted = loans.post_next_payment(book_id=book_id, loan_id=loan.id)
        assert posted["principalMinor"] == last["principalMinor"]
        assert posted["interestMinor"] == last["interestMinor"]
        assert posted["paymentMinor"] == last["amountMinor"]
        assert posted["status"]["closed"] is True
        assert posted["status"]["outstandingPrincipalMinor"] == 0
        assert first["status"]["closed"] is False
    finally:
        db.close()
