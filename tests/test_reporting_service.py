from __future__ import annotations

from core.category_service import CategoryService
from core.fx_service import FxService
from core.ledger_service import EntryDraft, TransactionDraft
from core.payee_service import PayeeService
from core.reporting_service import ReportingService


def _reporting_fixture(env):
    accounts = env.accounts
    ledger = env.ledger
    book = env.book_id
    bank = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Bank EUR",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    usd = accounts.create_account(
        book_id=book,
        account_type="ASSET",
        name="Cash USD",
        currency_code="USD",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    loan = accounts.create_account(
        book_id=book,
        account_type="LIABILITY",
        name="Loan",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    equity = accounts.create_account(book_id=book, account_type="EQUITY", name="Opening")
    categories = CategoryService(env.db, accounts)
    food_root = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Food",
        placeholder=True,
    )
    groceries = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Groceries",
        parent_id=food_root.id,
    )
    dining = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Dining",
        parent_id=food_root.id,
    )
    salary = categories.create_category(
        book_id=book,
        category_type="INCOME",
        name="Salary",
    )
    interest = categories.create_category(
        book_id=book,
        category_type="EXPENSE",
        name="Interest",
    )
    payees = PayeeService(env.db)
    market = payees.create_payee(book_id=book, name="Market")
    restaurant = payees.create_payee(book_id=book, name="Restaurant")

    ledger.create_opening_balance(
        book_id=book,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=100_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )
    ledger.create_opening_balance(
        book_id=book,
        account_id=usd.id,
        equity_account_id=equity.id,
        quantity_minor=10_000,
        currency_code="USD",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )
    ledger.create_opening_balance(
        book_id=book,
        account_id=loan.id,
        equity_account_id=equity.id,
        quantity_minor=-20_000,
        currency_code="EUR",
        transaction_date="2026-01-01",
        transaction_time="00:00:00",
    )
    ledger.create_income(
        book_id=book,
        destination_account_id=bank.id,
        income_account_id=salary.id,
        amount_minor=300_000,
        currency_code="EUR",
        transaction_date="2026-01-10",
    )
    grocery_tx = ledger.create_expense(
        book_id=book,
        source_account_id=bank.id,
        expense_account_id=groceries.id,
        amount_minor=10_000,
        currency_code="EUR",
        transaction_date="2026-01-12",
    )
    payees.assign_transaction(
        book_id=book,
        transaction_id=grocery_tx.id,
        payee_id=market.id,
    )
    usd_tx = ledger.create_transaction(
        TransactionDraft(
            book_id=book,
            kind="EXPENSE",
            transaction_date="2026-01-15",
            currency_code="USD",
            entries=(
                EntryDraft(usd.id, -1_000, -1_000),
                EntryDraft(dining.id, 1_000, None),
            ),
        )
    )
    payees.assign_transaction(
        book_id=book,
        transaction_id=usd_tx.id,
        payee_id=restaurant.id,
    )
    ledger.create_refund(
        book_id=book,
        destination_account_id=bank.id,
        expense_account_id=groceries.id,
        amount_minor=2_000,
        currency_code="EUR",
        transaction_date="2026-01-18",
    )
    ledger.create_transaction(
        TransactionDraft(
            book_id=book,
            kind="TRANSFER",
            transaction_date="2026-01-20",
            currency_code="EUR",
            entries=(
                EntryDraft(bank.id, -5_000, -5_000),
                EntryDraft(loan.id, 4_000, 4_000),
                EntryDraft(interest.id, 1_000, None),
            ),
        )
    )
    fx = FxService(env.db)
    fx.set_rate(
        book_id=book,
        currency_code="USD",
        rate_date="2026-01-01",
        rate="0.90",
    )
    fx.set_rate(
        book_id=book,
        currency_code="USD",
        rate_date="2026-01-15",
        rate="0.92",
    )
    fx.set_rate(
        book_id=book,
        currency_code="USD",
        rate_date="2026-01-31",
        rate="0.95",
    )
    reporting = ReportingService(env.db, fx, accounts, categories)
    return {
        "reporting": reporting,
        "fx": fx,
        "bank": bank,
        "usd": usd,
        "loan": loan,
        "groceries": groceries,
        "dining": dining,
        "salary": salary,
        "interest": interest,
        "market": market,
        "restaurant": restaurant,
    }


def test_overview_is_fx_aware_and_uses_income_expense_semantics(ledger_env) -> None:
    data = _reporting_fixture(ledger_env)
    overview = data["reporting"].overview(
        book_id=ledger_env.book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        as_of_date="2026-01-31",
    )
    assert overview["complete"] is True
    assert overview["incomeMinor"] == 300_000
    assert overview["expenseMinor"] == 9_920
    assert overview["savingMinor"] == 290_080
    assert overview["savingRateBps"] == 9_669
    assert overview["assetsMinor"] == 466_550
    assert overview["liabilitiesMinor"] == -16_000
    assert overview["netWorthMinor"] == 450_550
    assert overview["missingFx"] == []


def test_category_merchant_cashflow_and_history_are_backend_aggregates(ledger_env) -> None:
    data = _reporting_fixture(ledger_env)
    reporting = data["reporting"]
    categories = reporting.category_report(
        book_id=ledger_env.book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    by_path = {item["path"]: item for item in categories}
    assert by_path["Food › Groceries"]["amountMinor"] == 8_000
    assert by_path["Food › Dining"]["amountMinor"] == 920
    assert by_path["Interest"]["amountMinor"] == 1_000

    merchants = reporting.merchant_report(
        book_id=ledger_env.book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    by_name = {item["name"]: item for item in merchants}
    assert by_name["Market"]["amountMinor"] == 10_000
    assert by_name["Restaurant"]["amountMinor"] == 920
    assert by_name["Senza merchant"]["amountMinor"] == -1_000

    cash_flow = reporting.cash_flow(
        book_id=ledger_env.book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert cash_flow == [
        {
            "period": "2026-01",
            "incomeMinor": 300_000,
            "expenseMinor": 9_920,
            "netMinor": 290_080,
            "complete": True,
            "missingFx": [],
        }
    ]

    history = reporting.account_history(
        book_id=ledger_env.book_id,
        account_id=data["usd"].id,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert history["endingBalanceMinor"] == 9_000
    assert history["endingBaseValueMinor"] == 8_550
    assert history["complete"] is True


def test_missing_fx_fails_closed_instead_of_returning_partial_totals(ledger_env) -> None:
    data = _reporting_fixture(ledger_env)
    gbp = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Cash GBP",
        currency_code="GBP",
        tracking_start_date="2026-01-01",
        tracking_start_time="00:00:00",
    )
    equity = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EQUITY",
        name="GBP opening",
    )
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=gbp.id,
        equity_account_id=equity.id,
        quantity_minor=5_000,
        currency_code="GBP",
        transaction_date="2026-01-25",
        transaction_time="00:00:00",
    )
    overview = data["reporting"].overview(
        book_id=ledger_env.book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        as_of_date="2026-01-31",
    )
    assert overview["netWorthComplete"] is False
    assert overview["netWorthMinor"] is None
    assert overview["assetsMinor"] is None
    assert overview["incomeMinor"] == 300_000
    assert overview["expenseMinor"] == 9_920
    assert overview["missingFx"] == [{"currency": "GBP", "date": "2026-01-31"}]


def test_dashboard_composes_canonical_reporting_without_new_state(ledger_env) -> None:
    data = _reporting_fixture(ledger_env)
    dashboard = data["reporting"].dashboard(
        book_id=ledger_env.book_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        as_of_date="2026-01-31",
    )
    assert dashboard["baseCurrency"] == "EUR"
    assert dashboard["overview"]["netWorthMinor"] == 450_550
    assert dashboard["categories"][0]["path"] == "Food › Groceries"
    assert dashboard["cashFlow"][0]["netMinor"] == 290_080
