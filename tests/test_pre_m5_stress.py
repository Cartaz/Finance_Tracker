from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

import pytest

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.category_service import CategoryService
from core.database import Database
from core.errors import FinanceTrackerError
from core.ledger_service import EntryDraft, LedgerService, TransactionDraft
from core.money import CurrencySpec, minor_to_decimal, parse_money
from core.payee_service import PayeeService


def test_m0_m1_thousand_case_money_database_and_backup_stress(tmp_path) -> None:
    rng = random.Random(2026082401)
    specs = (CurrencySpec("EUR", 2), CurrencySpec("JPY", 0), CurrencySpec("KWD", 3))

    for index in range(1000):
        spec = specs[index % len(specs)]
        scale = 10**spec.minor_unit_digits
        whole = rng.randint(0, 9_999_999)
        fraction = rng.randrange(scale) if spec.minor_unit_digits else 0
        negative = index % 7 == 0
        sign = "-" if negative else ""
        if spec.minor_unit_digits:
            separator = ",," if index % 11 == 0 else ("," if index % 2 else ".")
            raw = f" {sign}{whole}{separator}{fraction:0{spec.minor_unit_digits}d} "
        else:
            raw = f" {sign}{whole} "
        expected = whole * scale + fraction
        if negative:
            expected = -expected
        parsed = parse_money(raw, spec)
        assert parsed == expected
        assert minor_to_decimal(parsed, spec) * scale == parsed

    invalid_inputs = ("", "abc", "1,2,3", "1.2.3", "1,23€", "--1", ".", "1,", ",1", "1_00")
    eur = CurrencySpec("EUR", 2)
    for index in range(1000):
        with pytest.raises(FinanceTrackerError):
            parse_money(invalid_inputs[index % len(invalid_inputs)], eur)

    db = Database(tmp_path / "foundation.db")
    db.open()
    db.migrate()
    try:
        with db.transaction() as conn:
            for index in range(1000):
                conn.execute(
                    "INSERT INTO users(name, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))",
                    (f"Stress User {index}",),
                )
        assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1000
        db.integrity_check()
        backup_path = tmp_path / "backup" / "foundation-backup.db"
        db.backup_to(backup_path)
        restored = Database(backup_path)
        restored.open()
        try:
            restored.integrity_check()
            assert restored.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1000
        finally:
            restored.close()
    finally:
        db.close()


def test_m2_thousand_valid_and_invalid_ledger_cases(ledger_env, tmp_path) -> None:
    rng = random.Random(2026082402)
    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    db = ledger_env.db
    book = ledger_env.book_id

    def create_account(account_type: str, name: str, currency: str | None = None, *, placeholder: bool = False):
        kwargs: dict[str, object] = {
            "book_id": book,
            "account_type": account_type,
            "name": name,
            "placeholder": placeholder,
        }
        if account_type in {"ASSET", "LIABILITY"}:
            kwargs.update(
                currency_code=currency,
                tracking_start_date="2026-01-01",
                tracking_start_time="00:00:00",
            )
        return accounts.create_account(**kwargs)

    bank = create_account("ASSET", "Bank", "EUR")
    savings = create_account("ASSET", "Savings", "EUR")
    cash_usd = create_account("ASSET", "Cash USD", "USD")
    loan = create_account("LIABILITY", "Loan", "EUR")
    groceries = create_account("EXPENSE", "Groceries")
    dining = create_account("EXPENSE", "Dining")
    interest = create_account("EXPENSE", "Interest")
    placeholder = create_account("EXPENSE", "Placeholder", placeholder=True)
    archived = create_account("EXPENSE", "Archived")
    accounts.set_archived(book, archived.id, True)
    salary = create_account("INCOME", "Salary")
    equity = create_account("EQUITY", "Equity")

    other_asset = accounts.create_account(
        book_id=ledger_env.other_book_id,
        account_type="ASSET",
        name="Other book asset",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )

    for balance_account, amount, currency in (
        (bank, 100_000_000, "EUR"),
        (savings, 10_000_000, "EUR"),
        (cash_usd, 2_000_000, "USD"),
        (loan, -50_000_000, "EUR"),
    ):
        ledger.create_opening_balance(
            book_id=book,
            account_id=balance_account.id,
            equity_account_id=equity.id,
            quantity_minor=amount,
            currency_code=currency,
            transaction_date="2026-01-01",
            transaction_time="00:00:00",
        )

    reversible: list[int] = []
    start = date(2026, 1, 2)
    for index in range(1000):
        tx_date = (start + timedelta(days=index)).isoformat()
        mode = index % 8
        if mode == 0:
            tx = ledger.create_expense(
                book_id=book,
                source_account_id=bank.id,
                expense_account_id=groceries.id,
                amount_minor=rng.randint(100, 20_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
            reversible.append(tx.id)
        elif mode == 1:
            tx = ledger.create_income(
                book_id=book,
                destination_account_id=bank.id,
                income_account_id=salary.id,
                amount_minor=rng.randint(10_000, 200_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
        elif mode == 2:
            tx = ledger.create_transfer(
                book_id=book,
                source_account_id=bank.id,
                destination_account_id=savings.id,
                amount_minor=rng.randint(100, 30_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
        elif mode == 3:
            tx = ledger.create_refund(
                book_id=book,
                destination_account_id=bank.id,
                expense_account_id=groceries.id,
                amount_minor=rng.randint(1, 5_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
        elif mode == 4:
            total = rng.randint(1_000, 30_000)
            first = total // 2
            tx = ledger.create_transaction(
                TransactionDraft(
                    book_id=book,
                    kind="EXPENSE",
                    transaction_date=tx_date,
                    currency_code="EUR",
                    entries=(
                        EntryDraft(bank.id, -total, -total),
                        EntryDraft(groceries.id, first, None),
                        EntryDraft(dining.id, total - first, None),
                    ),
                )
            )
            reversible.append(tx.id)
        elif mode == 5:
            payment = rng.randint(2_000, 25_000)
            interest_minor = rng.randint(1, max(1, payment // 4))
            principal = payment - interest_minor
            tx = ledger.create_transaction(
                TransactionDraft(
                    book_id=book,
                    kind="TRANSFER",
                    transaction_date=tx_date,
                    currency_code="EUR",
                    entries=(
                        EntryDraft(bank.id, -payment, -payment),
                        EntryDraft(loan.id, principal, principal),
                        EntryDraft(interest.id, interest_minor, None),
                    ),
                )
            )
        elif mode == 6:
            eur_value = rng.randint(100, 20_000)
            usd_quantity = eur_value + rng.randint(1, 4_000)
            tx = ledger.create_transaction(
                TransactionDraft(
                    book_id=book,
                    kind="EXPENSE",
                    transaction_date=tx_date,
                    currency_code="EUR",
                    original_amount_minor=usd_quantity,
                    original_currency_code="USD",
                    entries=(
                        EntryDraft(cash_usd.id, -eur_value, -usd_quantity),
                        EntryDraft(dining.id, eur_value, None),
                    ),
                )
            )
            reversible.append(tx.id)
        else:
            tx = ledger.create_reversal(
                book_id=book,
                transaction_id=reversible.pop(0),
                transaction_date=tx_date,
            )
        assert sum(entry.value_minor for entry in tx.entries) == 0

    assert db.connection.execute("SELECT COUNT(*) FROM transactions WHERE book_id = ?", (book,)).fetchone()[0] == 1004

    invalid_builders = (
        lambda: ledger.create_transaction(
            TransactionDraft(book, "EXPENSE", "2027-01-01", "EUR", (EntryDraft(bank.id, -1000, -1000), EntryDraft(groceries.id, 999, None)))
        ),
        lambda: ledger.create_expense(book_id=book, source_account_id=bank.id, expense_account_id=groceries.id, amount_minor=0, currency_code="EUR", transaction_date="2027-01-01"),
        lambda: ledger.create_expense(book_id=book, source_account_id=bank.id, expense_account_id=groceries.id, amount_minor=1000, currency_code="USD", transaction_date="2027-01-01"),
        lambda: ledger.create_expense(book_id=book, source_account_id=other_asset.id, expense_account_id=groceries.id, amount_minor=1000, currency_code="EUR", transaction_date="2027-01-01"),
        lambda: ledger.create_expense(book_id=book, source_account_id=bank.id, expense_account_id=placeholder.id, amount_minor=1000, currency_code="EUR", transaction_date="2027-01-01"),
        lambda: ledger.create_expense(book_id=book, source_account_id=bank.id, expense_account_id=archived.id, amount_minor=1000, currency_code="EUR", transaction_date="2027-01-01"),
        lambda: ledger.create_transaction(
            TransactionDraft(book, "EXPENSE", "2027-01-01", "EUR", (EntryDraft(bank.id, -1000.0, -1000), EntryDraft(groceries.id, 1000, None)))  # type: ignore[arg-type]
        ),
        lambda: ledger.create_expense(book_id=book, source_account_id=bank.id, expense_account_id=groceries.id, amount_minor=1000, currency_code="EUR", transaction_date="2025-12-31"),
        lambda: ledger.create_transaction(TransactionDraft(book, "EXPENSE", "2027-01-01", "EUR", (EntryDraft(bank.id, -1000, -1000),))),
        lambda: ledger.create_transaction(
            TransactionDraft(book, "EXPENSE", "2027-01-01", "EUR", (EntryDraft(bank.id, -1000, -1000), EntryDraft(groceries.id, 1000, 1000)))
        ),
    )
    for index in range(1000):
        before = (
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        )
        with pytest.raises(FinanceTrackerError):
            invalid_builders[index % len(invalid_builders)]()
        after = (
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        )
        assert after == before

    assert not db.connection.execute(
        "SELECT transaction_id FROM entries GROUP BY transaction_id HAVING SUM(value_minor) <> 0"
    ).fetchall()
    assert not db.connection.execute(
        "SELECT transaction_id FROM entries GROUP BY transaction_id HAVING COUNT(*) < 2"
    ).fetchall()
    for balance_account in (bank, savings, cash_usd, loan):
        expected = int(
            db.connection.execute(
                "SELECT COALESCE(SUM(quantity_minor), 0) FROM entries WHERE book_id = ? AND account_id = ?",
                (book, balance_account.id),
            ).fetchone()[0]
        )
        assert accounts.native_balance(book, balance_account.id) == expected
    db.integrity_check()
    backup = tmp_path / "m2-backup.db"
    db.backup_to(backup)
    verify = sqlite3.connect(backup)
    try:
        assert verify.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not verify.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        verify.close()


def test_m3_thousand_case_payee_category_history_and_invalid_state_stress(ledger_env) -> None:
    rng = random.Random(2026082403)
    db = ledger_env.db
    accounts = ledger_env.accounts
    ledger = ledger_env.ledger
    book = ledger_env.book_id
    other_book = ledger_env.other_book_id
    payees = PayeeService(db)
    categories = CategoryService(db, accounts)

    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    equity = accounts.create_account(book_id=book, account_type="EQUITY", name="Opening")
    ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=200_000_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )

    roots = [
        categories.create_category(book_id=book, category_type="EXPENSE", name=f"Group {index}", placeholder=True)
        for index in range(10)
    ]
    selectable = [
        categories.create_category(
            book_id=book,
            category_type="EXPENSE",
            name=f"Category {root_index}-{child_index}",
            parent_id=roots[root_index].id,
        )
        for root_index in range(10)
        for child_index in range(10)
    ]
    merchant_ids: list[int] = []
    for index in range(250):
        payee = payees.create_payee(book_id=book, name=f"Merchant {index:03d}")
        merchant_ids.append(payee.id)
        payees.add_alias(book_id=book, payee_id=payee.id, alias=f"M{index:03d} STORE", match_type="EXACT" if index % 2 == 0 else "PREFIX")

    transaction_ids: list[int] = []
    start = date(2026, 1, 2)
    for index in range(1000):
        tx = ledger.create_expense(
            book_id=book,
            source_account_id=bank.id,
            expense_account_id=rng.choice(selectable).id,
            amount_minor=rng.randint(100, 25_000),
            currency_code="EUR",
            transaction_date=(start + timedelta(days=index)).isoformat(),
        )
        payee_id = rng.choice(merchant_ids)
        payees.assign_transaction(book_id=book, transaction_id=tx.id, payee_id=payee_id)
        transaction_ids.append(tx.id)
        if index % 40 == 0:
            assert len(payees.suggest_payees(book, "M", limit=5)) <= 5
            assert len(categories.suggest_categories(book, "Cat", payee_id=payee_id, limit=5)) <= 5

    archived = payees.set_archived(book, merchant_ids[200], True)
    other_payee = payees.create_payee(book_id=other_book, name="Foreign Merchant")
    other_category = categories.create_category(book_id=other_book, category_type="EXPENSE", name="Foreign Category")
    target_tx = transaction_ids[0]

    invalid_builders = (
        lambda: payees.create_payee(book_id=book, name=" merchant 000 "),
        lambda: payees.add_alias(book_id=book, payee_id=merchant_ids[1], alias="Merchant 000"),
        lambda: payees.add_alias(book_id=book, payee_id=merchant_ids[1], alias="M000 STORE"),
        lambda: payees.assign_transaction(book_id=book, transaction_id=target_tx, payee_id=other_payee.id),
        lambda: payees.assign_transaction(book_id=book, transaction_id=target_tx, payee_id=archived.id),
        lambda: categories.create_category(book_id=book, category_type="EXPENSE", name="Category 0-0", parent_id=roots[0].id),
        lambda: categories.create_category(book_id=book, category_type="ASSET", name="Invalid"),
        lambda: categories.suggest_categories(book, "", limit=0),
        lambda: categories.category_path(book, other_category.id),
        lambda: categories.move_category(book, selectable[0].id, selectable[0].id),
    )
    for index in range(1000):
        before_counts = (
            db.connection.execute("SELECT COUNT(*) FROM payees").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        )
        before_payee = db.connection.execute("SELECT payee_id FROM transactions WHERE id = ?", (target_tx,)).fetchone()[0]
        with pytest.raises(FinanceTrackerError):
            invalid_builders[index % len(invalid_builders)]()
        after_counts = (
            db.connection.execute("SELECT COUNT(*) FROM payees").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        )
        assert after_counts == before_counts
        assert db.connection.execute("SELECT payee_id FROM transactions WHERE id = ?", (target_tx,)).fetchone()[0] == before_payee

    before_payee = db.connection.execute("SELECT payee_id FROM transactions WHERE id = ?", (transaction_ids[1],)).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute("UPDATE transactions SET payee_id = ? WHERE id = ?", (other_payee.id, transaction_ids[1]))
    assert db.connection.execute("SELECT payee_id FROM transactions WHERE id = ?", (transaction_ids[1],)).fetchone()[0] == before_payee

    for source_id, target_id in zip(merchant_ids[225:245], merchant_ids[0:20], strict=True):
        payees.merge_payees(book_id=book, source_id=source_id, target_id=target_id)
        assert payees.get_payee(book, source_id).archived
        assert not db.connection.execute("SELECT 1 FROM transactions WHERE book_id = ? AND payee_id = ?", (book, source_id)).fetchall()

    assert not db.connection.execute(
        "SELECT normalized_name FROM payees WHERE book_id = ? GROUP BY normalized_name HAVING COUNT(*) > 1",
        (book,),
    ).fetchall()
    assert not db.connection.execute(
        "SELECT normalized_alias FROM payee_aliases WHERE book_id = ? GROUP BY normalized_alias HAVING COUNT(*) > 1",
        (book,),
    ).fetchall()
    assert not db.connection.execute(
        """
        SELECT 1 FROM payees p JOIN payee_aliases a
          ON a.book_id = p.book_id AND a.normalized_alias = p.normalized_name
        WHERE p.book_id = ? AND p.archived = 0
        """,
        (book,),
    ).fetchall()
    db.integrity_check()


def test_m4_thousand_valid_and_invalid_controller_workflow_cases(tmp_path) -> None:
    rng = random.Random(2026082404)
    db = Database(tmp_path / "m4-thousand.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    ledger = LedgerService(db)
    books = BookService(db)
    payees = PayeeService(db)
    controller = AppController(db, Settings(), accounts, ledger, books, payees)
    try:
        assert controller.initial_state()["needsSetup"] is True
        controller.setup({"userName": "Stress User", "bookName": "Stress Book", "currency": "EUR"})
        assert controller.initial_state()["needsSetup"] is False

        bank = controller.create_account({"type": "ASSET", "name": "Bank", "currency": "EUR", "trackingStartDate": "2026-01-01", "trackingStartTime": "00:00"})["id"]
        cash = controller.create_account({"type": "ASSET", "name": "Cash", "currency": "EUR", "trackingStartDate": "2026-01-01", "trackingStartTime": "00:00"})["id"]
        category_ids = [controller.create_account({"type": "EXPENSE", "name": f"Category {index}"})["id"] for index in range(20)]
        placeholder = controller.create_account({"type": "EXPENSE", "name": "Group", "placeholder": True})["id"]
        merchant_ids = [controller.create_payee(f"Merchant {index:03d}")["id"] for index in range(100)]

        start = date(2026, 1, 2)
        for index in range(1000):
            result = controller.create_expense(
                {
                    "sourceAccountId": bank if index % 4 else cash,
                    "categoryAccountId": rng.choice(category_ids),
                    "payeeId": rng.choice(merchant_ids),
                    "amount": f"{rng.randint(1, 500)},{rng.randint(0, 99):02d}",
                    "date": (start + timedelta(days=index)).isoformat(),
                    "description": f"Workflow stress {index}",
                }
            )
            assert result["id"] > 0
            assert result["state"]["book"]["currency"] == "EUR"
            if index % 100 == 0:
                assert len(controller.suggest_payees("Merchant")) == 5

        assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1000
        assert db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2000
        assert len(controller.snapshot()["transactions"]) == 100

        invalid_payloads = (
            {"sourceAccountId": bank, "categoryAccountId": category_ids[0], "amount": "", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": category_ids[0], "amount": "-2,00", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": category_ids[0], "amount": "12,345", "date": "2029-01-01"},
            {"sourceAccountId": 0, "categoryAccountId": category_ids[0], "amount": "2,00", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": 999999, "amount": "2,00", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": category_ids[0], "payeeId": 999999, "amount": "2,00", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": category_ids[0], "amount": "2,00", "date": "2025-12-31"},
            {"sourceAccountId": category_ids[0], "categoryAccountId": category_ids[1], "amount": "2,00", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": bank, "amount": "2,00", "date": "2029-01-01"},
            {"sourceAccountId": True, "categoryAccountId": category_ids[0], "amount": "2,00", "date": "2029-01-01"},
            {"sourceAccountId": bank, "categoryAccountId": placeholder, "amount": "2,00", "date": "2029-01-01"},
        )
        for index in range(1000):
            before = (
                db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            )
            with pytest.raises(FinanceTrackerError):
                controller.create_expense(dict(invalid_payloads[index % len(invalid_payloads)]))
            after = (
                db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            )
            assert after == before

        for index in range(1000):
            suggestions = controller.suggest_payees(f"Merchant {index % 100:03d}")
            assert len(suggestions) <= 5

        db.integrity_check()
        assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        db.close()
