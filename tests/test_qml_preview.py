from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from ui.quick_adapter import QuickPreviewAdapter
from ui.quick_shell import launch_quick_preview


class _Controller:
    """Contract fixture for a controller that supplies immutable read results."""

    def __init__(self) -> None:
        self.amount = "9007199254740993"
        self.fail = False
        self.no_book = False

    def initial_state(self):
        if self.fail:
            raise RuntimeError("private internal details")
        return {
            "book": None if self.no_book else {"name": "Fixture book"},
            "bookCurrency": "EUR",
        }

    def dashboard(self, payload):
        assert payload["startDate"] <= payload["endDate"]
        assert payload["endDate"] == payload["asOfDate"]
        return {
            "baseCurrency": "EUR",
            "overview": {"netWorthMinor": self.amount},
        }


class _Tasks(QObject):
    maintenanceChanged = Signal(bool)
    finished = Signal("QVariant")

    def __init__(self):
        super().__init__()
        self.active = False


def test_adapter_uses_controller_and_preserves_large_financial_integer_as_text() -> None:
    controller = _Controller()
    tasks = _Tasks()
    adapter = QuickPreviewAdapter(controller, tasks)  # type: ignore[arg-type]
    assert adapter.bookName == "Fixture book"
    assert adapter.currency == "EUR"
    assert adapter.netWorthMinor == "9007199254740993"

    controller.amount = None
    adapter.refresh()
    assert adapter.netWorthMinor == "FX mancanti"

    controller.no_book = True
    adapter.refresh()
    assert adapter.bookName == "Book non configurato"
    assert adapter.netWorthMinor == "—"


def test_adapter_does_not_leak_unexpected_errors_or_read_while_maintenance() -> None:
    controller = _Controller()
    controller.fail = True
    tasks = _Tasks()
    adapter = QuickPreviewAdapter(controller, tasks)  # type: ignore[arg-type]
    assert adapter.errorMessage == "Errore inatteso; consultare i log."
    errors: list[str] = []
    adapter.errorOccurred.connect(errors.append)
    tasks.active = True
    tasks.maintenanceChanged.emit(True)
    adapter.refresh()
    assert errors[-1] == "Operazione di backup o ripristino in corso."
    assert adapter.errorMessage == errors[-1]
    assert adapter.busy is True

    tasks.active = False
    tasks.maintenanceChanged.emit(False)
    adapter.refresh()
    assert errors[-1] == "Errore inatteso; consultare i log."
    assert "private" not in errors[-1]
    controller.fail = False
    adapter.refresh()
    assert adapter.errorMessage == ""


def test_qml_engine_loads_with_required_backend_and_reacts_to_refresh() -> None:
    app = QApplication.instance() or QApplication([])
    controller = _Controller()
    tasks = _Tasks()
    engine = launch_quick_preview(controller, tasks)  # type: ignore[arg-type]
    try:
        root = engine.rootObjects()[0]
        backend = root.property("backend")
        assert backend is not None
        book_name = root.findChild(QObject, "bookNameValue")
        net_worth = root.findChild(QObject, "netWorthValue")
        feedback = root.findChild(QObject, "previewFeedback")
        assert book_name is not None
        assert net_worth is not None
        assert feedback is not None
        assert book_name.property("text") == "Fixture book"
        assert net_worth.property("text") == "9007199254740993"
        controller.amount = "9223372036854775807"
        backend.refresh()
        app.processEvents()
        assert net_worth.property("text") == "9223372036854775807"
        controller.fail = True
        backend.refresh()
        app.processEvents()
        assert feedback.property("text") == "Errore inatteso; consultare i log."
        controller.fail = False
        backend.refresh()
        app.processEvents()
        assert feedback.property("text") == ""
        root.close()
    finally:
        del engine
        app.processEvents()
