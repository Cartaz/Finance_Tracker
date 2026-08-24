from __future__ import annotations

import random

import pytest

from core.category_service import CategoryService
from core.errors import (
    CategoryError,
    CrossBookReferenceError,
    PayeeArchivedError,
    PayeeCollisionError,
    ValidationError,
)
from core.payee_service import PayeeService


def test_m3_stress_payees_aliases_categories_and_invalid_states(ledger_env) -> None:
    rng = random.Random(20260824)
    db = ledger_env.db
    book = ledger_env.book_id
    other_book = ledger_env.other_book_id
    payees = PayeeService(db)
    categories = CategoryService(db, ledger_env.accounts)

    bank = ledger_env.accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    equity = ledger_env.accounts.create_account(book_id=book, account_type="EQUITY", name="Opening")
    ledger_env.ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=5_000_000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="00:00:00",
    )

    roots = []
    selectable = []
    for index in range(5):
        root = categories.create_category(
            book_id=book,
            category_type="EXPENSE",
            name=f"Group {index}",
            placeholder=True,
        )
        roots.append(root)
        for child in range(6):
            selectable.append(
                categories.create_category(
                    book_id=book,
                    category_type="EXPENSE",
                    name=f"Category {index}-{child}",
                    parent_id=root.id,
                )
            )

    merchant_ids = []
    for index in range(60):
        payee = payees.create_payee(book_id=book, name=f"Merchant {index:02d}")
        merchant_ids.append(payee.id)
        payees.add_alias(
            book_id=book,
            payee_id=payee.id,
            alias=f"M{index:02d} STORE",
            match_type="EXACT" if index % 2 == 0 else "PREFIX",
        )

    transaction_ids = []
    for index in range(180):
        category = rng.choice(selectable)
        payee_id = rng.choice(merchant_ids)
        tx = ledger_env.ledger.create_expense(
            book_id=book,
            source_account_id=bank.id,
            expense_account_id=category.id,
            amount_minor=rng.randint(100, 20_000),
            currency_code="EUR",
            transaction_date=f"2026-{9 + (index // 28) % 3:02d}-{1 + index % 28:02d}",
        )
        payees.assign_transaction(book_id=book, transaction_id=tx.id, payee_id=payee_id)
        transaction_ids.append(tx.id)

    assert len(payees.suggest_payees(book, "M", limit=5)) == 5
    assert len(categories.suggest_categories(book, "Cat", limit=5)) == 5

    # Merge ten merchants into five canonical merchants and ensure links move atomically.
    for source_id, target_id in zip(merchant_ids[50:60], merchant_ids[0:10], strict=True):
        payees.merge_payees(book_id=book, source_id=source_id, target_id=target_id)
        assert payees.get_payee(book, source_id).archived
        assert not db.connection.execute(
            "SELECT 1 FROM transactions WHERE book_id = ? AND payee_id = ?",
            (book, source_id),
        ).fetchall()

    invalid_attempts = 0

    def rejected(call, expected) -> None:
        nonlocal invalid_attempts
        before = (
            db.connection.execute("SELECT COUNT(*) FROM payees").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM transactions WHERE payee_id IS NOT NULL").fetchone()[0],
        )
        with pytest.raises(expected):
            call()
        after = (
            db.connection.execute("SELECT COUNT(*) FROM payees").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0],
            db.connection.execute("SELECT COUNT(*) FROM transactions WHERE payee_id IS NOT NULL").fetchone()[0],
        )
        assert after == before
        invalid_attempts += 1

    rejected(
        lambda: payees.create_payee(book_id=book, name=" merchant 00 "),
        PayeeCollisionError,
    )
    rejected(
        lambda: payees.create_payee(book_id=book, name="M00 STORE"),
        PayeeCollisionError,
    )
    rejected(
        lambda: payees.add_alias(
            book_id=book,
            payee_id=merchant_ids[1],
            alias="M00 STORE",
        ),
        PayeeCollisionError,
    )
    rejected(
        lambda: payees.add_alias(
            book_id=book,
            payee_id=merchant_ids[1],
            alias="Merchant 01",
        ),
        PayeeCollisionError,
    )
    rejected(
        lambda: payees.merge_payees(
            book_id=book,
            source_id=merchant_ids[0],
            target_id=merchant_ids[0],
        ),
        ValidationError,
    )

    archived = payees.set_archived(book, merchant_ids[20], True)
    rejected(
        lambda: payees.add_alias(
            book_id=book,
            payee_id=archived.id,
            alias="ARCHIVED ALIAS",
        ),
        PayeeArchivedError,
    )
    rejected(
        lambda: payees.assign_transaction(
            book_id=book,
            transaction_id=transaction_ids[0],
            payee_id=archived.id,
        ),
        PayeeArchivedError,
    )

    other_payee = payees.create_payee(book_id=other_book, name="Foreign merchant")
    rejected(
        lambda: payees.assign_transaction(
            book_id=book,
            transaction_id=transaction_ids[0],
            payee_id=other_payee.id,
        ),
        CrossBookReferenceError,
    )

    rejected(
        lambda: categories.create_category(
            book_id=book,
            category_type="ASSET",
            name="Invalid category",
        ),
        CategoryError,
    )
    rejected(
        lambda: categories.move_category(book, selectable[0].id, selectable[0].id),
        Exception,
    )

    # Direct SQL must also reject a cross-book payee assignment via the schema trigger.
    before_payee = db.connection.execute(
        "SELECT payee_id FROM transactions WHERE id = ?", (transaction_ids[1],)
    ).fetchone()[0]
    with pytest.raises(Exception):
        with db.transaction() as conn:
            conn.execute(
                "UPDATE transactions SET payee_id = ? WHERE id = ?",
                (other_payee.id, transaction_ids[1]),
            )
    assert db.connection.execute(
        "SELECT payee_id FROM transactions WHERE id = ?", (transaction_ids[1],)
    ).fetchone()[0] == before_payee
    invalid_attempts += 1

    assert invalid_attempts >= 10
    assert db.connection.execute("SELECT COUNT(*) FROM payees WHERE book_id = ?", (book,)).fetchone()[0] == 60
    assert db.connection.execute("SELECT COUNT(*) FROM transactions WHERE book_id = ?", (book,)).fetchone()[0] == 181
    assert not db.connection.execute(
        """
        SELECT normalized_name FROM payees
        WHERE book_id = ?
        GROUP BY normalized_name HAVING COUNT(*) > 1
        """,
        (book,),
    ).fetchall()
    assert not db.connection.execute(
        """
        SELECT normalized_alias FROM payee_aliases
        WHERE book_id = ?
        GROUP BY normalized_alias HAVING COUNT(*) > 1
        """,
        (book,),
    ).fetchall()
    db.integrity_check()
