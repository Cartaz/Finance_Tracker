from __future__ import annotations

import pytest

from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.errors import BudgetError
from core.fx_service import FxService
from core.reporting_service import ReportingService


def _services(env):
    categories = CategoryService(env.db, env.accounts)
    fx = FxService(env.db)
    reporting = ReportingService(env.db, fx, env.accounts, categories)
    budgets = BudgetService(env.db, reporting, fx, env.accounts, categories)
    return budgets, categories


def test_budget_reports_overspend_above_one_hundred_percent(ledger_env) -> None:
    book = ledger_env.book_id
    budgets, categories = _services(ledger_env)
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


def test_budget_status_fails_closed_if_category_move_creates_overlap(ledger_env) -> None:
    book = ledger_env.book_id
    budgets, categories = _services(ledger_env)
    home = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Home",
        placeholder=True,
    )
    utilities = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Utilities",
        placeholder=True,
    )
    electricity = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Electricity",
        parent_id=utilities.id,
    )
    budgets.set_budget(
        book_id=book,
        category_account_id=home.id,
        period="2026-12",
        amount_minor=40_000,
    )
    budgets.set_budget(
        book_id=book,
        category_account_id=utilities.id,
        period="2026-12",
        amount_minor=20_000,
    )
    assert len(budgets.period_status(book_id=book, period="2026-12")["budgets"]) == 2

    categories.move_category(book, utilities.id, home.id)
    with pytest.raises(BudgetError, match="current category hierarchy"):
        budgets.period_status(book_id=book, period="2026-12")

    assert categories.category_path(book, electricity.id) == "Home › Utilities › Electricity"
