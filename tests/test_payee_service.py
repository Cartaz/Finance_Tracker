from __future__ import annotations

import pytest

from core.errors import (
    CrossBookReferenceError,
    PayeeArchivedError,
    PayeeCollisionError,
)
from core.payee_service import PayeeService, normalize_payee_text


def _expense_transaction(ledger_env, amount: int, date: str):
    accounts = ledger_env.accounts
    book = ledger_env.book_id
    bank = next((a for a in accounts.list_accounts(book) if a.name == "Bank"), None)
    expense = next((a for a in accounts.list_accounts(book) if a.name == "Groceries"), None)
    equity = next((a for a in accounts.list_accounts(book) if a.name == "Opening"), None)
    if bank is None:
        bank = accounts.create_account(
            book_id=book,
            account_type="ASSET",
            name="Bank",
            currency_code="EUR",
            tracking_start_date="2026-08-25",
            tracking_start_time="00:00:00",
        )
        expense = accounts.create_account(book_id=book, account_type="EXPENSE", name="Groceries")
        equity = accounts.create_account(book_id=book, account_type="EQUITY", name="Opening")
        ledger_env.ledger.create_opening_balance(
            book_id=book,
            account_id=bank.id,
            equity_account_id=equity.id,
            quantity_minor=100_000,
            currency_code="EUR",
            transaction_date="2026-08-25",
            transaction_time="00:00:00",
        )
    return ledger_env.ledger.create_expense(
        book_id=book,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=amount,
        currency_code="EUR",
        transaction_date=date,
    )


def test_normalization_is_case_and_whitespace_stable() -> None:
    assert normalize_payee_text("  AMAZON   Marketplace ") == "amazon marketplace"
    assert normalize_payee_text("Ａｍａｚｏｎ") == "amazon"


def test_namespace_rejects_canonical_and_alias_collisions(ledger_env) -> None:
    service = PayeeService(ledger_env.db)
    amazon = service.create_payee(book_id=ledger_env.book_id, name="Amazon")
    service.add_alias(
        book_id=ledger_env.book_id,
        payee_id=amazon.id,
        alias="AMZN MKTP",
    )
    with pytest.raises(PayeeCollisionError):
        service.create_payee(book_id=ledger_env.book_id, name=" amzn  mktp ")
    aldi = service.create_payee(book_id=ledger_env.book_id, name="Aldi")
    with pytest.raises(PayeeCollisionError):
        service.add_alias(
            book_id=ledger_env.book_id,
            payee_id=aldi.id,
            alias="AMAZON",
        )


def test_autocomplete_ranks_frequency_after_match_quality(ledger_env) -> None:
    service = PayeeService(ledger_env.db)
    amazon = service.create_payee(book_id=ledger_env.book_id, name="Amazon")
    aldi = service.create_payee(book_id=ledger_env.book_id, name="Aldi")
    for index in range(10):
        tx = _expense_transaction(ledger_env, 100 + index, f"2026-09-{index + 1:02d}")
        service.assign_transaction(book_id=ledger_env.book_id, transaction_id=tx.id, payee_id=amazon.id)
    for index in range(5):
        tx = _expense_transaction(ledger_env, 200 + index, f"2026-10-{index + 1:02d}")
        service.assign_transaction(book_id=ledger_env.book_id, transaction_id=tx.id, payee_id=aldi.id)
    suggestions = service.suggest_payees(ledger_env.book_id, "A", limit=5)
    assert [item.name for item in suggestions[:2]] == ["Amazon", "Aldi"]
    exact = service.suggest_payees(ledger_env.book_id, "Aldi", limit=5)
    assert exact[0].id == aldi.id


def test_archived_and_cross_book_payees_cannot_be_assigned(ledger_env) -> None:
    service = PayeeService(ledger_env.db)
    payee = service.create_payee(book_id=ledger_env.book_id, name="Amazon")
    tx = _expense_transaction(ledger_env, 500, "2026-09-01")
    service.set_archived(ledger_env.book_id, payee.id, True)
    with pytest.raises(PayeeArchivedError):
        service.assign_transaction(
            book_id=ledger_env.book_id,
            transaction_id=tx.id,
            payee_id=payee.id,
        )
    other = service.create_payee(book_id=ledger_env.other_book_id, name="Other merchant")
    with pytest.raises(CrossBookReferenceError):
        service.assign_transaction(
            book_id=ledger_env.book_id,
            transaction_id=tx.id,
            payee_id=other.id,
        )


def test_merge_relinks_transactions_and_preserves_source_name_as_alias(ledger_env) -> None:
    service = PayeeService(ledger_env.db)
    source = service.create_payee(book_id=ledger_env.book_id, name="Amazon Marketplace")
    target = service.create_payee(book_id=ledger_env.book_id, name="Amazon")
    service.add_alias(
        book_id=ledger_env.book_id,
        payee_id=source.id,
        alias="AMZN Mktp EU",
    )
    tx = _expense_transaction(ledger_env, 999, "2026-09-01")
    service.assign_transaction(book_id=ledger_env.book_id, transaction_id=tx.id, payee_id=source.id)
    service.merge_payees(book_id=ledger_env.book_id, source_id=source.id, target_id=target.id)
    row = ledger_env.db.connection.execute(
        "SELECT payee_id FROM transactions WHERE id = ?", (tx.id,)
    ).fetchone()
    assert row["payee_id"] == target.id
    assert service.get_payee(ledger_env.book_id, source.id).archived
    aliases = {alias.casefold() for _, alias, _ in service.aliases_for(ledger_env.book_id, target.id)}
    assert "amazon marketplace" in aliases
    assert "amzn mktp eu" in aliases
