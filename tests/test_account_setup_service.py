from __future__ import annotations

import pytest

from core.account_setup_service import AccountSetupService
from core.app_state_service import AppStateService
from core.category_service import CategoryService


def _service(ledger_env, ledger=None) -> AccountSetupService:
    categories = CategoryService(ledger_env.db, ledger_env.accounts)
    return AccountSetupService(
        ledger_env.db,
        ledger_env.accounts,
        categories,
        ledger or ledger_env.ledger,
    )


def test_opening_balances_are_atomic_ledger_entries_and_equity_is_hidden(
    ledger_env,
) -> None:
    service = _service(ledger_env)

    bank = service.create_balance_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Banca",
        currency_code="EUR",
        tracking_start_date="2026-08-28",
        opening_balance_minor=250_000,
        opening_balance_direction="POSITIVE",
    )
    card = service.create_balance_account(
        book_id=ledger_env.book_id,
        account_type="LIABILITY",
        name="Carta",
        currency_code="EUR",
        tracking_start_date="2026-08-28",
        opening_balance_minor=40_000,
        opening_balance_direction="NEGATIVE",
    )

    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 250_000
    assert ledger_env.accounts.native_balance(ledger_env.book_id, card.id) == -40_000

    all_accounts = ledger_env.accounts.list_accounts(ledger_env.book_id)
    technical_equity = [item for item in all_accounts if item.type == "EQUITY"]
    assert len(technical_equity) == 2

    snapshot = AppStateService(ledger_env.db, ledger_env.accounts).snapshot(
        book_id=ledger_env.book_id,
        book_name="Primary",
        book_currency="EUR",
    )
    assert all(item["type"] != "EQUITY" for item in snapshot["accounts"])
    assert {item["name"] for item in snapshot["accounts"]} == {"Banca", "Carta"}


def test_category_creation_supports_parent_child_hierarchy(ledger_env) -> None:
    service = _service(ledger_env)

    parent = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Alimentari",
        placeholder=True,
    )
    child = service.create_category(
        book_id=ledger_env.book_id,
        category_type="EXPENSE",
        name="Supermercato",
        parent_id=parent.id,
    )

    assert child.parent_id == parent.id
    assert CategoryService(
        ledger_env.db, ledger_env.accounts
    ).category_path(ledger_env.book_id, child.id) == "Alimentari › Supermercato"

    snapshot = AppStateService(ledger_env.db, ledger_env.accounts).snapshot(
        book_id=ledger_env.book_id,
        book_name="Primary",
        book_currency="EUR",
    )
    child_payload = next(item for item in snapshot["accounts"] if item["id"] == child.id)
    assert child_payload["parentId"] == parent.id


def test_opening_balance_failure_rolls_back_account_and_technical_counterpart(
    ledger_env,
) -> None:
    class FailingLedger:
        def create_opening_balance(self, **_kwargs) -> None:
            raise RuntimeError("simulated ledger failure")

    service = _service(ledger_env, FailingLedger())
    before = ledger_env.accounts.list_accounts(ledger_env.book_id)

    with pytest.raises(RuntimeError, match="simulated ledger failure"):
        service.create_balance_account(
            book_id=ledger_env.book_id,
            account_type="ASSET",
            name="Da annullare",
            currency_code="EUR",
            tracking_start_date="2026-08-28",
            opening_balance_minor=10_000,
            opening_balance_direction="POSITIVE",
        )

    after = ledger_env.accounts.list_accounts(ledger_env.book_id)
    assert after == before


def test_placeholder_balance_account_rejects_opening_balance(ledger_env) -> None:
    service = _service(ledger_env)

    with pytest.raises(Exception, match="placeholder account cannot have an opening balance"):
        service.create_balance_account(
            book_id=ledger_env.book_id,
            account_type="ASSET",
            name="Gruppo conti",
            currency_code="EUR",
            tracking_start_date="2026-08-28",
            placeholder=True,
            opening_balance_minor=1,
        )
