from __future__ import annotations

import random

import pytest

from config.settings import Settings
from core.composition import build_controller
from core.database import Database
from core.errors import FinanceTrackerError


def test_m4_workflow_stress(tmp_path) -> None:
    rng = random.Random(20260824)
    db = Database(tmp_path / "m4.db")
    db.open()
    db.migrate()
    controller = build_controller(db, Settings())
    try:
        assert controller.initial_state()["needsSetup"] is True
        controller.setup({"userName": "User", "bookName": "Personal", "currency": "EUR"})
        assert controller.initial_state()["needsSetup"] is False
        with pytest.raises(FinanceTrackerError):
            controller.setup({"userName": "Again", "bookName": "Again", "currency": "EUR"})

        today = "2026-08-25"
        bank = controller.create_account({"type": "ASSET", "name": "Bank", "currency": "EUR", "trackingStartDate": today, "trackingStartTime": "00:00"})["id"]
        cash = controller.create_account({"type": "ASSET", "name": "Cash", "currency": "EUR", "trackingStartDate": today, "trackingStartTime": "00:00"})["id"]
        categories = [controller.create_account({"type": "EXPENSE", "name": f"Category {i}"})["id"] for i in range(12)]
        controller.create_account({"type": "EXPENSE", "name": "Group", "placeholder": True})
        merchant_ids = [controller.create_payee(f"Merchant {i:02d}")["id"] for i in range(25)]

        for index in range(100):
            controller.create_expense({
                "sourceAccountId": bank if index % 4 else cash,
                "categoryAccountId": rng.choice(categories),
                "payeeId": rng.choice(merchant_ids),
                "amount": f"{rng.randint(1, 80)},{rng.randint(0, 99):02d}",
                "date": f"2026-{9 + (index // 28) % 3:02d}-{1 + index % 28:02d}",
                "description": f"Stress {index}",
            })

        snapshot = controller.snapshot()
        assert len(snapshot["transactions"]) == 100
        assert len(controller.suggest_payees("Merchant")) == 5
        before = db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        invalid_payloads = [
            {"sourceAccountId": bank, "categoryAccountId": categories[0], "amount": "", "date": "2026-09-01"},
            {"sourceAccountId": bank, "categoryAccountId": categories[0], "amount": "-2,00", "date": "2026-09-01"},
            {"sourceAccountId": bank, "categoryAccountId": categories[0], "amount": "12,345", "date": "2026-09-01"},
            {"sourceAccountId": 0, "categoryAccountId": categories[0], "amount": "2,00", "date": "2026-09-01"},
            {"sourceAccountId": bank, "categoryAccountId": 999999, "amount": "2,00", "date": "2026-09-01"},
            {"sourceAccountId": bank, "categoryAccountId": categories[0], "payeeId": 999999, "amount": "2,00", "date": "2026-09-01"},
            {"sourceAccountId": bank, "categoryAccountId": categories[0], "amount": "2,00", "date": "2020-01-01"},
        ]
        for payload in invalid_payloads:
            with pytest.raises(FinanceTrackerError):
                controller.create_expense(payload)
            assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before

        with pytest.raises(FinanceTrackerError):
            controller.create_account({"type": "ASSET", "name": "Broken", "currency": "EUR", "trackingStartDate": ""})
        with pytest.raises(FinanceTrackerError):
            controller.create_account({"type": "UNKNOWN", "name": "Broken"})

        db.integrity_check()
        assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()
        assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 100
        assert db.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 200
    finally:
        db.close()
