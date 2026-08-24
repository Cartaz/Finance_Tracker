from __future__ import annotations

import sqlite3

import pytest

from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.errors import BudgetError
from core.fx_service import FxService
from core.ledger_service import EntryDraft, TransactionDraft
from core.reporting_service import ReportingService


def _service(env):
    categories = CategoryService(env.db, env.accounts)
    fx = FxService(env.db)
    reporting = ReportingService(env.db, fx, env.accounts, categories)
    budgets = BudgetService(env.db, reporting, fx, env.accounts, categories)
    return budgets, categories, fx


def test_monthly_budget_aggregates_category_subtree_and_refunds(ledger_env) -> None:
    budgets, categories, _ = _service(ledger_env)
    book = ledger_env.book_id
    bank = ledger_env.accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
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
    dining = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Dining",
        parent_id=food.id,
    )

    ledger_env.ledger.create_expense(
        book_id=book,
        source_account_id=bank.id,
        expense_account_id=groceries.id,
        amount_minor=4_000,
        currency_code="EUR",
        transaction_date="2026-02-03",
    )
    ledger_env.ledger.create_expense(
        book_id=book,
        source_account_id=bank.id,
        expense_account_id=dining.id,
        amount_minor=2_500,
        currency_code="EUR",
        transaction_date="2026-02-07",
    )
    ledger_env.ledger.create_refund(
        book_id=book,
        destination_account_id=bank.id,
        expense_account_id=groceries.id,
        amount_minor=500,
        currency_code="EUR",
        transaction_date="2026-02-10",
    )

    item = budgets.set_budget(
        book_id=book,
        category_account_id=food.id,
        period="2026-02",
        amount_minor=10_000,
    )
    assert item.amount_minor == 10_000

    status = budgets.period_status(book_id=book, period="2026-02")
    assert status["baseCurrency"] == "EUR"
    assert status["totalBudgetMinor"] == 10_000
    assert status["totalSpentMinor"] == 6_000
    assert status["totalRemainingMinor"] == 4_000
    assert status["complete"] is True
    assert status["missingFx"] == []
    budget = status["budgets"][0]
    assert budget["categoryPath"] == "Food"
    assert budget["spentMinor"] == 6_000
    assert budget["remainingMinor"] == 4_000
    assert budget["usageBps"] == 6_000
    assert budget["overBudget"] is False


def test_budget_upsert_delete_and_validation_are_book_scoped(ledger_env) -> None:
    budgets, categories, _ = _service(ledger_env)
    book = ledger_env.book_id
    expense = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Transport",
    )
    income = categories.create_category(
        book_id=book,
        category_type="INCOME",
        name="Salary",
    )

    first = budgets.set_budget(
        book_id=book,
        category_account_id=expense.id,
        period="2026-03",
        amount_minor=20_000,
    )
    second = budgets.set_budget(
        book_id=book,
        category_account_id=expense.id,
        period="2026-03",
        amount_minor=25_000,
    )
    assert second.id == first.id
    assert second.amount_minor == 25_000

    with pytest.raises(BudgetError):
        budgets.set_budget(
            book_id=book,
            category_account_id=income.id,
            period="2026-03",
            amount_minor=10_000,
        )
    with pytest.raises(BudgetError):
        budgets.set_budget(
            book_id=book,
            category_account_id=expense.id,
            period="03/2026",
            amount_minor=10_000,
        )
    with pytest.raises(BudgetError):
        budgets.set_budget(
            book_id=book,
            category_account_id=expense.id,
            period="2026-03",
            amount_minor=0,
        )

    budgets.delete_budget(book_id=book, budget_id=first.id)
    assert budgets.period_status(book_id=book, period="2026-03")["budgets"] == []
    with pytest.raises(BudgetError):
        budgets.delete_budget(book_id=book, budget_id=first.id)


def test_same_period_budgets_cannot_overlap_parent_and_child_scopes(ledger_env) -> None:
    budgets, categories, _ = _service(ledger_env)
    root = categories.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Home",
        placeholder=True,
    )
    child = categories.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Utilities",
        parent_id=root.id,
    )
    budgets.set_budget(
        book_id=ledger_env.book_id,
        category_account_id=root.id,
        period="2026-06",
        amount_minor=50_000,
    )
    with pytest.raises(BudgetError, match="cannot overlap"):
        budgets.set_budget(
            book_id=ledger_env.book_id,
            category_account_id=child.id,
            period="2026-06",
            amount_minor=20_000,
        )
    budgets.set_budget(
        book_id=ledger_env.book_id,
        category_account_id=child.id,
        period="2026-07",
        amount_minor=20_000,
    )


def test_budget_spending_fails_closed_when_required_fx_is_missing(ledger_env) -> None:
    budgets, categories, _ = _service(ledger_env)
    book = ledger_env.book_id
    usd = ledger_env.accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="USD",
        currency_code="USD",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    travel = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Travel",
    )
    ledger_env.ledger.create_transaction(
        TransactionDraft(
            book_id=book,
            kind="EXPENSE",
            transaction_date="2026-04-12",
            currency_code="USD",
            entries=(
                EntryDraft(usd.id, -5_000, -5_000),
                EntryDraft(travel.id, 5_000, None),
            ),
        )
    )
    budgets.set_budget(
        book_id=book,
        category_account_id=travel.id,
        period="2026-04",
        amount_minor=30_000,
    )

    status = budgets.period_status(book_id=book, period="2026-04")
    item = status["budgets"][0]
    assert status["complete"] is False
    assert status["totalSpentMinor"] is None
    assert status["totalRemainingMinor"] is None
    assert status["missingFx"] == [{"currency": "USD", "date": "2026-04-12"}]
    assert item["spentMinor"] is None
    assert item["remainingMinor"] is None
    assert item["usageBps"] is None
    assert item["overBudget"] is None


def test_database_trigger_rejects_non_expense_budget_category(ledger_env) -> None:
    _, categories, _ = _service(ledger_env)
    income = categories.create_category(
        book_id=ledger_env.book_id,
        category_type="INCOME",
        name="Income only",
    )
    with pytest.raises(sqlite3.IntegrityError):
        with ledger_env.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO budgets(
                    book_id, category_account_id, period, amount_minor, created_at, updated_at
                ) VALUES (?, ?, '2026-05', 1000, datetime('now'), datetime('now'))
                """,
                (ledger_env.book_id, income.id),
            )