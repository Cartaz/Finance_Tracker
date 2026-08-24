from __future__ import annotations

import pytest

from core.category_service import CategoryService
from core.errors import CategoryError
from core.payee_service import PayeeService


def test_category_tree_and_paths(ledger_env) -> None:
    service = CategoryService(ledger_env.db, ledger_env.accounts)
    food = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Alimentazione",
        placeholder=True,
    )
    groceries = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Supermercato",
        parent_id=food.id,
    )
    assert (
        service.category_path(ledger_env.book_id, groceries.id)
        == "Alimentazione › Supermercato"
    )


def test_duplicate_sibling_names_are_rejected_but_other_branches_are_allowed(
    ledger_env,
) -> None:
    service = CategoryService(ledger_env.db, ledger_env.accounts)
    food = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Food",
        placeholder=True,
    )
    auto = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Auto",
        placeholder=True,
    )
    service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Other",
        parent_id=food.id,
    )
    with pytest.raises(CategoryError):
        service.create_category(
            book_id=ledger_env.book_id,
            category_type="EXPENSE",
            name="  OTHER ",
            parent_id=food.id,
        )
    second = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Other",
        parent_id=auto.id,
    )
    assert service.category_path(ledger_env.book_id, second.id) == "Auto › Other"


def test_non_category_account_is_rejected(ledger_env) -> None:
    service = CategoryService(ledger_env.db, ledger_env.accounts)
    bank = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    with pytest.raises(CategoryError):
        service.rename_category(ledger_env.book_id, bank.id, "Not a category")


def test_category_autocomplete_prefers_payee_history(ledger_env) -> None:
    categories = CategoryService(ledger_env.db, ledger_env.accounts)
    payees = PayeeService(ledger_env.db)
    book = ledger_env.book_id
    bank = ledger_env.accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    equity = ledger_env.accounts.create_account(
        book_id=book,
        account_type="EQUITY",
        name="Opening",
    )
    supermarket = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Supermercato",
    )
    subscriptions = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Subscriptions",
    )
    amazon = payees.create_payee(book_id=book, name="Amazon")
    ledger_env.ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=100_000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="00:00:00",
    )
    for index in range(4):
        tx = ledger_env.ledger.create_expense(
            book_id=book,
            source_account_id=bank.id,
            expense_account_id=supermarket.id,
            amount_minor=1000,
            currency_code="EUR",
            transaction_date=f"2026-09-{index + 1:02d}",
        )
        payees.assign_transaction(
            book_id=book,
            transaction_id=tx.id,
            payee_id=amazon.id,
        )
    for index in range(10):
        ledger_env.ledger.create_expense(
            book_id=book,
            source_account_id=bank.id,
            expense_account_id=subscriptions.id,
            amount_minor=500,
            currency_code="EUR",
            transaction_date=f"2026-10-{index + 1:02d}",
        )
    suggestions = categories.suggest_categories(
        book,
        "S",
        category_type="EXPENSE",
        payee_id=amazon.id,
    )
    assert suggestions[0].id == supermarket.id
    assert suggestions[0].payee_usage_count == 4
