from __future__ import annotations

import pytest

from core.account_service import AccountService
from core.book_service import BookService
from core.database import Database
from core.errors import LoanError
from core.ledger_service import LedgerService
from core.loan_service import LoanService


def _env(tmp_path):
    db = Database(tmp_path / "loans-generalized.db")
    db.open()
    db.migrate()
    book = BookService(db).create_personal_book(
        user_name="User", book_name="Book", currency_code="EUR"
    )
    accounts = AccountService(db)
    ledger = LedgerService(db)
    liability = accounts.create_account(
        book_id=book.id,
        account_type="LIABILITY",
        name="Loan",
        currency_code="EUR",
        tracking_start_date="2025-01-01",
    )
    bank = accounts.create_account(
        book_id=book.id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2025-01-01",
    )
    interest = accounts.create_account(
        book_id=book.id,
        account_type="EXPENSE",
        name="Interest",
    )
    return db, book.id, liability.id, bank.id, interest.id, LoanService(db, accounts, ledger)


def _loan(
    service: LoanService,
    *,
    book_id: int,
    liability_id: int,
    bank_id: int,
    interest_id: int,
    amortization_type: str = "FRENCH",
    rate_type: str = "FIXED",
    recast_strategy: str = "REDUCE_PAYMENT",
    annual_rate_bps: int = 600,
):
    return service.create_loan(
        book_id=book_id,
        name=f"{rate_type}-{amortization_type}",
        liability_account_id=liability_id,
        payment_account_id=bank_id,
        interest_expense_account_id=interest_id,
        annual_rate_bps=annual_rate_bps,
        term_months=12,
        first_due_date="2026-02-28",
        mode="NEW_DISBURSEMENT",
        principal_minor=120_000,
        funding_account_id=bank_id,
        start_date="2026-01-01",
        rate_type=rate_type,
        amortization_type=amortization_type,
        recast_strategy=recast_strategy,
    )


@pytest.mark.parametrize("amortization", ["FRENCH", "ITALIAN", "BULLET"])
def test_each_amortization_reaches_zero_without_shadow_balance(tmp_path, amortization) -> None:
    db, book_id, liability_id, bank_id, interest_id, service = _env(tmp_path)
    try:
        loan = _loan(
            service,
            book_id=book_id,
            liability_id=liability_id,
            bank_id=bank_id,
            interest_id=interest_id,
            amortization_type=amortization,
        )
        plan = service.amortization_plan(book_id, loan.id)
        assert plan["rows"][-1]["remainingPrincipalMinor"] == 0
        assert sum(int(row["principalMinor"]) for row in plan["rows"]) == 120_000
        if amortization == "ITALIAN":
            assert [int(row["principalMinor"]) for row in plan["rows"][:-1]] == [10_000] * 11
            assert int(plan["rows"][0]["paymentMinor"]) > int(plan["rows"][-1]["paymentMinor"])
        if amortization == "BULLET":
            assert all(int(row["principalMinor"]) == 0 for row in plan["rows"][:-1])
            assert int(plan["rows"][-1]["principalMinor"]) == 120_000
    finally:
        db.close()


def test_variable_rate_history_changes_only_future_installments(tmp_path) -> None:
    db, book_id, liability_id, bank_id, interest_id, service = _env(tmp_path)
    try:
        loan = _loan(
            service,
            book_id=book_id,
            liability_id=liability_id,
            bank_id=bank_id,
            interest_id=interest_id,
            rate_type="VARIABLE",
            annual_rate_bps=400,
        )
        service.set_variable_rate(
            book_id=book_id,
            loan_id=loan.id,
            effective_date="2026-07-01",
            annual_rate_bps=900,
        )
        plan = service.amortization_plan(book_id, loan.id)
        before = [row for row in plan["rows"] if str(row["dueDate"]) < "2026-07-01"]
        after = [row for row in plan["rows"] if str(row["dueDate"]) >= "2026-07-01"]
        assert before and after
        assert {int(row["annualRateBps"]) for row in before} == {400}
        assert {int(row["annualRateBps"]) for row in after} == {900}
        assert service.list_rate_revisions(book_id, loan.id) == [
            {"effectiveDate": "2026-01-01", "annualRateBps": 400},
            {"effectiveDate": "2026-07-01", "annualRateBps": 900},
        ]
    finally:
        db.close()


def test_fixed_loan_rejects_rate_revision(tmp_path) -> None:
    db, book_id, liability_id, bank_id, interest_id, service = _env(tmp_path)
    try:
        loan = _loan(
            service,
            book_id=book_id,
            liability_id=liability_id,
            bank_id=bank_id,
            interest_id=interest_id,
        )
        with pytest.raises(LoanError, match="VARIABLE"):
            service.set_variable_rate(
                book_id=book_id,
                loan_id=loan.id,
                effective_date="2026-07-01",
                annual_rate_bps=900,
            )
    finally:
        db.close()


def test_custom_payment_recasts_future_payment_and_uses_ledger_balance(tmp_path) -> None:
    db, book_id, liability_id, bank_id, interest_id, service = _env(tmp_path)
    try:
        loan = _loan(
            service,
            book_id=book_id,
            liability_id=liability_id,
            bank_id=bank_id,
            interest_id=interest_id,
            recast_strategy="REDUCE_PAYMENT",
        )
        initial = service.status(book_id, loan.id)
        scheduled = int(initial["nextPaymentMinor"])
        custom = service.post_custom_payment(
            book_id=book_id,
            loan_id=loan.id,
            amount_minor=scheduled + 20_000,
            recast_strategy="REDUCE_PAYMENT",
        )
        assert custom["paymentKind"] == "CUSTOM"
        assert int(custom["principalMinor"]) > 20_000
        after = service.status(book_id, loan.id)
        assert int(after["outstandingPrincipalMinor"]) == (
            120_000 - int(custom["principalMinor"])
        )
        assert int(after["nextPaymentMinor"]) < scheduled
    finally:
        db.close()


def test_custom_payment_below_schedule_fails_closed_instead_of_inventing_arrears(tmp_path) -> None:
    db, book_id, liability_id, bank_id, interest_id, service = _env(tmp_path)
    try:
        loan = _loan(
            service,
            book_id=book_id,
            liability_id=liability_id,
            bank_id=bank_id,
            interest_id=interest_id,
            recast_strategy="REDUCE_TERM",
        )
        scheduled = int(service.status(book_id, loan.id)["nextPaymentMinor"])
        with pytest.raises(LoanError, match="arrears semantics"):
            service.post_custom_payment(
                book_id=book_id,
                loan_id=loan.id,
                amount_minor=scheduled - 1,
                recast_strategy="REDUCE_TERM",
            )
    finally:
        db.close()


def test_incompatible_recast_policy_is_rejected_at_contract_creation(tmp_path) -> None:
    db, book_id, liability_id, bank_id, interest_id, service = _env(tmp_path)
    try:
        with pytest.raises(LoanError, match="not supported"):
            _loan(
                service,
                book_id=book_id,
                liability_id=liability_id,
                bank_id=bank_id,
                interest_id=interest_id,
                rate_type="VARIABLE",
                amortization_type="FRENCH",
                recast_strategy="REDUCE_TERM",
            )
    finally:
        db.close()


def test_capabilities_expose_policy_compatibility_matrix(tmp_path) -> None:
    db, book_id, _, _, _, service = _env(tmp_path)
    try:
        combinations = service.creation_capabilities(book_id)["policyCombinations"]
        variable_french = next(
            item
            for item in combinations
            if item["rateType"] == "VARIABLE"
            and item["amortizationType"] == "FRENCH"
        )
        fixed_italian = next(
            item
            for item in combinations
            if item["rateType"] == "FIXED"
            and item["amortizationType"] == "ITALIAN"
        )
        assert variable_french["recastStrategies"] == ["REDUCE_PAYMENT"]
        assert fixed_italian["recastStrategies"] == ["REDUCE_PAYMENT", "REDUCE_TERM"]
    finally:
        db.close()
