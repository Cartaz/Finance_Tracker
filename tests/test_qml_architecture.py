"""Architecture invariants of the Qt Quick presentation layer."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML_DIR = ROOT / "ui" / "qml"


def _qml_sources() -> dict[str, str]:
    return {
        path.relative_to(QML_DIR).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(QML_DIR.rglob("*.qml"))
    }


def test_qml_has_no_network_dynamic_code_or_filesystem_access() -> None:
    for name, source in _qml_sources().items():
        for forbidden in (
            "XMLHttpRequest",
            "WebSocket",
            "Qt.openUrlExternally",
            "Qt.createQmlObject",
            "eval(",
            "new Function(",
            "QtWebEngine",
            "FileDialog",
            "http://",
            "https://",
        ):
            assert forbidden not in source, f"{name} uses {forbidden}"


def test_qml_never_parses_or_computes_money() -> None:
    # Money arrives as exact integer text and is formatted by Python.
    numeric = re.compile(r"\b(parseFloat|parseInt|BigInt|Math\.(round|floor|ceil|pow))\b")
    for name, source in _qml_sources().items():
        assert not numeric.search(source), f"{name} performs numeric conversion"
        if name != "pages/ToolsPage.qml":  # byte sizes of backup files only
            assert "Number(" not in source, f"{name} converts values to numbers"
    main = _qml_sources()["Main.qml"]
    assert "root.backend.formatMoney(" in main
    assert "root.backend.formatPercentBps(" in main


def test_single_backend_object_is_injected_into_the_root_only() -> None:
    sources = _qml_sources()
    declarations = [name for name, text in sources.items() if "property var backend" in text]
    assert declarations == ["Main.qml"]
    shell = (ROOT / "ui" / "shell.py").read_text(encoding="utf-8")
    assert 'setInitialProperties({"backend": bridge})' in shell


def test_pages_render_backend_capabilities_instead_of_rederiving_rules() -> None:
    sources = _qml_sources()
    main = sources["Main.qml"]
    assert "postingCapabilities[kind]" in main
    transactions = sources["pages/TransactionsPage.qml"]
    for kind in ("EXPENSE", "INCOME", "TRANSFER"):
        assert re.search(rf'app\.counterOptions\([^)]*"{kind}"\)', transactions), kind
    assert "report.targets" in sources["pages/BudgetsPage.qml"]
    assert "postingCapabilities" in sources["pages/ImportRow.qml"]
    assert 'app.call("getForecast"' in sources["pages/ForecastPage.qml"]
    for name, source in sources.items():
        # Accounting decisions (eligibility by type/currency) stay in Python.
        assert ".currency ===" not in source, name
        assert "type === \"LIABILITY\" &&" not in source, name


def test_restore_rebuilds_the_session_and_maintenance_is_visible() -> None:
    main = _qml_sources()["Main.qml"]
    tools = _qml_sources()["pages/ToolsPage.qml"]
    assert "result.requiresReload" in main
    assert "root.sessionReset()" in main
    assert "root.backend.maintenance" in main
    assert "backup dello stato corrente" in tools
    assert "modalità manutenzione" in tools
    assert "page.app.confirm(" in tools


def test_inset_shader_is_shipped_compiled_for_the_runtime() -> None:
    import shutil
    import subprocess
    import sys

    package = QML_DIR / "shaders" / "inset.frag.qsb"
    assert (QML_DIR / "shaders" / "inset.frag").is_file()
    assert package.is_file() and package.stat().st_size > 0
    assert 'Qt.resolvedUrl("shaders/inset.frag.qsb")' in _qml_sources()["InsetSurface.qml"]
    qsb = Path(sys.executable).with_name("pyside6-qsb")
    if not qsb.exists():
        qsb = Path(shutil.which("pyside6-qsb") or "")
    if qsb.is_file():
        dump = subprocess.run(
            [str(qsb), "-d", str(package)], capture_output=True, text=True, check=True
        ).stdout
        assert "GLSL" in dump
