from __future__ import annotations

from pathlib import Path

import pytest

from core.category_service import CategoryService
from core.database import Database
from core.errors import ReconciliationError
from core.payee_service import PayeeService
from core.reconciliation_service import ReconciliationService


def test_m6_thousand_row_reconciliation_and_invalid_state_stress(
    ledger_env, tmp_path: Path
) -> None:
    db = ledger_env.db
    book = ledger_env.book_id
    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="M6 Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    equity = accounts.create_account(
        book_id=book, account_type="EQUITY", name="M6 Equity"
    )
    ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=10_000_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
    )
    categories = CategoryService(db, accounts)
    expense = categories.create_category(
        book_id=book, category_type="EXPENSE", name="M6 Expense"
    )
    income = categories.create_category(
        book_id=book, category_type="INCOME", name="M6 Income"
    )
    placeholder = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="M6 Placeholder",
        placeholder=True,
    )
    archived = categories.create_category(
        book_id=book, category_type="EXPENSE", name="M6 Archived"
    )
    categories.set_archived(book, archived.id, True)
    other_book_counter = accounts.create_account(
        book_id=ledger_env.other_book_id,
        account_type="EXPENSE",
        name="Other book expense",
    )
    payees = PayeeService(db)
    merchant = payees.create_payee(book_id=book, name="M6 Merchant")
    service = ReconciliationService(db, accounts, ledger, payees)

    lines = ["date;amount;currency;description;external_id"]
    for index in range(1000):
        day = index % 28 + 1
        month = index % 12 + 1
        amount = "-10,00" if index % 2 == 0 else "20,00"
        lines.append(
            f"2026-{month:02d}-{day:02d};{amount};EUR;Stress row {index};m6-{index:04d}"
        )
    csv_text = "\n".join(lines) + "\n"

    imported = service.import_csv(
        book_id=book,
        account_id=bank.id,
        source_name="Stress Bank",
        csv_text=csv_text,
        review_mode="FULL_REVIEW",
    )
    assert imported["rowCount"] == 1000
    assert imported["summary"] == {"REVIEW_REQUIRED": 1000}
    rows = service.batch_rows(book, int(imported["batchId"]))
    assert len(rows) == 1000

    for index, row in enumerate(rows[:500]):
        service.post_row(
            book_id=book,
            row_id=int(row["id"]),
            posting_kind="EXPENSE" if index % 2 == 0 else "INCOME",
            counter_account_id=expense.id if index % 2 == 0 else income.id,
            payee_id=merchant.id if index % 2 == 0 else None,
        )
    for row in rows[500:750]:
        service.ignore_row(book_id=book, row_id=int(row["id"]))

    transactions_after_valid = db.connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE book_id=?", (book,)
    ).fetchone()[0]
    entries_after_valid = db.connection.execute(
        "SELECT COUNT(*) FROM entries WHERE book_id=?", (book,)
    ).fetchone()[0]
    links_after_valid = db.connection.execute(
        "SELECT COUNT(*) FROM reconciliation_links WHERE book_id=?", (book,)
    ).fetchone()[0]
    assert links_after_valid == 500

    repeated = service.import_csv(
        book_id=book,
        account_id=bank.id,
        source_name="Stress Bank",
        csv_text=csv_text,
        review_mode="ASSISTED_REVIEW",
    )
    repeated_rows = service.batch_rows(book, int(repeated["batchId"]))
    assert sum(row["review_state"] == "MATCHED" for row in repeated_rows) == 500
    assert sum(row["review_state"] == "DUPLICATE_REVIEW" for row in repeated_rows) == 500

    invalid_cases = (
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[0]["id"]),
            posting_kind="EXPENSE",
            counter_account_id=expense.id,
        ),
        lambda: service.ignore_row(book_id=book, row_id=int(rows[1]["id"])),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[751]["id"]),
            posting_kind="EXPENSE",
            counter_account_id=expense.id,
        ),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[752]["id"]),
            posting_kind="INCOME",
            counter_account_id=income.id,
        ),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[754]["id"]),
            posting_kind="EXPENSE",
            counter_account_id=placeholder.id,
        ),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[756]["id"]),
            posting_kind="EXPENSE",
            counter_account_id=archived.id,
        ),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[758]["id"]),
            posting_kind="EXPENSE",
            counter_account_id=other_book_counter.id,
        ),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[760]["id"]),
            posting_kind="UNKNOWN",
            counter_account_id=expense.id,
        ),
        lambda: service.post_row(
            book_id=book,
            row_id=int(rows[762]["id"]),
            posting_kind="TRANSFER",
            counter_account_id=bank.id,
        ),
        lambda: service.link_existing(
            book_id=book,
            row_id=int(rows[753]["id"]),
            transaction_id=999_999_999,
        ),
        lambda: service.batch_rows(book, 999_999_999),
        lambda: service.ignore_row(book_id=book, row_id=999_999_999),
    )
    for index in range(1000):
        before = (
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM reconciliation_links").fetchone()[0],
        )
        with pytest.raises(ReconciliationError):
            invalid_cases[index % len(invalid_cases)]()
        after = (
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM reconciliation_links").fetchone()[0],
        )
        assert after == before

    assert db.connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE book_id=?", (book,)
    ).fetchone()[0] == transactions_after_valid
    assert db.connection.execute(
        "SELECT COUNT(*) FROM entries WHERE book_id=?", (book,)
    ).fetchone()[0] == entries_after_valid
    db.integrity_check()

    backup = tmp_path / "m6-backup.db"
    db.backup_to(backup)
    restored = Database(backup)
    restored.open()
    try:
        restored.integrity_check()
        assert restored.connection.execute(
            "SELECT COUNT(*) FROM import_batches"
        ).fetchone()[0] == 2
        assert restored.connection.execute(
            "SELECT COUNT(*) FROM import_rows"
        ).fetchone()[0] == 2000
        assert restored.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_links"
        ).fetchone()[0] == 500
    finally:
        restored.close()
