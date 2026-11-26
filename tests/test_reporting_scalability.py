"""Reporting queries must scale linearly with ledger size.

Work is measured in SQLite virtual-machine steps (progress-handler ticks),
which is deterministic, instead of wall-clock time.
"""

from __future__ import annotations

from datetime import date, timedelta

from config.settings import Settings
from core.composition import build_controller
from core.database import Database


def _ledger(tmp_path, count: int):
    database = Database(tmp_path / f"scale-{count}.db")
    database.migrate()
    controller = build_controller(database, Settings())
    controller.setup({"userName": "u", "bookName": "b", "currency": "EUR"})
    bank = controller.create_account(
        {"type": "ASSET", "name": "Bank", "currency": "EUR", "trackingStartDate": "2020-01-01"}
    )["id"]
    food = controller.create_account({"type": "EXPENSE", "name": "Food"})["id"]
    book_id = controller.initial_state()["book"]["id"]
    ledger = controller._ledger  # noqa: SLF001 - bulk fixture setup
    start = date(2021, 1, 1)
    with database.transaction() as conn:
        for index in range(count):
            ledger.create_expense(
                book_id=book_id,
                source_account_id=bank,
                expense_account_id=food,
                amount_minor=100 + index,
                currency_code="EUR",
                transaction_date=(start + timedelta(days=index % 1500)).isoformat(),
                connection=conn,
            )
    return database, controller, bank


def _vm_work(database: Database, action) -> int:
    ticks = 0

    def tick() -> int:
        nonlocal ticks
        ticks += 1
        return 0

    database.connection.set_progress_handler(tick, 100)
    try:
        action()
    finally:
        database.connection.set_progress_handler(None, 0)
    return ticks


def test_balance_and_history_queries_scale_linearly(tmp_path) -> None:
    work = {}
    for count in (1500, 3000):
        database, controller, bank = _ledger(tmp_path, count)
        try:
            work[count] = (
                _vm_work(
                    database,
                    lambda c=controller: c.dashboard(
                        {"startDate": "2026-01-01", "endDate": "2026-01-31", "asOfDate": "2026-01-31"}
                    ),
                ),
                _vm_work(
                    database,
                    lambda c=controller, b=bank: c.account_history(
                        {"accountId": b, "startDate": "2024-01-01", "endDate": "2024-01-31"}
                    ),
                ),
            )
        finally:
            database.close()
    for before, after in zip(work[1500], work[3000], strict=True):
        # Doubling the ledger must roughly double the work, not quadruple it.
        assert after < 2.6 * before, work
