import pytest

from core.errors import (
    AccountArchivedError,
    AccountPlaceholderError,
    CrossBookReferenceError,
    LedgerValidationError,
    TrackingBoundaryAmbiguousError,
    TrackingBoundaryError,
    UnbalancedTransactionError,
)
from core.ledger_service import EntryDraft, TransactionDraft


def _base_accounts(env):
    bank = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="16:00:00",
    )
    savings = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Savings",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="16:00:00",
    )
    expense = env.accounts.create_account(
        book_id=env.book_id,
        account_type="EXPENSE",
        name="Food",
    )
    income = env.accounts.create_account(
        book_id=env.book_id,
        account_type="INCOME",
        name="Salary",
    )
    equity = env.accounts.create_account(
        book_id=env.book_id,
        account_type="EQUITY",
        name="Opening Balance",
    )
    return bank, savings, expense, income, equity


def test_opening_income_expense_transfer_and_reversal(ledger_env) -> None:
    bank, savings, expense, income, equity = _base_accounts(ledger_env)
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=250000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="16:00:00",
    )
    ledger_env.ledger.create_income(
        book_id=ledger_env.book_id,
        destination_account_id=bank.id,
        income_account_id=income.id,
        amount_minor=200000,
        currency_code="EUR",
        transaction_date="2026-08-26",
    )
    expense_tx = ledger_env.ledger.create_expense(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=4273,
        currency_code="EUR",
        transaction_date="2026-08-27",
    )
    ledger_env.ledger.create_transfer(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        destination_account_id=savings.id,
        amount_minor=50000,
        currency_code="EUR",
        transaction_date="2026-08-28",
    )
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 395727
    assert ledger_env.accounts.native_balance(ledger_env.book_id, savings.id) == 50000

    ledger_env.ledger.create_reversal(
        book_id=ledger_env.book_id,
        transaction_id=expense_tx.id,
        transaction_date="2026-08-29",
    )
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 400000


def test_split_transaction_balances_atomically(ledger_env) -> None:
    bank, _, expense, _, equity = _base_accounts(ledger_env)
    books = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Books",
    )
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=20000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="16:00:00",
    )
    transaction = ledger_env.ledger.create_transaction(
        TransactionDraft(
            book_id=ledger_env.book_id,
            kind="EXPENSE",
            transaction_date="2026-08-26",
            currency_code="EUR",
            entries=(
                EntryDraft(bank.id, -10000, -10000),
                EntryDraft(expense.id, 6000, None),
                EntryDraft(books.id, 4000, None),
            ),
        )
    )
    assert len(transaction.entries) == 3
    assert sum(entry.value_minor for entry in transaction.entries) == 0
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 10000


def test_multicurrency_quantity_and_value_are_independent(ledger_env) -> None:
    eur = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Cash EUR",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    usd = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="ASSET",
        name="Cash USD",
        currency_code="USD",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    equity = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EQUITY",
        name="Opening",
    )
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=eur.id,
        equity_account_id=equity.id,
        quantity_minor=10000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="00:00:00",
    )
    ledger_env.ledger.create_transaction(
        TransactionDraft(
            book_id=ledger_env.book_id,
            kind="TRANSFER",
            transaction_date="2026-08-26",
            currency_code="EUR",
            entries=(
                EntryDraft(eur.id, -10000, -10000),
                EntryDraft(usd.id, 10000, 11500),
            ),
        )
    )
    assert ledger_env.accounts.native_balance(ledger_env.book_id, eur.id) == 0
    assert ledger_env.accounts.native_balance(ledger_env.book_id, usd.id) == 11500


def test_unbalanced_transaction_rolls_back(ledger_env) -> None:
    bank, _, expense, _, _ = _base_accounts(ledger_env)
    before = ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    with pytest.raises(UnbalancedTransactionError):
        ledger_env.ledger.create_transaction(
            TransactionDraft(
                book_id=ledger_env.book_id,
                kind="EXPENSE",
                transaction_date="2026-08-26",
                currency_code="EUR",
                entries=(
                    EntryDraft(bank.id, -1000, -1000),
                    EntryDraft(expense.id, 999, None),
                ),
            )
        )
    after = ledger_env.db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert after == before


def test_tracking_boundary_requires_manual_resolution_when_time_is_missing(ledger_env) -> None:
    bank, _, expense, _, equity = _base_accounts(ledger_env)
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=250000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="16:00:00",
    )
    with pytest.raises(TrackingBoundaryError):
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=expense.id,
            amount_minor=5000,
            currency_code="EUR",
            transaction_date="2026-08-25",
            transaction_time="12:00:00",
        )
    with pytest.raises(TrackingBoundaryAmbiguousError):
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=expense.id,
            amount_minor=5000,
            currency_code="EUR",
            transaction_date="2026-08-25",
        )
    ledger_env.ledger.create_expense(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=5000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="22:00:00",
    )
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 245000


def test_cross_book_and_account_state_are_rejected(ledger_env) -> None:
    bank, _, expense, _, _ = _base_accounts(ledger_env)
    other_asset = ledger_env.accounts.create_account(
        book_id=ledger_env.other_book_id,
        account_type="ASSET",
        name="Other bank",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    with pytest.raises(CrossBookReferenceError):
        ledger_env.ledger.create_transaction(
            TransactionDraft(
                book_id=ledger_env.book_id,
                kind="TRANSFER",
                transaction_date="2026-08-26",
                currency_code="EUR",
                entries=(
                    EntryDraft(bank.id, -1000, -1000),
                    EntryDraft(other_asset.id, 1000, 1000),
                ),
            )
        )

    placeholder = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EXPENSE",
        name="Placeholder",
        placeholder=True,
    )
    with pytest.raises(AccountPlaceholderError):
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=placeholder.id,
            amount_minor=1000,
            currency_code="EUR",
            transaction_date="2026-08-26",
        )

    ledger_env.accounts.set_archived(ledger_env.book_id, expense.id, True)
    with pytest.raises(AccountArchivedError):
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=expense.id,
            amount_minor=1000,
            currency_code="EUR",
            transaction_date="2026-08-26",
        )


def test_float_and_invalid_quantity_semantics_are_rejected(ledger_env) -> None:
    bank, _, expense, _, _ = _base_accounts(ledger_env)
    with pytest.raises(LedgerValidationError):
        ledger_env.ledger.create_transaction(
            TransactionDraft(
                book_id=ledger_env.book_id,
                kind="EXPENSE",
                transaction_date="2026-08-26",
                currency_code="EUR",
                entries=(
                    EntryDraft(bank.id, -1000.0, -1000),  # type: ignore[arg-type]
                    EntryDraft(expense.id, 1000, None),
                ),
            )
        )
    with pytest.raises(LedgerValidationError):
        ledger_env.ledger.create_transaction(
            TransactionDraft(
                book_id=ledger_env.book_id,
                kind="EXPENSE",
                transaction_date="2026-08-26",
                currency_code="EUR",
                entries=(
                    EntryDraft(bank.id, -1000, None),
                    EntryDraft(expense.id, 1000, None),
                ),
            )
        )


def test_convenience_apis_require_semantic_counterpart_types(ledger_env) -> None:
    bank, _, expense, income, equity = _base_accounts(ledger_env)
    with pytest.raises(LedgerValidationError):
        ledger_env.ledger.create_expense(
            book_id=ledger_env.book_id,
            source_account_id=bank.id,
            expense_account_id=income.id,
            amount_minor=1000,
            currency_code="EUR",
            transaction_date="2026-08-26",
        )
    with pytest.raises(LedgerValidationError):
        ledger_env.ledger.create_income(
            book_id=ledger_env.book_id,
            destination_account_id=bank.id,
            income_account_id=expense.id,
            amount_minor=1000,
            currency_code="EUR",
            transaction_date="2026-08-26",
        )
    with pytest.raises(LedgerValidationError):
        ledger_env.ledger.create_opening_balance(
            book_id=ledger_env.book_id,
            account_id=bank.id,
            equity_account_id=expense.id,
            quantity_minor=1000,
            currency_code="EUR",
            transaction_date="2026-08-25",
            transaction_time="16:00:00",
        )
    assert equity.type == "EQUITY"


def test_refund_reduces_expense_and_restores_asset(ledger_env) -> None:
    bank, _, expense, _, equity = _base_accounts(ledger_env)
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=10000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="16:00:00",
    )
    ledger_env.ledger.create_expense(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=4000,
        currency_code="EUR",
        transaction_date="2026-08-26",
    )
    refund = ledger_env.ledger.create_refund(
        book_id=ledger_env.book_id,
        destination_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=1500,
        currency_code="EUR",
        transaction_date="2026-08-27",
    )
    assert refund.kind == "REFUND"
    assert ledger_env.accounts.native_balance(ledger_env.book_id, bank.id) == 7500
    expense_total = ledger_env.db.connection.execute(
        "SELECT SUM(value_minor) FROM entries WHERE account_id = ? AND book_id = ?",
        (expense.id, ledger_env.book_id),
    ).fetchone()[0]
    assert expense_total == 2500


def test_adjustment_and_liability_sign_semantics(ledger_env) -> None:
    liability = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="LIABILITY",
        name="Car loan",
        currency_code="EUR",
        tracking_start_date="2026-08-25",
        tracking_start_time="00:00:00",
    )
    equity = ledger_env.accounts.create_account(
        book_id=ledger_env.book_id,
        account_type="EQUITY",
        name="Opening",
    )
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=liability.id,
        equity_account_id=equity.id,
        quantity_minor=-240000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="00:00:00",
    )
    assert ledger_env.accounts.native_balance(ledger_env.book_id, liability.id) == -240000
    ledger_env.ledger.create_adjustment(
        book_id=ledger_env.book_id,
        account_id=liability.id,
        equity_account_id=equity.id,
        quantity_minor=10000,
        currency_code="EUR",
        transaction_date="2026-08-26",
        description="Correct residual debt",
    )
    assert ledger_env.accounts.native_balance(ledger_env.book_id, liability.id) == -230000


def test_transaction_cannot_be_reversed_twice(ledger_env) -> None:
    bank, _, expense, _, equity = _base_accounts(ledger_env)
    ledger_env.ledger.create_opening_balance(
        book_id=ledger_env.book_id,
        account_id=bank.id,
        equity_account_id=equity.id,
        quantity_minor=10000,
        currency_code="EUR",
        transaction_date="2026-08-25",
        transaction_time="16:00:00",
    )
    expense_tx = ledger_env.ledger.create_expense(
        book_id=ledger_env.book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=1000,
        currency_code="EUR",
        transaction_date="2026-08-26",
    )
    ledger_env.ledger.create_reversal(
        book_id=ledger_env.book_id,
        transaction_id=expense_tx.id,
        transaction_date="2026-08-27",
    )
    with pytest.raises(LedgerValidationError):
        ledger_env.ledger.create_reversal(
            book_id=ledger_env.book_id,
            transaction_id=expense_tx.id,
            transaction_date="2026-08-28",
        )
