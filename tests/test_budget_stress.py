from __future__ import annotations

from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.fx_service import FxService
from core.reporting_service import ReportingService


def test_many_sibling_budgets_are_deterministic_and_read_only(ledger_env) -> None:
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

    expected_spent = 0
    count = 64
    for index in range(count):
        category = categories.create_category(
            book_id=book,
            category_type="EXPENSE",
            name=f"Category {index:02d}",
        )
        budgets.set_budget(
            book_id=book,
            category_account_id=category.id,
            period="2026-10",
            amount_minor=10_000,
        )
        amount = 100 + index
        expected_spent += amount
        ledger_env.ledger.create_expense(
            book_id=book,
            source_account_id=bank.id,
            expense_account_id=category.id,
            amount_minor=amount,
            currency_code="EUR",
            transaction_date=f"2026-10-{(index % 28) + 1:02d}",
        )

    before = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
    )
    first = budgets.period_status(book_id=book, period="2026-10")
    second = budgets.period_status(book_id=book, period="2026-10")
    after = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
    )

    assert first == second
    assert before == after
    assert len(first["budgets"]) == count
    assert first["totalBudgetMinor"] == count * 10_000
    assert first["totalSpentMinor"] == expected_spent
    assert first["totalRemainingMinor"] == count * 10_000 - expected_spent
    assert first["complete"] is True
    ledger_env.db.integrity_check()
