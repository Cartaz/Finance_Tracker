from __future__ import annotations

from decimal import Decimal

import pytest

from core.category_service import CategoryService
from core.fx_service import FxService
from core.ledger_service import EntryDraft, TransactionDraft
from core.reporting_service import ReportingService


@pytest.mark.parametrize(
    ("has_account_fx", "has_transaction_fx", "net_worth_complete", "flow_complete"),
    (
        (False, False, False, False),
        (True, False, True, False),
        (False, True, False, True),
        (True, True, True, True),
    ),
)
def test_cross_currency_account_and_transaction_fx_are_independent(
    ledger_env,
    has_account_fx: bool,
    has_transaction_fx: bool,
    net_worth_complete: bool,
    flow_complete: bool,
) -> None:
    """Exercise 1,000 cross-currency postings across the four FX availability states.

    The balance account is GBP while each expense is valued in CHF and the book is EUR.
    Native account quantity and transaction value therefore depend on different FX rates.
    Each parametrized run creates 250 postings, for 1,000 cross-currency postings total.
    """

    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    book_id = ledger_env.book_id

    gbp_account = accounts.create_account(
        book_id=book_id,
        account_type="ASSET",
        name="GBP cross-currency account",
        currency_code="GBP",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    equity = accounts.create_account(
        book_id=book_id,
        account_type="EQUITY",
        name="Cross-currency opening",
    )
    category = CategoryService(ledger_env.db, accounts).create_category(
        book_id=book_id,
        category_type="EXPENSE",
        name="Cross-currency expense",
    )

    ledger.create_opening_balance(
        book_id=book_id,
        account_id=gbp_account.id,
        equity_account_id=equity.id,
        quantity_minor=10_000_000,
        currency_code="GBP",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )

    for index in range(250):
        transaction = ledger.create_transaction(
            TransactionDraft(
                book_id=book_id,
                kind="EXPENSE",
                transaction_date="2026-01-15",
                currency_code="CHF",
                description=f"Cross-currency stress {index}",
                original_amount_minor=1_000,
                original_currency_code="GBP",
                entries=(
                    EntryDraft(
                        account_id=gbp_account.id,
                        value_minor=-1_200,
                        quantity_minor=-1_000,
                    ),
                    EntryDraft(
                        account_id=category.id,
                        value_minor=1_200,
                        quantity_minor=None,
                    ),
                ),
            )
        )
        assert sum(entry.value_minor for entry in transaction.entries) == 0

    fx = FxService(ledger_env.db)
    if has_account_fx:
        fx.set_rate(
            book_id=book_id,
            currency_code="GBP",
            rate_date="2026-01-01",
            rate=Decimal("1.15"),
        )
    if has_transaction_fx:
        fx.set_rate(
            book_id=book_id,
            currency_code="CHF",
            rate_date="2026-01-01",
            rate=Decimal("1.05"),
        )

    reporting = ReportingService(ledger_env.db, fx, accounts)
    overview = reporting.overview(
        book_id=book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        as_of_date="2026-01-31",
    )

    assert overview["netWorthComplete"] is net_worth_complete
    assert overview["flowComplete"] is flow_complete
    assert overview["complete"] is (net_worth_complete and flow_complete)

    if net_worth_complete:
        # 10,000,000 GBP minor opening - 250 * 1,000 GBP minor, valued at 1.15 EUR/GBP.
        assert overview["assetsMinor"] == 11_212_500
        assert overview["netWorthMinor"] == 11_212_500
    else:
        assert overview["assetsMinor"] is None
        assert overview["netWorthMinor"] is None

    if flow_complete:
        # 250 * 1,200 CHF minor, valued at 1.05 EUR/CHF.
        assert overview["expenseMinor"] == 315_000
        assert overview["incomeMinor"] == 0
        assert overview["savingMinor"] == -315_000
    else:
        assert overview["expenseMinor"] is None
        assert overview["savingMinor"] is None

    missing = {(item["currency"], item["date"]) for item in overview["missingFx"]}
    expected_missing: set[tuple[str, str]] = set()
    if not has_account_fx:
        expected_missing.add(("GBP", "2026-01-31"))
    if not has_transaction_fx:
        expected_missing.add(("CHF", "2026-01-15"))
    assert missing == expected_missing

    history = reporting.account_history(
        book_id=book_id,
        account_id=gbp_account.id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert history["endingBalanceMinor"] == 9_750_000
    assert history["complete"] is has_account_fx

    categories = reporting.category_report(
        book_id=book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert len(categories) == 1
    assert categories[0]["complete"] is has_transaction_fx
    assert categories[0]["amountMinor"] == (315_000 if has_transaction_fx else None)

    ledger_env.db.integrity_check()
    assert not ledger_env.db.connection.execute("PRAGMA foreign_key_check").fetchall()
