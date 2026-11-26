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
    with pytest.raises(ValidationError, match="programmata non conclusa"):
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
    assert opening["reversalBlocker"] == "BOUNDARY"
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
    # A fully reversed purchase is neither spending nor a visit.
    assert merchants == []
    suggestion = controller.suggest_payees("Bar")[0]
    assert suggestion["usageCount"] == 0


def test_restore_refuses_a_child_under_an_archived_parent(app) -> None:
    controller, ids = app
    child = controller.create_account(
        {"type": "EXPENSE", "name": "Groceries", "parentId": ids["food"]}
    )["id"]
    controller.set_account_archived({"accountId": child, "archived": True})
    controller.set_account_archived({"accountId": ids["food"], "archived": True})
    with pytest.raises(ValidationError, match="voce padre è archiviata"):
        controller.set_account_archived({"accountId": child, "archived": False})


def test_reversal_is_validated_at_the_requested_date(app) -> None:
    controller, ids = app
    opening = next(t for t in controller.snapshot()["transactions"] if t["kind"] == "OPENING_BALANCE")
    reversal = controller._ledger.create_reversal(  # noqa: SLF001 - explicit later date
        book_id=controller.initial_state()["book"]["id"],
        transaction_id=opening["id"],
        transaction_date="2026-02-01",
    )
    assert reversal.transaction_date == "2026-02-01"


def test_system_accounts_and_pending_imports_block_archiving(app, tmp_path) -> None:
    controller, ids = app
    book_id = controller.initial_state()["book"]["id"]
    equity = next(
        a for a in controller._accounts.list_accounts(book_id) if a.type == "EQUITY"  # noqa: SLF001
    )
    with pytest.raises(ValidationError, match="conto di sistema"):
        controller.set_account_archived({"accountId": equity.id, "archived": True})
    with pytest.raises(ValidationError, match="cannot be renamed"):
        controller.rename_account({"accountId": equity.id, "name": "Mine"})
    with pytest.raises(ValidationError, match="name must be text"):
        controller.rename_account({"accountId": ids["cash"], "name": None})

    csv_path = tmp_path / "cash.csv"
    csv_path.write_text("date,amount\n2026-03-01,-5\n", encoding="utf-8")
    controller.csv_import_task({"accountId": ids["cash"], "sourceName": "Cash"})(csv_path)
    with pytest.raises(ValidationError, match="da riconciliare"):
        controller.set_account_archived({"accountId": ids["cash"], "archived": True})


def test_snapshot_query_count_does_not_grow_with_transactions(app) -> None:
    controller, ids = app
    database = controller._database  # noqa: SLF001

    def statements() -> int:
        count = 0

        def trace(_sql: str) -> None:
            nonlocal count
            count += 1

        database.connection.set_trace_callback(trace)
        try:
            controller.snapshot()
        finally:
            database.connection.set_trace_callback(None)
        return count

    for _ in range(5):
        controller.create_expense(
            {"sourceAccountId": ids["bank"], "categoryAccountId": ids["food"], "amount": "1", "date": "2026-03-01"}
        )
    few = statements()
    for _ in range(60):
        controller.create_expense(
            {"sourceAccountId": ids["bank"], "categoryAccountId": ids["food"], "amount": "1", "date": "2026-03-01"}
        )
    assert statements() == few


def test_paused_schedules_and_open_budgets_block_archiving(app) -> None:
    from datetime import date

    from core.errors import ScheduledTransactionError

    controller, ids = app
    rent = controller.create_account({"type": "EXPENSE", "name": "Rent"})["id"]
    schedule = controller.create_scheduled_transaction(
        {"kind": "EXPENSE", "sourceAccountId": ids["bank"], "counterAccountId": rent,
         "amount": "10", "frequency": "MONTHLY", "interval": "1", "startDate": "2026-02-01"}
    )
    controller.set_scheduled_active({"scheduleId": schedule["id"], "active": False})
    with pytest.raises(ValidationError, match="programmata non conclusa"):
        controller.set_account_archived({"accountId": rent, "archived": True})

    controller.set_budget(
        {"categoryAccountId": ids["food"], "period": date.today().strftime("%Y-%m"), "amount": "100"}
    )
    with pytest.raises(ValidationError, match="budget"):
        controller.set_account_archived({"accountId": ids["food"], "archived": True})

    # A paused schedule whose account is archived (legacy data) cannot resume.
    from tests.conftest import force_legacy_archive

    force_legacy_archive(controller._database, rent)  # noqa: SLF001
    with pytest.raises(ScheduledTransactionError):
        controller.set_scheduled_active({"scheduleId": schedule["id"], "active": True})


def test_boundary_blocked_reversal_can_use_a_later_date(app) -> None:
    controller, ids = app
    opening = next(t for t in controller.snapshot()["transactions"] if t["kind"] == "OPENING_BALANCE")
    assert opening["reversalBlocker"] == "BOUNDARY"
    controller.reverse_transaction({"transactionId": opening["id"], "date": "2026-02-01"})
    assert _balance(controller, ids["bank"]) == "0"
    with pytest.raises(ValidationError, match="date must be text"):
        controller.reverse_transaction({"transactionId": opening["id"], "date": 20260201})
