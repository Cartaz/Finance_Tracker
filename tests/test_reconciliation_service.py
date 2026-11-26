from __future__ import annotations

import pytest

from core.category_service import CategoryService
from core.errors import ReconciliationAmbiguousError, ReconciliationError
from core.ledger_service import EntryDraft, TransactionDraft
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
            posting_kind="EXPENSE",
            counter_account_id=groceries.id,
        )
    after = (
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        ledger_env.db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
    )
    assert after == before


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
            posting_kind="EXPENSE",
            counter_account_id=groceries.id,
        )

    posted_expense = service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[1]["id"]),
        posting_kind="EXPENSE",
        counter_account_id=groceries.id,
        payee_id=merchant.id,
    )
    posted_income = service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[2]["id"]),
        posting_kind="INCOME",
        counter_account_id=salary.id,
    )
    assert posted_expense["state"] == "POSTED"
    assert posted_income["state"] == "POSTED"
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 107_500
    ledger_env.db.integrity_check()


def test_refund_and_liability_transfer_are_not_misclassified_as_income(ledger_env) -> None:
    bank, groceries, _, _, service = _setup(ledger_env)
    card = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="LIABILITY",
        name="Card",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    result = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=card.id,
        source_name="Card issuer",
        review_mode="FULL_REVIEW",
        csv_text=(
            "date,amount,currency,description,external_id\n"
            "2026-05-01,-50.00,EUR,Purchase,cc-1\n"
            "2026-05-02,10.00,EUR,Refund,cc-2\n"
            "2026-05-03,100.00,EUR,Card payment,cc-3\n"
        ),
    )
    rows = service.batch_rows(ledger_env.book_id, int(result["batchId"]))
    service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[0]["id"]),
        posting_kind="EXPENSE",
        counter_account_id=groceries.id,
    )
    service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[1]["id"]),
        posting_kind="REFUND",
        counter_account_id=groceries.id,
    )
    service.post_row(
        book_id=ledger_env.book_id,
        row_id=int(rows[2]["id"]),
        posting_kind="TRANSFER",
        counter_account_id=bank.id,
    )
    updated = service.batch_rows(ledger_env.book_id, int(result["batchId"]))
    transaction_ids = tuple(int(row["matched_transaction_id"]) for row in updated)
    kinds = [
        row[0]
        for row in ledger_env.db.connection.execute(
            "SELECT kind FROM transactions WHERE id IN (?,?,?) ORDER BY id",
            transaction_ids,
        ).fetchall()
    ]
    assert kinds == ["EXPENSE", "REFUND", "TRANSFER"]
    assert ledger_env.accounts.native_balance(ledger_env.book_id, card.id) == 6_000
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 90_000


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


def test_cross_currency_candidate_uses_native_account_quantity(ledger_env) -> None:
    accounts = ledger_env.accounts
    book = ledger_env.book_id
    cash_gbp = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="GBP account",
        currency_code="GBP",
        tracking_start_date="2026-01-01",
    )
    expense = accounts.create_account(
        book_id=book,
        account_type="EXPENSE",
        name="Travel",
    )
    transaction = ledger_env.ledger.create_transaction(
        TransactionDraft(
            book_id=book,
            kind="EXPENSE",
            transaction_date="2026-07-10",
            currency_code="CHF",
            entries=(
                EntryDraft(cash_gbp.id, -1200, -1000),
                EntryDraft(expense.id, 1200, None),
            ),
        )
    )
    service = ReconciliationService(
        ledger_env.db,
        accounts,
        ledger_env.ledger,
        PayeeService(ledger_env.db),
    )
    imported = service.import_csv(
        book_id=book,
        account_id=cash_gbp.id,
        source_name="Cross Currency Bank",
        review_mode="ASSISTED_REVIEW",
        csv_text=(
            "date,amount,currency,description,external_id\n"
            "2026-07-10,-10.00,GBP,Card purchase,cross-1\n"
        ),
    )
    row = service.batch_rows(book, int(imported["batchId"]))[0]
    assert row["review_state"] == "SUGGESTED"
    assert [candidate["id"] for candidate in row["candidates"]] == [transaction.id]
    assert row["candidates"][0]["currency_code"] == "CHF"

    service.link_existing(
        book_id=book,
        row_id=int(row["id"]),
        transaction_id=transaction.id,
    )
    repeated = service.import_csv(
        book_id=book,
        account_id=cash_gbp.id,
        source_name="cross currency bank",
        review_mode="FULL_REVIEW",
        csv_text=(
            "date,amount,currency,description,external_id\n"
            "2026-07-10,-10.00,GBP,Card purchase,cross-1\n"
        ),
    )
    repeated_row = service.batch_rows(book, int(repeated["batchId"]))[0]
    assert repeated_row["review_state"] == "MATCHED"
    assert repeated_row["matched_transaction_id"] == transaction.id


def test_tracking_start_day_without_time_is_explicitly_ambiguous(ledger_env) -> None:
    accounts = ledger_env.accounts
    book = ledger_env.book_id
    intraday = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Intraday",
        currency_code="EUR",
        tracking_start_date="2026-08-01",
        tracking_start_time="12:00:00",
    )
    category = accounts.create_account(
        book_id=book,
        account_type="EXPENSE",
        name="Boundary Expense",
    )
    service = ReconciliationService(
        ledger_env.db,
        accounts,
        ledger_env.ledger,
        PayeeService(ledger_env.db),
    )
    before = ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    imported = service.import_csv(
        book_id=book,
        account_id=intraday.id,
        source_name="Boundary Bank",
        review_mode="ASSISTED_REVIEW",
        csv_text="date,amount,currency\n2026-08-01,-1.00,EUR\n",
    )
    row = service.batch_rows(book, int(imported["batchId"]))[0]
    assert row["review_state"] == "TRACKING_AMBIGUOUS"
    with pytest.raises(ReconciliationError):
        service.post_row(
            book_id=book,
            row_id=int(row["id"]),
            posting_kind="EXPENSE",
            counter_account_id=category.id,
        )
    after = ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert after == before


def test_multiple_semantic_csv_headers_are_rejected_fail_closed(ledger_env) -> None:
    bank, _, _, _, service = _setup(ledger_env)
    before = ledger_env.db.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
    with pytest.raises(ReconciliationAmbiguousError):
        service.import_csv(
            book_id=ledger_env.book_id,
            account_id=bank.id,
            source_name="Bank",
            review_mode="FULL_REVIEW",
            csv_text=(
                "date,booking_date,amount\n"
                "2026-09-01,2026-09-01,-1.00\n"
            ),
        )
    assert ledger_env.db.connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == before


def test_duplicates_and_identities_follow_the_account_not_the_source_label(tmp_path) -> None:
    from core.account_service import AccountService
    from core.book_service import BookService
    from core.database import Database
    from core.ledger_service import LedgerService
    from core.payee_service import PayeeService
    from core.reconciliation_service import ReconciliationService

    database = Database(tmp_path / "labels.db")
    database.migrate()
    book = BookService(database).create_personal_book(
        user_name="u", book_name="b", currency_code="EUR"
    )
    accounts = AccountService(database)
    bank = accounts.create_account(
        book_id=book.id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    food = accounts.create_account(book_id=book.id, account_type="EXPENSE", name="Food")
    service = ReconciliationService(
        database, accounts, LedgerService(database), PayeeService(database)
    )
    csv_text = "date,amount,description,external_id\n2026-03-01,-5,Bar,ext-1\n2026-03-02,-7,Shop,\n"

    def stage(label):
        result = service.import_csv(
            book_id=book.id,
            account_id=bank.id,
            source_name=label,
            csv_text=csv_text,
            review_mode="FULL_REVIEW",
        )
        return service.batch_rows(book.id, result["batchId"])

    first = stage("Intesa")
    service.post_row(
        book_id=book.id, row_id=first[0]["id"], posting_kind="EXPENSE", counter_account_id=food.id
    )
    second = stage("intesa sanpaolo")
    states = [row["review_state"] for row in second]
    # Another label never auto-matches; both rows surface as duplicates for review.
    assert states == ["DUPLICATE_REVIEW", "DUPLICATE_REVIEW"]
    database.close()


def test_reversed_transactions_are_not_reconciliation_candidates(ledger_env) -> None:
    bank, groceries, _, _, service = _setup(ledger_env)
    kept, mistaken = (
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=groceries.id,
            amount_minor=5000,
            currency_code="EUR",
            transaction_date="2026-03-05",
        )
        for _ in range(2)
    )
    ledger_env.ledger.create_reversal(
        book_id=ledger_env.book_id, transaction_id=mistaken.id, transaction_date="2026-03-05"
    )
    result = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="Bank",
        review_mode="ASSISTED_REVIEW",
        csv_text="date,amount\n2026-03-05,-50\n2026-03-05,50\n",
    )
    rows = service.batch_rows(ledger_env.book_id, int(result["batchId"]))
    assert rows[0]["review_state"] == "SUGGESTED"
    assert [item["id"] for item in rows[0]["candidates"]] == [kept.id]
    assert rows[1]["candidates"] == []


def test_generic_ids_from_another_export_do_not_collide(ledger_env) -> None:
    bank, groceries, _, _, service = _setup(ledger_env)

    def stage(source, csv_text):
        result = service.import_csv(
            book_id=ledger_env.book_id,
            account_id=bank.id,
            source_name=source,
            review_mode="FULL_REVIEW",
            csv_text=csv_text,
        )
        return service.batch_rows(ledger_env.book_id, int(result["batchId"]))[0]

    card = stage("Card", "date,amount,id\n2026-03-01,-12,1\n")
    service.post_row(
        book_id=ledger_env.book_id, row_id=card["id"], posting_kind="EXPENSE", counter_account_id=groceries.id
    )
    current = stage("Current account", "date,amount,id\n2026-03-04,-30,1\n")
    assert current["review_state"] == "REVIEW_REQUIRED"
    posted = service.post_row(
        book_id=ledger_env.book_id, row_id=current["id"], posting_kind="EXPENSE", counter_account_id=groceries.id
    )
    assert posted["state"] == "POSTED"


def test_identical_movements_with_distinct_bank_ids_are_not_duplicates(ledger_env) -> None:
    bank, _, _, _, service = _setup(ledger_env)
    result = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="Bank",
        review_mode="FULL_REVIEW",
        csv_text="date,amount,description,external_id\n2026-03-01,-1.20,CAFFE,A1\n2026-03-01,-1.20,CAFFE,A2\n",
    )
    assert result["summary"] == {"REVIEW_REQUIRED": 2}


def test_row_counter_ids_are_not_bank_identities(ledger_env) -> None:
    bank, groceries, _, _, service = _setup(ledger_env)

    def stage(csv_text):
        result = service.import_csv(
            book_id=ledger_env.book_id,
            account_id=bank.id,
            source_name="Bank",
            review_mode="FULL_REVIEW",
            csv_text=csv_text,
        )
        return service.batch_rows(ledger_env.book_id, int(result["batchId"]))

    january = stage("date,amount,id\n2026-01-03,-12,1\n2026-01-04,-8,2\n")
    assert [row["external_id"] for row in january] == [None, None]
    service.post_row(
        book_id=ledger_env.book_id, row_id=january[0]["id"], posting_kind="EXPENSE", counter_account_id=groceries.id
    )
    february = stage("date,amount,id\n2026-02-05,-30,1\n2026-02-06,-9,2\n")
    assert [row["review_state"] for row in february] == ["REVIEW_REQUIRED", "REVIEW_REQUIRED"]
    real = stage("date,amount,id\n2026-02-07,-1,TX-9\n")
    assert real[0]["external_id"] == "TX-9"


def test_a_suggestion_that_no_longer_exists_is_shown_as_unmatched(ledger_env) -> None:
    bank, groceries, _, _, service = _setup(ledger_env)
    expense = ledger_env.ledger.create_expense(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        expense_account_id=groceries.id,
        amount_minor=700,
        currency_code="EUR",
        transaction_date="2026-03-09",
    )
    result = service.import_csv(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        source_name="Bank",
        review_mode="ASSISTED_REVIEW",
        csv_text="date,amount\n2026-03-09,-7\n",
    )
    assert service.batch_rows(ledger_env.book_id, int(result["batchId"]))[0]["review_state"] == "SUGGESTED"
    ledger_env.ledger.create_reversal(
        book_id=ledger_env.book_id, transaction_id=expense.id, transaction_date="2026-03-09"
    )
    assert service.batch_rows(ledger_env.book_id, int(result["batchId"]))[0]["review_state"] == "UNMATCHED"
