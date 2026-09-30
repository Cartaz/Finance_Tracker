from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import Settings, SettingsStore
from core.app_controller import AppController
from core.app_state_service import AppStateService
from core.backup_service import BackupService
from core.book_service import BookService
from core.errors import BackupError, ValidationError
from core.payee_service import PayeeService
from core.transport import TransportSerializer
from ui.bridge import Bridge


@pytest.mark.parametrize(
    "raw",
    [
        {"book_currency": None},
        {"book_currency": 123},
        {"reconciliation_review_mode": []},
        {"locale": None},
    ],
)
def test_malformed_setting_types_use_defaults(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert SettingsStore(path).load() == Settings()


def _bridge(env):
    return Bridge(
        AppController(
            env.db,
            Settings(),
            env.accounts,
            env.ledger,
            BookService(env.db),
            PayeeService(env.db),
        )
    )


@pytest.mark.parametrize("payload", [123, "oops", [1, 2], True])
def test_bridge_rejects_non_object_payload_without_raising(ledger_env, payload):
    result = _bridge(ledger_env).createAccount(payload)
    assert result["ok"] is False
    assert result["error"]["code"] == "ValidationError"


@pytest.mark.parametrize("value", [1.5, True, float("inf"), "1.5"])
def test_controller_identifiers_never_truncate(value):
    with pytest.raises(ValidationError):
        AppController._positive_id(value)


def test_currency_metadata_survives_database_reopen(ledger_env):
    state = AppStateService(ledger_env.db, ledger_env.accounts)
    before = state.supported_currencies()
    ledger_env.db.close()
    ledger_env.db.open()
    assert state.supported_currencies() == before


@pytest.mark.parametrize(
    "field",
    [
        "assetsMinor",
        "liabilitiesMinor",
        "savingMinor",
        "openingBalanceMinor",
        "endingBalanceMinor",
        "endingBaseValueMinor",
        "valueMinor",
        "quantityMinor",
    ],
)
def test_all_public_money_fields_keep_exact_transport_precision(field):
    amount = 2**53 + 1
    assert TransportSerializer.serialize({field: amount})[field] == str(amount)


@pytest.mark.parametrize(
    "failure_point",
    ["checkpoint", "sidecars", "move_original", "move_staged", "reopen"],
)
def test_restore_failure_never_deletes_original(ledger_env, monkeypatch, failure_point):
    db = ledger_env.db
    service = BackupService(db, db.path.parent / "backups")
    backup = service.create_managed_backup()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE books SET name='Keep me' WHERE id=?", (ledger_env.book_id,)
        )
    plan = service.prepare_restore(service.managed_path(str(backup["name"])))
    assert plan.staged_database.stat().st_mode & 0o777 == 0o600
    fired = False

    def inject():
        nonlocal fired
        if not fired:
            fired = True
            raise OSError("injected failure")

    if failure_point in {"checkpoint", "reopen"}:
        name = "checkpoint" if failure_point == "checkpoint" else "open"
        original = getattr(db, name)

        def fail_once():
            inject()
            return original()

        monkeypatch.setattr(db, name, fail_once)
    elif failure_point == "sidecars":
        original = service._remove_sidecars

        def fail_sidecars(path):
            inject()
            return original(path)

        monkeypatch.setattr(service, "_remove_sidecars", fail_sidecars)
    else:
        original = Path.replace

        def fail_replace(path, target):
            if (failure_point == "move_original" and path == db.path) or (
                failure_point == "move_staged" and path == plan.staged_database
            ):
                inject()
            return original(path, target)

        monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(BackupError):
        service.finalize_restore(plan)
    assert db.path.is_file()
    assert BookService(db).current_book().name == "Keep me"
    db.integrity_check()
    assert not plan.staged_database.exists()


def test_csv_extra_columns_fail_closed(ledger_env):
    from core.errors import ReconciliationError
    from core.reconciliation_service import ReconciliationService

    with pytest.raises(ReconciliationError):
        ReconciliationService._parse_csv("date,amount\n2026-09-30,-5,unexpected\n")


def test_compact_dates_are_stored_canonically_and_reported(ledger_env):
    from core.fx_service import FxService
    from core.reporting_service import ReportingService

    env = ledger_env
    bank = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="20260101",
        tracking_start_time="0800",
    )
    assert bank.tracking_start_date == "2026-01-01"
    assert bank.tracking_start_time == "08:00:00"
    expense = env.accounts.create_account(
        book_id=env.book_id, account_type="EXPENSE", name="Food"
    )
    posted = env.ledger.create_expense(
        book_id=env.book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=500,
        currency_code="EUR",
        transaction_date="20260930",
    )
    assert posted.transaction_date == "2026-09-30"
    report = ReportingService(env.db, FxService(env.db)).overview(
        book_id=env.book_id,
        start_date="2026-09-01",
        end_date="2026-09-30",
        as_of_date="2026-09-30",
    )
    assert report["expenseMinor"] == 500


def test_offset_times_are_refused_before_persistence(ledger_env):
    with pytest.raises(ValidationError):
        ledger_env.accounts.create_account(
            book_id=ledger_env.book_id,
            account_type="ASSET",
            name="Bad",
            currency_code="EUR",
            tracking_start_date="2026-01-01",
            tracking_start_time="08:00+02:00",
        )


def test_reconciliation_without_external_ids_cannot_match_twice(ledger_env):
    from core.errors import ReconciliationError
    from core.reconciliation_service import ReconciliationService

    env = ledger_env
    bank = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    expense = env.accounts.create_account(
        book_id=env.book_id, account_type="EXPENSE", name="Food"
    )
    transaction = env.ledger.create_expense(
        book_id=env.book_id,
        source_account_id=bank.id,
        expense_account_id=expense.id,
        amount_minor=500,
        currency_code="EUR",
        transaction_date="2026-09-30",
    )
    service = ReconciliationService(
        env.db, env.accounts, env.ledger, PayeeService(env.db)
    )
    batch = service.import_csv(
        book_id=env.book_id,
        account_id=bank.id,
        source_name="Bank",
        review_mode="FULL_REVIEW",
        csv_text="date,amount\n2026-09-30,-5\n2026-09-30,-5\n",
    )
    rows = service.batch_rows(env.book_id, batch["batchId"])
    service.link_existing(
        book_id=env.book_id, row_id=rows[0]["id"], transaction_id=transaction.id
    )
    with pytest.raises(ReconciliationError):
        service.link_existing(
            book_id=env.book_id, row_id=rows[1]["id"], transaction_id=transaction.id
        )


def test_large_csv_worker_keeps_event_loop_alive_and_paginates(ledger_env):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from core.backup_controller import BackupController
    from ui.backup_task_manager import BackupTaskManager

    app = QApplication.instance() or QApplication([])
    env = ledger_env
    bank = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    controller = _bridge(env)._controller
    manager = BackupTaskManager(
        BackupController(BackupService(env.db, env.db.path.parent / "backups")),
        controller.error_payload,
    )
    bridge = Bridge(controller, manager)
    results = []
    heartbeats = []
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeats.append(True))
    manager.finished.connect(lambda result: (results.append(result), loop.quit()))
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    csv_text = "date,amount,externalid\n" + "".join(
        f"2026-09-30,-5,row-{i}\n" for i in range(10_000)
    )
    started = bridge.startCsvImport(
        {"accountId": bank.id, "sourceName": "Bank", "csvText": csv_text}
    )
    assert started["ok"] is True
    assert manager.maintenance is True
    assert bridge.createPayee("Blocked")["ok"] is False
    assert bridge.startManagedBackup()["ok"] is False
    timer.start()
    deadline.start(60_000)
    loop.exec()
    timer.stop()
    deadline.stop()
    assert results and results[0]["ok"] is True
    assert len(heartbeats) > 0
    assert manager.active is False
    batch_id = results[0]["data"]["batchId"]
    assert results[0]["data"]["rowCount"] == 10_000
    first = bridge.getImportBatchRows({"batchId": batch_id, "limit": 101})["data"]
    second = bridge.getImportBatchRows(
        {"batchId": batch_id, "offset": 100, "limit": 101}
    )["data"]
    assert len(first) == len(second) == 101
    assert first[100]["id"] == second[0]["id"]
    assert bridge.getSnapshot()["ok"] is True
    app.processEvents()


def test_local_navigation_is_confined_to_frontend(monkeypatch):
    from PySide6.QtCore import QUrl

    from ui.window import _local_resource_allowed

    root = Path(__file__).resolve().parents[1] / "ui" / "web"
    assert _local_resource_allowed(QUrl.fromLocalFile(str(root / "index.html")))
    assert not _local_resource_allowed(QUrl("file:///etc/passwd"))
    assert not _local_resource_allowed(
        QUrl.fromLocalFile(str(root / ".." / "bridge.py"))
    )
    assert not _local_resource_allowed(QUrl("about:version"))


def test_payee_merge_keeps_future_schedules_postable(ledger_env):
    from core.scheduled_transaction_service import ScheduledTransactionService

    env = ledger_env
    bank = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    expense = env.accounts.create_account(
        book_id=env.book_id, account_type="EXPENSE", name="Food"
    )
    payees = PayeeService(env.db)
    source = payees.create_payee(book_id=env.book_id, name="Old name")
    target = payees.create_payee(book_id=env.book_id, name="New name")
    scheduled = ScheduledTransactionService(env.db, env.accounts, env.ledger, payees)
    schedule = scheduled.create_schedule(
        book_id=env.book_id,
        kind="EXPENSE",
        source_account_id=bank.id,
        counter_account_id=expense.id,
        amount_minor=500,
        frequency="MONTHLY",
        interval=1,
        start_date="2026-09-30",
        payee_id=source.id,
    )
    payees.merge_payees(book_id=env.book_id, source_id=source.id, target_id=target.id)
    assert scheduled.get_schedule(env.book_id, schedule.id).payee_id == target.id
    posted = scheduled.post_due(book_id=env.book_id, as_of_date="2026-09-30")
    payee_id = env.db.connection.execute(
        "SELECT payee_id FROM transactions WHERE id=?", (posted[0]["transactionId"],)
    ).fetchone()[0]
    assert payee_id == target.id


def test_reconciliation_matches_the_net_account_quantity(ledger_env):
    from core.ledger_service import EntryDraft, TransactionDraft
    from core.reconciliation_service import ReconciliationService

    env = ledger_env
    bank = env.accounts.create_account(
        book_id=env.book_id,
        account_type="ASSET",
        name="Bank",
        currency_code="EUR",
        tracking_start_date="2026-01-01",
    )
    expense = env.accounts.create_account(
        book_id=env.book_id, account_type="EXPENSE", name="Food"
    )
    transaction = env.ledger.create_transaction(
        TransactionDraft(
            book_id=env.book_id,
            kind="EXPENSE",
            currency_code="EUR",
            transaction_date="2026-09-30",
            entries=(
                EntryDraft(bank.id, -500, -500),
                EntryDraft(bank.id, -500, -500),
                EntryDraft(expense.id, 1000, None),
            ),
        )
    )
    service = ReconciliationService(
        env.db, env.accounts, env.ledger, PayeeService(env.db)
    )
    assert service._candidate_details(env.book_id, bank.id, "2026-09-30", -500) == []
    candidates = service._candidate_details(env.book_id, bank.id, "2026-09-30", -1000)
    assert [item["id"] for item in candidates] == [transaction.id]
    assert service._transaction_is_compatible(
        env.book_id, bank.id, transaction.id, "2026-09-30", -1000
    )
    assert not service._transaction_is_compatible(
        env.book_id, bank.id, transaction.id, "2026-09-30", -500
    )


def test_invalid_settings_encoding_does_not_break_startup(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfeinvalid")
    assert SettingsStore(path).load() == Settings()
