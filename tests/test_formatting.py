from __future__ import annotations

import pytest

from ui.formatting import format_money, format_percent_bps


@pytest.mark.parametrize(
    ("minor", "currency", "digits", "expected"),
    [
        ("123456", "EUR", 2, "1.234,56 EUR"),
        (-5, "EUR", 2, "−0,05 EUR"),
        ("0", "EUR", 2, "0,00 EUR"),
        ("1500", "JPY", 0, "1.500 JPY"),
        ("1234", "KWD", 3, "1,234 KWD"),
        # Beyond JavaScript's 2^53 safe-integer limit: exact digits survive.
        ("9007199254740993", "EUR", 2, "90.071.992.547.409,93 EUR"),
        ("-9223372036854775807", "EUR", 2, "−92.233.720.368.547.758,07 EUR"),
        (None, "EUR", 2, "FX mancante"),
        ("", "EUR", 2, "FX mancante"),
    ],
)
def test_format_money_is_exact(minor, currency, digits, expected) -> None:
    assert format_money(minor, currency, digits) == expected


@pytest.mark.parametrize("bad", ["1.5", "1e3", "abc", 1.5, True])
def test_format_money_rejects_non_integer_values(bad) -> None:
    with pytest.raises(ValueError):
        format_money(bad, "EUR", 2)


@pytest.mark.parametrize(
    ("bps", "expected"),
    [("525", "5,25%"), ("-1", "−0,01%"), ("10000", "100,00%"), (None, "—")],
)
def test_format_percent_bps(bps, expected) -> None:
    assert format_percent_bps(bps) == expected


def test_bridge_formats_with_backend_currency_precision(ledger_env) -> None:
    from config.settings import Settings
    from core.app_controller import AppController
    from core.book_service import BookService
    from core.payee_service import PayeeService
    from ui.bridge import Bridge

    controller = AppController(
        ledger_env.db,
        Settings(),
        ledger_env.accounts,
        ledger_env.ledger,
        BookService(ledger_env.db),
        PayeeService(ledger_env.db),
    )
    bridge = Bridge(controller)
    assert bridge.formatMoney("123456", "EUR") == "1.234,56 EUR"
    assert bridge.formatMoney("123456", "JPY") == "123.456 JPY"
    assert bridge.formatMoney("123456", "XXX") == "—"
    assert bridge.formatMoney("not-a-number", "EUR") == "—"
    assert bridge.formatPercentBps("9999") == "99,99%"


def test_money_formatting_never_queries_sqlite_during_maintenance() -> None:
    from PySide6.QtCore import QObject, Signal

    from ui.bridge import Bridge

    class Controller:
        def __init__(self) -> None:
            self.lookups = 0

        def initial_state(self):
            return {"currencies": [{"code": "EUR", "minorUnitDigits": 2}]}

        def currency_digits(self, code):
            self.lookups += 1
            return 0

        @staticmethod
        def error_payload(exc):
            return {"ok": False, "error": {"code": type(exc).__name__, "message": str(exc)}}

    class Tasks(QObject):
        finished = Signal("QVariant")
        maintenanceChanged = Signal(bool)
        maintenance = False
        active = False

    controller = Controller()
    tasks = Tasks()
    bridge = Bridge(controller, tasks)  # type: ignore[arg-type]
    assert bridge.getInitialState()["ok"] is True
    tasks.maintenance = True
    # Cached metadata keeps formatting off the GUI SQLite connection.
    assert bridge.formatMoney("123456", "EUR") == "1.234,56 EUR"
    assert bridge.formatMoney("1", "JPY") == "—"
    assert controller.lookups == 0
    tasks.maintenance = False
    assert bridge.formatMoney("1500", "JPY") == "1.500 JPY"
    assert controller.lookups == 1
