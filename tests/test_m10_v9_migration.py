from __future__ import annotations

from core.account_service import AccountService
from core.book_service import BookService
from core.database import Database
from core.migration_catalog import apply_migrations


def test_v8_loan_migrates_to_explicit_fixed_french_policy(tmp_path) -> None:
    path = tmp_path / "v8-loan.db"
    old = Database(path)
    old.open()
    with old.transaction() as conn:
        apply_migrations(conn, current_version=0, target_version=8)
    book = BookService(old).create_personal_book(
        user_name="User", book_name="Book", currency_code="EUR"
    )
    accounts = AccountService(old)
    liability = accounts.create_account(
        book_id=book.id,
        account_type="LIABILITY",
        name="Legacy loan",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    payment = accounts.create_account(
        book_id=book.id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    interest = accounts.create_account(
        book_id=book.id,
        account_type="EXPENSE",
        name="Interest",
    )
    with old.transaction() as conn:
        loan_id = int(
            conn.execute(
                """
                INSERT INTO loans(
                    book_id,name,liability_account_id,payment_account_id,
                    interest_expense_account_id,currency_code,
                    original_principal_minor,annual_rate_bps,term_months,
                    first_due_date,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,? ,datetime('now'),datetime('now'))
                """,
                (
                    book.id,
                    "Legacy",
                    liability.id,
                    payment.id,
                    interest.id,
                    "EUR",
                    100_000,
                    525,
                    24,
                    "2026-02-01",
                ),
            ).lastrowid
        )
    assert old.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 8
    old.close()

    upgraded = Database(path)
    try:
        upgraded.open()
        upgraded.migrate()
        row = upgraded.connection.execute(
            """
            SELECT rate_type,amortization_type,recast_strategy
            FROM loans WHERE id=?
            """,
            (loan_id,),
        ).fetchone()
        assert tuple(row) == ("FIXED", "FRENCH", "REDUCE_PAYMENT")
        payment_columns = {
            item[1]
            for item in upgraded.connection.execute(
                "PRAGMA table_info(loan_payments)"
            ).fetchall()
        }
        assert {
            "annual_rate_bps",
            "payment_kind",
            "recast_strategy",
        } <= payment_columns
        assert upgraded.connection.execute(
            "SELECT COUNT(*) FROM loan_rate_revisions"
        ).fetchone()[0] == 0
        upgraded.integrity_check()
    finally:
        upgraded.close()
