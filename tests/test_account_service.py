import pytest

from core.errors import AccountHierarchyError, ValidationError


def test_account_types_and_native_balance(ledger_env) -> None:
    asset = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Current account",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    category = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Food",
    )
    assert asset.currency_code == "EUR"
    assert category.currency_code is None
    assert ledger_env.accounts.native_balance(ledger_env.book_id, asset.id) == 0
    with pytest.raises(ValidationError):
        ledger_env.accounts.native_balance(ledger_env.book_id, category.id)


def test_invalid_currency_semantics_are_rejected(ledger_env) -> None:
    with pytest.raises(ValidationError):
        ledger_env.accounts.create_account(
            book_id=ledger_env.book_id,
            account_type="ASSET",
            name="Broken",
            tracking_start_date="2026-08-25",
        )
    with pytest.raises(ValidationError):
        ledger_env.accounts.create_account(
            book_id=ledger_env.book_id,
            account_type="EXPENSE",
            name="Broken category",
            currency_code="EUR",
            tracking_start_date="2026-08-25",
        )


def test_hierarchy_rejects_type_mismatch_and_cycles(ledger_env) -> None:
    parent = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Food",
    )
    child = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Groceries",
        parent_id=parent.id,
    )
    income = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="INCOME",
        name="Salary",
    )
    with pytest.raises(AccountHierarchyError):
        ledger_env.accounts.move_account(ledger_env.book_id, parent.id, child.id)
    with pytest.raises(AccountHierarchyError):
        ledger_env.accounts.move_account(ledger_env.book_id, child.id, income.id)
