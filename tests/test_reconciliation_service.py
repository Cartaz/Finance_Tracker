from __future__ import annotations

import pytest

from core.category_service import CategoryService
from core.errors import ReconciliationAmbiguousError, ReconciliationError
from core.payee_service import PayeeService
from core.reconciliation_service import ReconciliationService


def _setup(ledger_env):
    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    db = ledger_env.db
    book = ledger_env.book_id
    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    equity = accounts.create_account(book_id=book, account_type="EQUITY", name="Equity")
    ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=100_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
    )
    categories = CategoryService(db, accounts)
    groceries = categories.create_category(book_id=book, category_type="EXPENSE", name="Groceries")
    salary = categories.create_category(book_id=book, category_type="INCOME", name="Salary")
    payees = PayeeService(db)
    merchant = payees.create_payee(book_id=book, name="Market")
    service = ReconciliationService(db, accounts, ledger, payees)
    return bank, groceries, salary, merchant, service


def test_assisted_review_never_auto_matches_heuristic_candidate(ledger_env) -> None:
    bank, groceries, _, merchant, service = _setup(ledger_env)
    existing = ledger_env.ledger.create_expense(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        expense_account_id=groceries.id,
        amount_minor=1234,
        currency_code="EUR",
        transaction_date="2026-03-01",
        description="Market",
    )
    ledger_env.db.connection.execute(
        "UPDATE transactions SET payee_id=? WHERE id=?", (merchant.id, existing.id)
    )
    ledger_env.db.connection.commit()

    result = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="Example Bank",
        review_mode="ASSISTED_REVIEW",
        csv_text="date;amount;currency;description;external_id\n01/03/2026;-12,34;EUR;Market;bank-001\n",
    )
    rows = service.batch_rows(ledger_env.book_id, int(result["batchId"]))
    assert rows[0]["review_state"] == "SUGGESTED"
    assert rows[0]["matched_transaction_id"] is None
    assert [item["id"] for item in rows[0]["candidates"]] == [existing.id]
    assert rows[0]["candidates"][0]["payee_name"] == "Market"

    linked = service.link_existing(
        book_id=ledger_env.book_id,
        row_id=int(rows[0]["id"]),
        transaction_id=existing.id,
    )
    assert linked["state"] == "MATCHED"

    repeated = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="  EXAMPLE   BANK ",
        review_mode="FULL_REVIEW",
        csv_text="date,amount,currency,description,external_id\n2026-03-01,-12.34,EUR,Market,bank-001\n",
    )
    repeated_row = service.batch_rows(ledger_env.book_id, int(repeated["batchId"]))[0]
    assert repeated_row["review_state"] == "MATCHED"
    assert repeated_row["matched_transaction_id"] == existing.id

    conflicting = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="example bank",
        review_mode="ASSISTED_REVIEW",
        csv_text="date,amount,currency,description,external_id\n2026-03-02,-99.99,EUR,Conflict,bank-001\n",
    )
    conflict_row = service.batch_rows(ledger_env.book_id, int(conflicting["batchId"]))[0]
    assert conflict_row["review_state"] == "AMBIGUOUS"
    assert conflict_row["matched_transaction_id"] is None

    before = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
    )
    with pytest.raises(ReconciliationAmbiguousError):
        service.post_row(
            book_id=ledger_env.book_id,
            row_id=int(conflict_row["id"]),
            category_account_id=groceries.id,
        )
    after = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
    )
    assert after == before
    assert ledger_env.db.connection.execute(
        "SELECT review_state, matched_transaction_id FROM import_rows WHERE id=?",
        (int(conflict_row["id"]),),
    ).fetchone()["review_state"] == "AMBIGUOUS"


def test_posting_is_atomic_and_tracking_boundary_is_preserved(ledger_env) -> None:
    bank, groceries, salary, merchant, service = _setup(ledger_env)
    result = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="Example Bank",
        review_mode="FULL_REVIEW",
        csv_text=(
            "date,amount,currency,description,external_id\n"
            "2025-12-31,-5.00,EUR,Too old,old-1\n"
            "2026-04-01,-25.00,EUR,Market,out-1\n"
            "2026-04-02,100.00,EUR,Employer,in-1\n"
        ),
    )
    rows = service.batch_rows(ledger_env.book_id, int(result["batchId"]))
    assert [row["review_state"] for row in rows] == [
        "OUTSIDE_TRACKING",
        "REVIEW_REQUIRED",
        "REVIEW_REQUIRED",
    ]
    with pytest.raises(ReconciliationError):
        service.post_row(
            book_id=ledger_env.book_id,
            row_id=int(rows[0]["id"]),
            category_account_id=groceries.id,
        )

    posted_expense = service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[1]["id"]),
        category_account_id=groceries.id,
        payee_id=merchant.id,
    )
    posted_income = service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[2]["id"]),
        category_account_id=salary.id,
    )
    assert posted_expense["state"] == "POSTED"
    assert posted_income["state"] == "POSTED"
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 107_500
    ledger_env.db.integrity_check()


def test_duplicate_external_ids_inside_one_csv_are_rejected_atomically(ledger_env) -> None:
    bank, _, _, _, service = _setup(ledger_env)
    before = ledger_env.db.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
    with pytest.raises(ReconciliationAmbiguousError):
        service.import_csv(
            book_id=ledger_env.book_id,
            account_id=bank.id,
            source_name="Bank",
            review_mode="FULL_REVIEW",
            csv_text=(
                "date,amount,external_id\n"
                "2026-05-01,-1.00,dup\n"
                "2026-05-02,-2.00,dup\n"
            ),
        )
    after = ledger_env.db.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
    assert after == before


def test_reimport_without_external_id_is_never_silently_duplicated(ledger_env) -> None:
    bank, _, _, _, service = _setup(ledger_env)
    csv_text = "date,amount,description\n2026-06-01,-3.50,Coffee\n"
    first = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="Bank",
        review_mode="FULL_REVIEW",
        csv_text=csv_text,
    )
    assert service.batch_rows(ledger_env.book_id, int(first["batchId"]))[0]["review_state"] == "REVIEW_REQUIRED"
    second = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="BANK",
        review_mode="ASSISTED_REVIEW",
        csv_text=csv_text,
    )
    assert service.batch_rows(ledger_env.book_id, int(second["batchId"]))[0]["review_state"] == "DUPLICATE_REVIEW"
