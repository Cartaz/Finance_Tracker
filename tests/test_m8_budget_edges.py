from __future__ import annotations

from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.fx_service import FxService
from core.reporting_service import ReportingService


def test_budget_reports_overspend_above_one_hundred_percent(ledger_env) -> None:
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
    bank = ledger_env.accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    category = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Leisure",
    )
    budgets.set_budget(
        book_id=book,
        category_account_id=category.id,
        period="2026-11",
        amount_minor=10_000,
    )
    ledger_env.ledger.create_expense(
        book_id=book,
        source_account_id=bank.id,
        expense_account_id=category.id,
        amount_minor=12_345,
        currency_code="EUR",
        transaction_date="2026-11-10",
    )

    status = budgets.period_status(book_id=book, period="2026-11")
    item = status["budgets"][0]
    assert item["spentMinor"] == 12_345
    assert item["remainingMinor"] == -2_345
    assert item["usageBps"] == 12_345
    assert item["overBudget"] is True
    assert status["totalRemainingMinor"] == -2_345
