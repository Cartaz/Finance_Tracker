from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from config.settings import Settings
from core.account_service import AccountService
from core.app_controller import AppController
from core.book_service import BookService
from core.category_service import CategoryService
from core.database import Database
from core.errors import FinanceTrackerError
from core.fx_service import FxService
from core.ledger_service import LedgerService
from core.money import CurrencySpec, parse_money
from core.payee_service import PayeeService
from core.reporting_service import ReportingService
from ui.bridge import Bridge


def test_pre_m6_whole_system_stress(tmp_path) -> None:
    """Exercise every implemented M0-M5 feature in one deterministic workload."""

    rng = random.Random(2026082406)
    db = Database(tmp_path / "general-stress.db")
    db.open()
    db.migrate()
    accounts = AccountService(db)
    books = BookService(db)
    ledger = LedgerService(db)
    payees = PayeeService(db)
    categories = CategoryService(db, accounts)
    fx = FxService(db)
    reporting = ReportingService(db, fx, accounts, categories)
    controller = AppController(
        db,
        Settings(),
        accounts,
        ledger,
        books,
        payees,
        fx,
        reporting,
    )
    bridge = Bridge(controller)

    try:
        # M0/M1: bootstrap, canonical currency metadata and money parsing.
        initial = controller.initial_state()
        assert initial["needsSetup"] is True
        assert len(initial["currencies"]) == 9
        snapshot = controller.setup(
            {"userName": "Stress User", "bookName": "Stress Book", "currency": "EUR"}
        )
        book_id = int(snapshot["book"]["id"])
        assert books.current_book() is not None

        money_specs = (
            CurrencySpec("EUR", 2),
            CurrencySpec("JPY", 0),
            CurrencySpec("KWD", 3),
        )
        for index in range(1_000):
            spec = money_specs[index % len(money_specs)]
            scale = 10**spec.minor_unit_digits
            whole = rng.randrange(0, 1_000_000)
            fraction = rng.randrange(scale) if scale > 1 else 0
            if spec.minor_unit_digits:
                separator = "," if index % 2 else "."
                raw = f"{whole}{separator}{fraction:0{spec.minor_unit_digits}d}"
            else:
                raw = str(whole)
            assert parse_money(raw, spec) == whole * scale + fraction

        # Accounts and category hierarchy.
        bank = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Bank EUR",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
            tracking_start_time="00:00:00",
        )
        cash_usd = accounts.create_account(
            book_id=book_id,
            account_type="ASSET",
            name="Cash USD",
            currency_code="USD",
            tracking_start_date="2026-01-01",
            tracking_start_time="00:00:00",
        )
        liability = accounts.create_account(
            book_id=book_id,
            account_type="LIABILITY",
            name="Card",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
            tracking_start_time="00:00:00",
        )
        equity = accounts.create_account(
            book_id=book_id,
            account_type="EQUITY",
            name="Opening Equity",
        )
        income = categories.create_category(
            book_id=book_id,
            category_type="INCOME",
            name="Income",
        )

        category_parents = [
            categories.create_category(
                book_id=book_id,
                category_type="EXPENSE",
                name=f"Group {index:02d}",
                placeholder=True,
            )
            for index in range(20)
        ]
        expense_categories = []
        for parent_index, parent in enumerate(category_parents):
            for child_index in range(5):
                expense_categories.append(
                    categories.create_category(
                        book_id=book_id,
                        category_type="EXPENSE",
                        name=f"Item {parent_index:02d}-{child_index:02d}",
                        parent_id=parent.id,
                    )
                )
        assert len(expense_categories) == 100

        # Exercise rename/move/archive/path without changing semantic type.
        for index in range(1_000):
            item = expense_categories[index % len(expense_categories)]
            mode = index % 4
            if mode == 0:
                renamed = categories.rename_category(
                    book_id, item.id, f"Item {index % 20:02d}-{index % 5:02d}-R{index}"
                )
                expense_categories[index % len(expense_categories)] = renamed
            elif mode == 1:
                parent = category_parents[(index // 5) % len(category_parents)]
                try:
                    moved = categories.move_category(book_id, item.id, parent.id)
                    expense_categories[index % len(expense_categories)] = moved
                except FinanceTrackerError:
                    # A sibling collision is expected for some deterministic moves.
                    pass
            elif mode == 2:
                assert "Group" in categories.category_path(book_id, item.id)
            else:
                categories.set_archived(book_id, item.id, True)
                categories.set_archived(book_id, item.id, False)

        # Payees, aliases and namespace/autocomplete.
        merchant_items = [
            payees.create_payee(book_id=book_id, name=f"Merchant {index:03d}")
            for index in range(100)
        ]
        for index, merchant in enumerate(merchant_items):
            payees.add_alias(
                book_id=book_id,
                payee_id=merchant.id,
                alias=f"M-{index:03d}",
                match_type="EXACT" if index % 2 == 0 else "PREFIX",
            )

        for index in range(1_000):
            query = f"Merchant {index % 100:03d}" if index % 2 == 0 else f"M-{index % 100:03d}"
            suggestions = payees.suggest_payees(book_id, query, limit=5)
            assert suggestions
            assert suggestions[0].id == merchant_items[index % 100].id

        # Ledger: opening balances plus 1,000 mixed valid transactions.
        ledger.create_opening_balance(
            book_id=book_id,
            account_id=bank.id,
            equity_account_id=equity.id,
            quantity_minor=5_000_000,
            currency_code="EUR",
            transaction_date="2026-01-01",
            transaction_time="00:00:00",
        )
        ledger.create_opening_balance(
            book_id=book_id,
            account_id=cash_usd.id,
            equity_account_id=equity.id,
            quantity_minor=2_000_000,
            currency_code="USD",
            transaction_date="2026-01-01",
            transaction_time="00:00:00",
        )
        ledger.create_opening_balance(
            book_id=book_id,
            account_id=liability.id,
            equity_account_id=equity.id,
            quantity_minor=-500_000,
            currency_code="EUR",
            transaction_date="2026-01-01",
            transaction_time="00:00:00",
        )

        fx.set_rate(
            book_id=book_id,
            currency_code="USD",
            rate_date="2026-01-01",
            rate="0.91",
        )

        created_transaction_ids: list[int] = []
        start = date(2026, 2, 1)
        for index in range(1_000):
            tx_date = (start + timedelta(days=index % 180)).isoformat()
            category = expense_categories[index % len(expense_categories)]
            merchant = merchant_items[index % len(merchant_items)]
            mode = index % 5
            if mode == 0:
                tx = ledger.create_income(
                    book_id=book_id,
                    destination_account_id=bank.id,
                    income_account_id=income.id,
                    amount_minor=5_000 + index,
                    currency_code="EUR",
                    transaction_date=tx_date,
                )
            elif mode == 1:
                tx = ledger.create_expense(
                    book_id=book_id,
                    source_account_id=bank.id,
                    expense_account_id=category.id,
                    amount_minor=100 + index,
                    currency_code="EUR",
                    transaction_date=tx_date,
                )
                payees.assign_transaction(
                    book_id=book_id,
                    transaction_id=tx.id,
                    payee_id=merchant.id,
                )
            elif mode == 2:
                tx = ledger.create_expense(
                    book_id=book_id,
                    source_account_id=cash_usd.id,
                    expense_account_id=category.id,
                    amount_minor=100 + index,
                    currency_code="USD",
                    transaction_date=tx_date,
                )
                payees.assign_transaction(
                    book_id=book_id,
                    transaction_id=tx.id,
                    payee_id=merchant.id,
                )
            elif mode == 3:
                tx = ledger.create_refund(
                    book_id=book_id,
                    destination_account_id=bank.id,
                    expense_account_id=category.id,
                    amount_minor=50 + index,
                    currency_code="EUR",
                    transaction_date=tx_date,
                )
            else:
                tx = ledger.create_transfer(
                    book_id=book_id,
                    source_account_id=bank.id,
                    destination_account_id=liability.id,
                    amount_minor=100 + index,
                    currency_code="EUR",
                    transaction_date=tx_date,
                )
            created_transaction_ids.append(tx.id)
            assert sum(entry.value_minor for entry in tx.entries) == 0

        assert len(created_transaction_ids) == 1_000

        # Category ranking should now be influenced by real merchant history.
        for index in range(1_000):
            merchant = merchant_items[index % len(merchant_items)]
            suggestions = categories.suggest_categories(
                book_id,
                category_type="EXPENSE",
                payee_id=merchant.id,
                limit=5,
            )
            assert suggestions

        # FX: 1,000 exact rate writes/lookups/conversions using Decimal-backed storage.
        for index in range(1_000):
            rate_date = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            rate_text = f"0.{800000 + index:06d}"
            rate = fx.set_rate(
                book_id=book_id,
                currency_code="USD",
                rate_date=rate_date,
                rate=rate_text,
            )
            assert fx.rate_for(book_id, "USD", rate_date) == rate.rate
            converted = fx.convert_minor(
                book_id=book_id,
                amount_minor=10_000 + index,
                currency_code="USD",
                rate_date=rate_date,
            )
            assert isinstance(converted, int)

        # Reporting: 1,000 reads across all report families.
        for index in range(1_000):
            mode = index % 5
            if mode == 0:
                result = reporting.overview(
                    book_id=book_id,
                    start_date="2026-02-01",
                    end_date="2026-07-31",
                    as_of_date="2026-07-31",
                )
                assert result["complete"] is True
            elif mode == 1:
                assert reporting.category_report(
                    book_id=book_id,
                    start_date="2026-02-01",
                    end_date="2026-07-31",
                    limit=20,
                )
            elif mode == 2:
                assert reporting.merchant_report(
                    book_id=book_id,
                    start_date="2026-02-01",
                    end_date="2026-07-31",
                    limit=20,
                )
            elif mode == 3:
                assert reporting.cash_flow(
                    book_id=book_id,
                    start_date="2026-02-01",
                    end_date="2026-07-31",
                    granularity="MONTH",
                )
            else:
                history = reporting.account_history(
                    book_id=book_id,
                    account_id=cash_usd.id if index % 2 else bank.id,
                    start_date="2026-01-01",
                    end_date="2026-07-31",
                )
                assert history["complete"] is True

        # Controller/QWebChannel transport: 1,000 canonical read calls.
        for index in range(1_000):
            if index % 4 == 0:
                result = bridge.getSnapshot()
            elif index % 4 == 1:
                result = bridge.getDashboard(
                    {
                        "startDate": "2026-02-01",
                        "endDate": "2026-07-31",
                        "asOfDate": "2026-07-31",
                    }
                )
            elif index % 4 == 2:
                result = bridge.suggestPayees(f"Merchant {index % 100:03d}")
            else:
                result = bridge.getAccountHistory(
                    {
                        "accountId": bank.id,
                        "startDate": "2026-01-01",
                        "endDate": "2026-07-31",
                    }
                )
            assert result["ok"] is True

        # 1,000 invalid operations must fail without partial writes.
        invalid_actions = (
            lambda: accounts.create_account(
                book_id=book_id,
                account_type="ASSET",
                name="Bad",
                currency_code="EUR",
                tracking_start_date="not-a-date",
            ),
            lambda: categories.create_category(
                book_id=book_id,
                category_type="ASSET",
                name="Bad category",
            ),
            lambda: payees.create_payee(book_id=book_id, name="Merchant 000"),
            lambda: fx.set_rate(
                book_id=book_id,
                currency_code="EUR",
                rate_date="2026-01-01",
                rate="1",
            ),
            lambda: fx.set_rate(
                book_id=book_id,
                currency_code="USD",
                rate_date="bad-date",
                rate="1.2",
            ),
            lambda: ledger.create_expense(
                book_id=book_id,
                source_account_id=bank.id,
                expense_account_id=expense_categories[0].id,
                amount_minor=0,
                currency_code="EUR",
                transaction_date="2026-07-31",
            ),
            lambda: reporting.overview(
                book_id=book_id,
                start_date="2026-08-01",
                end_date="2026-07-01",
                as_of_date="2026-08-01",
            ),
            lambda: reporting.cash_flow(
                book_id=book_id,
                start_date="2026-02-01",
                end_date="2026-07-31",
                granularity="WEEK",
            ),
            lambda: controller.create_account(
                {"type": "ASSET", "name": "Bad controller account", "currency": "XXX"}
            ),
            lambda: controller.dashboard(
                {"startDate": "bad", "endDate": "2026-07-31", "asOfDate": "2026-07-31"}
            ),
        )

        before = {
            "accounts": db.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "transactions": db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            "entries": db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "payees": db.connection.execute("SELECT COUNT(*) FROM payees").fetchone()[0],
            "aliases": db.connection.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0],
            "fx": db.connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0],
        }
        for index in range(1_000):
            with pytest.raises(FinanceTrackerError):
                invalid_actions[index % len(invalid_actions)]()
        after = {
            "accounts": db.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "transactions": db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            "entries": db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "payees": db.connection.execute("SELECT COUNT(*) FROM payees").fetchone()[0],
            "aliases": db.connection.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0],
            "fx": db.connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0],
        }
        assert after == before

        # Database integrity and backup/restore after the full workload.
        db.integrity_check()
        assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()
        backup_path = tmp_path / "backup" / "general-stress-backup.db"
        db.backup_to(backup_path)
        restored = Database(backup_path)
        restored.open()
        try:
            restored.integrity_check()
            assert restored.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before["transactions"]
            assert restored.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == before["entries"]
            assert restored.connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == before["fx"]
        finally:
            restored.close()
    finally:
        db.close()
