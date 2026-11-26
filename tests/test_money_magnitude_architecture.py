"""Every user-entered amount is an unsigned magnitude.

Direction belongs to the posting kind; a typed sign must be refused at every
entry point instead of silently flipping or being ignored.
"""

from __future__ import annotations

import pytest

from config.settings import Settings
from core.composition import build_controller
from core.database import Database
from core.errors import MoneyParseError


@pytest.fixture
def app(tmp_path):
    database = Database(tmp_path / "magnitude.db")
    database.migrate()
    controller = build_controller(database, Settings())
    controller.setup({"userName": "u", "bookName": "b", "currency": "EUR"})
    ids = {
        "bank": controller.create_account(
            {"type": "ASSET", "name": "Bank", "currency": "EUR",
             "trackingStartDate": "2026-01-01", "openingBalance": "5000"}
        )["id"],
        "cash": controller.create_account(
            {"type": "ASSET", "name": "Cash", "currency": "EUR", "trackingStartDate": "2026-01-01"}
        )["id"],
        "debt": controller.create_account(
            {"type": "LIABILITY", "name": "Debt", "currency": "EUR", "trackingStartDate": "2026-01-01"}
        )["id"],
        "food": controller.create_account({"type": "EXPENSE", "name": "Food"})["id"],
        "salary": controller.create_account({"type": "INCOME", "name": "Salary"})["id"],
    }
    try:
        yield controller, ids
    finally:
        database.close()


def _requests(ids, loan_id):
    return {
        "expense": ("create_expense", {"sourceAccountId": ids["bank"], "categoryAccountId": ids["food"], "date": "2026-03-01"}),
        "income": ("create_income", {"destinationAccountId": ids["bank"], "incomeAccountId": ids["salary"], "date": "2026-03-01"}),
        "transfer": ("create_transfer", {"sourceAccountId": ids["bank"], "destinationAccountId": ids["cash"], "date": "2026-03-01"}),
        "budget": ("set_budget", {"categoryAccountId": ids["food"], "period": "2026-03"}),
        "schedule": ("create_scheduled_transaction", {"kind": "EXPENSE", "sourceAccountId": ids["bank"], "counterAccountId": ids["food"], "frequency": "MONTHLY", "interval": "1", "startDate": "2026-03-01"}),
        "opening balance": ("create_account", {"type": "ASSET", "name": "Other", "currency": "EUR", "trackingStartDate": "2026-01-01"}),
        "custom loan payment": ("post_custom_loan_payment", {"loanId": loan_id}),
    }


@pytest.mark.parametrize("sign", ["-", "+"])
@pytest.mark.parametrize(
    "entry",
    ["expense", "income", "transfer", "budget", "schedule", "opening balance", "custom loan payment"],
)
def test_signed_amounts_are_refused_everywhere(app, entry, sign) -> None:
    controller, ids = app
    loan = controller.create_loan(
        {"name": "Loan", "mode": "NEW_DISBURSEMENT", "liabilityAccountId": ids["debt"],
         "paymentAccountId": ids["bank"], "fundingAccountId": ids["bank"],
         "interestExpenseAccountId": ids["food"], "annualRate": "5", "termMonths": "12",
         "principal": "1200", "startDate": "2026-02-01", "firstDueDate": "2026-03-01"}
    )
    method, payload = _requests(ids, loan["id"])[entry]
    field = "openingBalance" if entry == "opening balance" else "amount"
    before = controller.snapshot()
    with pytest.raises(MoneyParseError, match="sign"):
        getattr(controller, method)({**payload, field: f"{sign}10"})
    assert controller.snapshot() == before


@pytest.mark.parametrize("sign", ["-", "+"])
def test_signed_loan_principal_is_refused(app, sign) -> None:
    controller, ids = app
    with pytest.raises(MoneyParseError, match="sign"):
        controller.create_loan(
            {"name": "Loan", "mode": "NEW_DISBURSEMENT", "liabilityAccountId": ids["debt"],
             "paymentAccountId": ids["bank"], "fundingAccountId": ids["bank"],
             "interestExpenseAccountId": ids["food"], "annualRate": "5", "termMonths": "12",
             "principal": f"{sign}1200", "startDate": "2026-02-01", "firstDueDate": "2026-03-01"}
        )
