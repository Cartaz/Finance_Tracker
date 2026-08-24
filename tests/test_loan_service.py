from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.account_service import AccountService
from core.database import Database
from core.errors import LoanError
from core.ledger_service import LedgerService
from core.loan_service import LoanService


@dataclass(slots=True)
class LoanEnv:
    db: Database
    accounts: AccountService
    ledger: LedgerService
    loans: LoanService
    book_id: int
    liability_id: int
    payment_id: int
    funding_id: int
    interest_id: int
    equity_id: int


@pytest.fixture
def loan_env(tmp_path: Path) -> LoanEnv:
    db = Database(tmp_path / "finance.db")
    db.open()
    db.migrate()
    with db.transaction() as conn:
        user_id = int(
            conn.execute(
                "INSERT INTO users(name, created_at, updated_at) VALUES ('User', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        book_id = int(
            conn.execute(
                "INSERT INTO books(name, base_currency_code, created_at, updated_at) VALUES ('Primary', 'EUR', datetime('now'), datetime('now'))"
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO book_members(book_id, user_id, role) VALUES (?, ?, 'OWNER')",
            (book_id, user_id),
        )
    accounts = AccountService(db)
    ledger = LedgerService(db)
    liability = accounts.create_account(
        book_id=book_id,
        account_type="LIABILITY",
        name="Loan",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    payment = accounts.create_account(
        book_id=book_id,
        account_type="ASSET",
        name="Checking",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    funding = accounts.create_account(
        book_id=book_id,
        account_type="ASSET",
        name="Funding",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    interest = accounts.create_account(
        book_id=book_id,
        account_type="EXPENSE",
        name="Loan interest",
    )
    equity = accounts.create_account(
        book_id=book_id,
        account_type="EQUITY",
        name="Opening equity",
    )
    env = LoanEnv(
        db,
        accounts,
        ledger,
        LoanService(db, accounts, ledger),
        book_id,
        liability.id,
        payment.id,
        funding.id,
        interest.id,
        equity.id,
    )
    try:
        yield env
    finally:
        db.close()


def _new_loan(env: LoanEnv, *, rate_bps: int = 1200, term: int = 12):
    return env.loans.create_loan(
        book_id=env.book_id,
        name="Personal loan",
        liability_account_id=env.liability_id,
        payment_account_id=env.payment_id,
        interest_expense_account_id=env.interest_id,
        annual_rate_bps=rate_bps,
        term_months=term,
        first_due_date="2026-02-28",
        mode="NEW_DISBURSEMENT",
        principal_minor=120_000,
        funding_account_id=env.funding_id,
        start_date="2026-01-15",
    )


def test_schema_v8_contains_loans_and_payment_constraints(loan_env: LoanEnv) -> None:
    env = loan_env
    assert env.db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 8
    assert env.db.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='loans'"
    ).fetchone()
    assert env.db.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='loan_payments'"
    ).fetchone()


def test_creation_capabilities_are_backend_owned_and_balance_sensitive(
    loan_env: LoanEnv,
) -> None:
    env = loan_env
    empty = env.loans.creation_capabilities(env.book_id)
    target = next(
        item
        for item in empty["targets"]
        if item["liabilityAccountId"] == env.liability_id
    )
    assert target["allowedModes"] == ["NEW_DISBURSEMENT"]
    assert env.payment_id in target["paymentAccountIds"]
    assert env.interest_id in {
        item["id"] for item in empty["interestExpenseAccounts"]
    }

    env.ledger.create_opening_balance(
        book_id=env.book_id,
        account_id=env.liability_id,
        equity_account_id=env.equity_id,
        quantity_minor=-50_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
    )
    existing = env.loans.creation_capabilities(env.book_id)
    target = next(
        item
        for item in existing["targets"]
        if item["liabilityAccountId"] == env.liability_id
    )
    assert target["allowedModes"] == ["EXISTING_BALANCE"]
    assert target["nativeBalanceMinor"] == -50_000


def test_new_disbursement_is_atomic_and_ledger_owned(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = _new_loan(env)
    assert loan.original_principal_minor == 120_000
    assert loan.origination_transaction_id is not None
    assert env.accounts.native_balance(env.book_id, env.liability_id) == -120_000
    assert env.accounts.native_balance(env.book_id, env.funding_id) == 120_000
    status = env.loans.status(env.book_id, loan.id)
    assert status["outstandingPrincipalMinor"] == 120_000
    assert status["closed"] is False


def test_existing_balance_mode_derives_principal_from_ledger(loan_env: LoanEnv) -> None:
    env = loan_env
    env.ledger.create_opening_balance(
        book_id=env.book_id,
        account_id=env.liability_id,
        equity_account_id=env.equity_id,
        quantity_minor=-75_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
    )
    loan = env.loans.create_loan(
        book_id=env.book_id,
        name="Existing loan",
        liability_account_id=env.liability_id,
        payment_account_id=env.payment_id,
        interest_expense_account_id=env.interest_id,
        annual_rate_bps=500,
        term_months=24,
        first_due_date="2026-02-15",
        mode="EXISTING_BALANCE",
    )
    assert loan.original_principal_minor == 75_000
    assert loan.origination_transaction_id is None


def test_amortization_plan_is_deterministic_and_reaches_zero(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = _new_loan(env)
    first = env.loans.amortization_plan(env.book_id, loan.id)
    second = env.loans.amortization_plan(env.book_id, loan.id)
    assert first == second
    assert len(first["rows"]) == 12
    assert sum(row["principalMinor"] for row in first["rows"]) == 120_000
    assert first["rows"][-1]["remainingPrincipalMinor"] == 0
    assert first["totalPaidMinor"] == 120_000 + first["totalInterestMinor"]


def test_month_end_due_dates_keep_contract_anchor(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = env.loans.create_loan(
        book_id=env.book_id,
        name="Month end",
        liability_account_id=env.liability_id,
        payment_account_id=env.payment_id,
        interest_expense_account_id=env.interest_id,
        annual_rate_bps=0,
        term_months=3,
        first_due_date="2026-01-31",
        mode="NEW_DISBURSEMENT",
        principal_minor=30_000,
        funding_account_id=env.funding_id,
        start_date="2026-01-02",
    )
    plan = env.loans.amortization_plan(env.book_id, loan.id)
    assert [row["dueDate"] for row in plan["rows"]] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
    ]


def test_payment_posts_principal_and_interest_without_second_balance(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = _new_loan(env)
    env.ledger.create_opening_balance(
        book_id=env.book_id,
        account_id=env.payment_id,
        equity_account_id=env.equity_id,
        quantity_minor=200_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
    )
    before = env.accounts.native_balance(env.book_id, env.liability_id)
    payment = env.loans.post_next_payment(book_id=env.book_id, loan_id=loan.id)
    after = env.accounts.native_balance(env.book_id, env.liability_id)
    assert payment["interestMinor"] == 1_200
    assert payment["principalMinor"] > 0
    assert payment["paymentMinor"] == payment["principalMinor"] + 1_200
    assert after == before + payment["principalMinor"]
    assert payment["status"]["outstandingPrincipalMinor"] == -after
    assert env.loans.list_payments(env.book_id, loan.id)[0]["transactionId"] == payment[
        "transactionId"
    ]


def test_zero_interest_payment_uses_principal_only(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = _new_loan(env, rate_bps=0, term=12)
    env.ledger.create_opening_balance(
        book_id=env.book_id,
        account_id=env.payment_id,
        equity_account_id=env.equity_id,
        quantity_minor=200_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
    )
    payment = env.loans.post_next_payment(book_id=env.book_id, loan_id=loan.id)
    assert payment["interestMinor"] == 0
    assert payment["paymentMinor"] == payment["principalMinor"]


def test_stale_archived_contract_fails_closed(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = _new_loan(env)
    env.accounts.set_archived(env.book_id, env.interest_id, True)
    with pytest.raises(LoanError, match="interest account"):
        env.loans.status(env.book_id, loan.id)


def test_duplicate_liability_is_rejected_as_domain_error(loan_env: LoanEnv) -> None:
    env = loan_env
    _new_loan(env)
    with pytest.raises(LoanError, match="already linked"):
        env.loans.create_loan(
            book_id=env.book_id,
            name="Duplicate",
            liability_account_id=env.liability_id,
            payment_account_id=env.payment_id,
            interest_expense_account_id=env.interest_id,
            annual_rate_bps=500,
            term_months=12,
            first_due_date="2026-03-01",
            mode="EXISTING_BALANCE",
        )


def test_invalid_rate_type_is_rejected(loan_env: LoanEnv) -> None:
    env = loan_env
    with pytest.raises(LoanError, match="annual_rate_bps"):
        env.loans.create_loan(
            book_id=env.book_id,
            name="Bad",
            liability_account_id=env.liability_id,
            payment_account_id=env.payment_id,
            interest_expense_account_id=env.interest_id,
            annual_rate_bps=1.5,  # type: ignore[arg-type]
            term_months=12,
            first_due_date="2026-02-28",
        )


def test_long_contract_projection_is_read_only(loan_env: LoanEnv) -> None:
    env = loan_env
    loan = _new_loan(env, rate_bps=350, term=600)
    transactions_before = env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0]
    balance_before = env.accounts.native_balance(env.book_id, env.liability_id)
    first = env.loans.amortization_plan(env.book_id, loan.id)
    second = env.loans.amortization_plan(env.book_id, loan.id)
    assert first == second
    assert len(first["rows"]) == 600
    assert env.db.connection.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == transactions_before
    assert env.accounts.native_balance(env.book_id, env.liability_id) == balance_before
