from __future__ import annotations

from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.fx_service import FxService
from core.reporting_service import ReportingService


def test_period_status_exposes_only_non_overlapping_budget_targets(ledger_env) -> None:
    book = ledger_env.book_id
    categories = CategoryService(ledger_env.db, ledger_env.accounts)
    fx = FxService(ledger_env.db)
    reporting = ReportingService(ledger_env.db, fx, ledger_env.accounts, categories)
    budgets = BudgetService(
        ledger_env.db,
        reporting,
        fx,
        ledger_env.accounts,
        categories,
    )
    food = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Food",
        placeholder=True,
    )
    groceries = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Groceries",
        parent_id=food.id,
    )
    transport = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Transport",
    )
    categories.create_category(
        book_id=book,
        category_type="INCOME",
        name="Salary",
    )

    initial = budgets.period_status(book_id=book, period="2027-01")
    initial_ids = {item["categoryAccountId"] for item in initial["targets"]}
    assert initial_ids == {food.id, groceries.id, transport.id}
    food_target = next(item for item in initial["targets"] if item["categoryAccountId"] == food.id)
    assert food_target["categoryPath"] == "Food"
    assert food_target["placeholder"] is True
    assert food_target["hasBudget"] is False

    budgets.set_budget(
        book_id=book,
        category_account_id=food.id,
        period="2027-01",
        amount_minor=30_000,
    )
    status = budgets.period_status(book_id=book, period="2027-01")
    targets = {item["categoryAccountId"]: item for item in status["targets"]}
    assert set(targets) == {food.id, transport.id}
    assert targets[food.id]["hasBudget"] is True
    assert groceries.id not in targets
