from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_user_money_inputs_use_canonical_magnitude_parser() -> None:
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    money = (ROOT / "core" / "money.py").read_text(encoding="utf-8")
    reconciliation = (ROOT / "core" / "reconciliation_service.py").read_text(
        encoding="utf-8"
    )

    assert "def parse_money_magnitude" in money
    assert "from core.money import parse_money_magnitude" in controller
    # expense, budget, scheduled amount, opening balance, new-loan principal,
    # and custom loan payment
    assert controller.count("parse_money_magnitude(") == 6
    assert "from core.money import parse_money" in reconciliation
    assert "parse_money(" in reconciliation


def test_magnitude_parser_owns_sign_semantics() -> None:
    money = (ROOT / "core" / "money.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")

    assert "monetary magnitude must not include a sign" in money
    assert "monetary magnitude must be greater than zero" in money
    assert "expense amount must be positive" not in controller
