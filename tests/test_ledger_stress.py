from __future__ import annotations

import random

from core.errors import LedgerValidationError
from core.ledger_service import EntryDraft, TransactionDraft


def test_hundred_mixed_transactions_preserve_ledger_invariants(ledger_env) -> None:
    rng = random.Random(20260824)
    a = ledger_env.accounts
    ledger = ledger_env.ledger
    book = ledger_env.book_id

    def account(account_type: str, name: str, currency: str | None = None):
        kwargs = {"book_id": book, "account_type": account_type, "name": name}
        if account_type in {"ASSET", "LIABILITY"}:
            kwargs.update(
                currency_code=currency,
                tracking_start_date="2026-08-25",
                tracking_start_time="16:00:00",
            )
        return a.create_account(**kwargs)

    bank = account("ASSET", "Bank", "EUR")
    savings = account("ASSET", "Savings", "EUR")
    cash = account("ASSET", "Cash EUR", "EUR")
    cash_usd = account("ASSET", "Cash USD", "USD")
    loan = account("LIABILITY", "Car loan", "EUR")
    groceries = account("EXPENSE", "Groceries")
    dining = account("EXPENSE", "Dining")
    transport = account("EXPENSE", "Transport")
    interest = account("EXPENSE", "Interest")
    salary = account("INCOME", "Salary")
    equity = account("EQUITY", "Opening balances")

    created = []
    for balance_account, amount, currency in (
        (bank, 250_000, "EUR"),
        (savings, 50_000, "EUR"),
        (cash, 2_000, "EUR"),
        (cash_usd, 10_000, "USD"),
        (loan, -240_000, "EUR"),
    ):
        created.append(
            ledger.create_opening_balance(
                book_id=book,
                account_id=balance_account.id,
                equity_account_id=equity.id,
                quantity_minor=amount,
                currency_code=currency,
                transaction_date="2026-08-25",
                transaction_time="16:00:00",
            )
        )

    reversible: list[int] = []
    for index in range(95):
        tx_date = f"2026-08-{26 + index % 6:02d}"
        mode = index % 10
        if mode in {0, 1, 2}:
            source = bank if index % 2 == 0 else cash
            category = (groceries, dining, transport)[index % 3]
            tx = ledger.create_expense(
                book_id=book,
                source_account_id=source.id,
                expense_account_id=category.id,
                amount_minor=rng.randint(300, 9_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
            reversible.append(tx.id)
        elif mode == 3:
            tx = ledger.create_income(
                book_id=book,
                destination_account_id=bank.id,
                income_account_id=salary.id,
                amount_minor=rng.randint(50_000, 220_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
        elif mode == 4:
            tx = ledger.create_transfer(
                book_id=book,
                source_account_id=bank.id,
                destination_account_id=savings.id,
                amount_minor=rng.randint(1_000, 20_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
        elif mode == 5:
            tx = ledger.create_refund(
                book_id=book,
                destination_account_id=bank.id,
                expense_account_id=groceries.id,
                amount_minor=rng.randint(100, 3_000),
                currency_code="EUR",
                transaction_date=tx_date,
            )
        elif mode == 6:
            total = rng.randint(3_000, 12_000)
            first = total // 2
            second = total // 3
            tx = ledger.create_transaction(
                TransactionDraft(
                    book_id=book,
                    kind="EXPENSE",
                    transaction_date=tx_date,
                    currency_code="EUR",
                    entries=(
                        EntryDraft(bank.id, -total, -total),
                        EntryDraft(groceries.id, first, None),
                        EntryDraft(dining.id, second, None),
                        EntryDraft(transport.id, total - first - second, None),
                    ),
                )
            )
            reversible.append(tx.id)
        elif mode == 7:
            usd_minor = rng.randint(500, 5_000)
            eur_value = max(1, round(usd_minor * 0.86))
            tx = ledger.create_transaction(
                TransactionDraft(
                    book_id=book,
                    kind="EXPENSE",
                    transaction_date=tx_date,
                    currency_code="EUR",
                    original_amount_minor=usd_minor,
                    original_currency_code="USD",
                    entries=(
                        EntryDraft(cash_usd.id, -eur_value, -usd_minor),
                        EntryDraft(dining.id, eur_value, None),
                    ),
                )
            )
            reversible.append(tx.id)
        elif mode == 8:
            payment = rng.randint(5_000, 20_000)
            interest_minor = rng.randint(300, 2_000)
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
        else:
            tx = ledger.create_reversal(
                book_id=book,
                transaction_id=reversible.pop(0),
                transaction_date=tx_date,
            )
        created.append(tx)

    conn = ledger_env.db.connection
    assert len(created) == 100
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 100
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] >= 200
    assert not conn.execute(
        "SELECT transaction_id FROM entries GROUP BY transaction_id HAVING SUM(value_minor) <> 0"
    ).fetchall()
    assert not conn.execute(
        "SELECT transaction_id FROM entries GROUP BY transaction_id HAVING COUNT(*) < 2"
    ).fetchall()
    assert not conn.execute(
        """
        SELECT e.id
        FROM entries e
        JOIN accounts a ON a.id = e.account_id AND a.book_id = e.book_id
        WHERE (a.type IN ('ASSET', 'LIABILITY') AND e.quantity_minor IS NULL)
           OR (a.type IN ('INCOME', 'EXPENSE', 'EQUITY') AND e.quantity_minor IS NOT NULL)
        """
    ).fetchall()

    for balance_account in (bank, savings, cash, cash_usd, loan):
        sql_balance = int(
            conn.execute(
                "SELECT COALESCE(SUM(quantity_minor), 0) FROM entries WHERE account_id = ?",
                (balance_account.id,),
            ).fetchone()[0]
        )
        assert a.native_balance(book, balance_account.id) == sql_balance

    before_invalid = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    try:
        ledger.create_transaction(
            TransactionDraft(
                book_id=book,
                kind="EXPENSE",
                transaction_date="2026-08-30",
                currency_code="EUR",
                entries=(
                    EntryDraft(bank.id, -1_000, -1_000),
                    EntryDraft(groceries.id, 999, None),
                ),
            )
        )
    except LedgerValidationError:
        pass
    else:
        raise AssertionError("unbalanced stress transaction unexpectedly succeeded")
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before_invalid

    ledger_env.db.integrity_check()
