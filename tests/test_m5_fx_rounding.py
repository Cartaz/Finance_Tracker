from __future__ import annotations

import pytest

from core.category_service import CategoryService
from core.fx_service import FxService
from core.ledger_service import EntryDraft, TransactionDraft
from core.reporting_service import ReportingService


@pytest.mark.parametrize(
    ("rate", "expected_minor"),
    (("0.50", 1), ("1.50", 3)),
)
def test_split_fx_rounding_reconciles_all_flow_reports(
    ledger_env,
    rate: str,
    expected_minor: int,
) -> None:
    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    book_id = ledger_env.book_id

    usd = accounts.create_account(
        book_id=book_id,
        account_type="ASSET",
        name="USD split",
        currency_code="USD",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    categories = CategoryService(ledger_env.db, accounts)
    first = categories.create_category(
        book_id=book_id,
        category_type="EXPENSE",
        name="Split A",
    )
    second = categories.create_category(
        book_id=book_id,
        category_type="EXPENSE",
        name="Split B",
    )

    ledger.create_transaction(
        TransactionDraft(
            book_id=book_id,
            kind="EXPENSE",
            transaction_date="2026-01-15",
            currency_code="USD",
            entries=(
                EntryDraft(usd.id, -2, -2),
                EntryDraft(first.id, 1, None),
                EntryDraft(second.id, 1, None),
            ),
        )
    )

    fx = FxService(ledger_env.db)
    fx.set_rate(
        book_id=book_id,
        currency_code="USD",
        rate_date="2026-01-15",
        rate=rate,
    )
    reporting = ReportingService(ledger_env.db, fx, accounts, categories)

    overview = reporting.overview(
        book_id=book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        as_of_date="2026-01-31",
    )
    assert overview["expenseMinor"] == expected_minor

    category_rows = reporting.category_report(
        book_id=book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert sum(int(item["amountMinor"]) for item in category_rows) == expected_minor

    merchant_rows = reporting.merchant_report(
        book_id=book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert len(merchant_rows) == 1
    assert merchant_rows[0]["amountMinor"] == expected_minor

    cash_flow = reporting.cash_flow(
        book_id=book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert cash_flow[0]["expenseMinor"] == expected_minor

    ledger_env.db.integrity_check()
    assert not ledger_env.db.connection.execute("PRAGMA foreign_key_check").fetchall()
