"""Correcting mistakes: reversal, archiving and renaming, with their guards."""

from __future__ import annotations

import pytest

from config.settings import Settings
from core.composition import build_controller
from core.database import Database
from core.errors import LedgerValidationError, ValidationError


@pytest.fixture
def app(tmp_path):
    database = Database(tmp_path / "corrections.db")
    database.migrate()
    controller = build_controller(database, Settings())
    controller.setup({"userName": "u", "bookName": "b", "currency": "EUR"})
    ids = {
        "bank": controller.create_account(
            {"type": "ASSET", "name": "Bank", "currency": "EUR",
             "trackingStartDate": "2026-01-01", "openingBalance": "1000"}
        )["id"],
        "cash": controller.create_account(
            {"type": "ASSET", "name": "Cash", "currency": "EUR", "trackingStartDate": "2026-01-01"}
        )["id"],
        "mortgage": controller.create_account(
            {"type": "LIABILITY", "name": "Mortgage", "currency": "EUR", "trackingStartDate": "2026-01-01"}
        )["id"],
        "food": controller.create_account({"type": "EXPENSE", "name": "Food"})["id"],
    }
    try:
        yield controller, ids
    finally:
        database.close()


def _balance(controller, account_id):
    return next(a for a in controller.snapshot()["accounts"] if a["id"] == account_id)["balanceMinor"]


def _row(controller, transaction_id):
    return next(t for t in controller.snapshot()["transactions"] if t["id"] == transaction_id)


def test_reversal_restores_balances_once_and_keeps_history(app) -> None:
    controller, ids = app
    expense = controller.create_expense(
        {"sourceAccountId": ids["bank"], "categoryAccountId": ids["food"],
         "amount": "25", "date": "2026-03-10", "time": "12:30"}
    )["id"]
    assert _balance(controller, ids["bank"]) == "97500"
    assert _row(controller, expense)["reversible"] is True

    reversal = controller.reverse_transaction({"transactionId": expense})
    assert _balance(controller, ids["bank"]) == "100000"
    stored = controller._ledger.get_transaction(1, reversal["id"])  # noqa: SLF001
    assert (stored.kind, stored.transaction_date, stored.transaction_time) == (
        "REVERSAL", "2026-03-10", "12:30:00",
    )
    assert _row(controller, expense)["reversalBlocker"] == "REVERSED"
    assert _row(controller, reversal["id"])["reversalBlocker"] == "REVERSAL"
    with pytest.raises(LedgerValidationError, match="già stata stornata"):
        controller.reverse_transaction({"transactionId": expense})
    with pytest.raises(LedgerValidationError, match="non può essere stornato"):
        controller.reverse_transaction({"transactionId": reversal["id"]})


def test_reversal_refuses_transactions_owned_by_other_workflows(app) -> None:
    controller, ids = app
    schedule = controller.create_scheduled_transaction(
        {"kind": "EXPENSE", "sourceAccountId": ids["bank"], "counterAccountId": ids["food"],
         "amount": "10", "frequency": "MONTHLY", "interval": "1", "startDate": "2026-02-01"}
    )
    posted = controller.post_due_scheduled({"asOfDate": "2026-02-01", "scheduleId": schedule["id"]})
    occurrence = posted["posted"][0]["transactionId"]
    assert _row(controller, occurrence)["reversalBlocker"] == "SCHEDULED"
    with pytest.raises(LedgerValidationError, match="programmata"):
        controller.reverse_transaction({"transactionId": occurrence})

    loan = controller.create_loan(
        {"name": "Loan", "mode": "NEW_DISBURSEMENT", "liabilityAccountId": ids["mortgage"],
         "paymentAccountId": ids["bank"], "fundingAccountId": ids["bank"],
         "interestExpenseAccountId": ids["food"], "annualRate": "5", "termMonths": "12",
         "principal": "1200", "startDate": "2026-03-01", "firstDueDate": "2026-04-01"}
    )
    origination = loan["originationTransactionId"]
    assert _row(controller, origination)["reversalBlocker"] == "LOAN"
    with pytest.raises(LedgerValidationError, match="prestito"):
        controller.reverse_transaction({"transactionId": origination})


def test_archiving_is_refused_while_it_would_contradict_other_state(app) -> None:
    controller, ids = app

    def archive(account_id, archived=True):
        return controller.set_account_archived({"accountId": account_id, "archived": archived})

    with pytest.raises(ValidationError, match="saldo non è zero"):
        archive(ids["bank"])
    controller.create_scheduled_transaction(
        {"kind": "TRANSFER", "sourceAccountId": ids["bank"], "counterAccountId": ids["cash"],
         "amount": "10", "frequency": "MONTHLY", "interval": "1", "startDate": "2026-02-01"}
    )
    with pytest.raises(ValidationError, match="programmata attiva"):
        archive(ids["cash"])
    groceries = controller.create_account(
        {"type": "EXPENSE", "name": "Groceries", "parentId": ids["food"]}
    )["id"]
    with pytest.raises(ValidationError, match="sottovoci"):
        archive(ids["food"])

    archive(groceries)
    assert next(a for a in controller.snapshot()["accounts"] if a["id"] == groceries)["archived"]
    archive(groceries, archived=False)
    assert not next(a for a in controller.snapshot()["accounts"] if a["id"] == groceries)["archived"]


def test_rename_uses_each_owner_rules(app) -> None:
    controller, ids = app
    controller.rename_account({"accountId": ids["cash"], "name": "Wallet"})
    controller.create_account({"type": "EXPENSE", "name": "Transport"})
    with pytest.raises(ValidationError):
        controller.rename_account({"accountId": ids["food"], "name": "Transport"})
    names = {a["name"] for a in controller.snapshot()["accounts"]}
    assert {"Wallet", "Food", "Transport"} <= names


def test_reversal_capability_matches_what_the_ledger_accepts(app) -> None:
    controller, ids = app
    opening = next(t for t in controller.snapshot()["transactions"] if t["kind"] == "OPENING_BALANCE")
    # The opening balance sits on the untimed tracking boundary: not reversible.
    assert opening["reversalBlocker"] == "INVALID"
    with pytest.raises(LedgerValidationError):
        controller.reverse_transaction({"transactionId": opening["id"]})

    out = controller.create_transfer(
        {"sourceAccountId": ids["bank"], "destinationAccountId": ids["cash"], "amount": "10", "date": "2026-03-01"}
    )["id"]
    controller.create_transfer(
        {"sourceAccountId": ids["cash"], "destinationAccountId": ids["bank"], "amount": "10", "date": "2026-03-02"}
    )
    controller.set_account_archived({"accountId": ids["cash"], "archived": True})
    assert _row(controller, out)["reversalBlocker"] == "INVALID"


def test_reversal_keeps_the_payee_so_merchant_reports_net_out(app) -> None:
    controller, ids = app
    bar = controller.create_payee("Bar")
    expense = controller.create_expense(
        {"sourceAccountId": ids["bank"], "categoryAccountId": ids["food"], "amount": "7",
         "date": "2026-03-10", "payeeId": str(bar["id"])}
    )["id"]
    controller.reverse_transaction({"transactionId": expense})
    merchants = controller.dashboard(
        {"startDate": "2026-03-01", "endDate": "2026-03-31", "asOfDate": "2026-03-31"}
    )["merchants"]
    assert all(item["amountMinor"] == "0" for item in merchants), merchants


def test_restore_refuses_a_child_under_an_archived_parent(app) -> None:
    controller, ids = app
    child = controller.create_account(
        {"type": "EXPENSE", "name": "Groceries", "parentId": ids["food"]}
    )["id"]
    controller.set_account_archived({"accountId": child, "archived": True})
    controller.set_account_archived({"accountId": ids["food"], "archived": True})
    with pytest.raises(ValidationError, match="voce padre è archiviata"):
        controller.set_account_archived({"accountId": child, "archived": False})
