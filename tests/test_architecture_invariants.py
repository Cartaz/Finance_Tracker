from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def _python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def test_ledger_is_only_core_accounting_writer() -> None:
    forbidden = ("INSERT INTO transactions", "INSERT INTO entries")
    violations: list[str] = []
    for path in _python_files(CORE):
        if path.name == "ledger_service.py":
            continue
        text = path.read_text(encoding="utf-8")
        if any(statement in text for statement in forbidden):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_core_does_not_depend_on_qt() -> None:
    violations = [
        str(path.relative_to(ROOT))
        for path in _python_files(CORE)
        if "PySide6" in path.read_text(encoding="utf-8")
    ]
    assert violations == []


def test_app_controller_contains_no_sql() -> None:
    text = (CORE / "app_controller.py").read_text(encoding="utf-8")
    assert ".execute(" not in text
    assert "SELECT " not in text
    assert "INSERT INTO " not in text
    assert "UPDATE " not in text
    assert "DELETE FROM " not in text


def test_bridge_imports_only_controller_and_expected_errors_from_core() -> None:
    tree = ast.parse((ROOT / "ui" / "bridge.py").read_text(encoding="utf-8"))
    core_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("core."):
            core_imports.add(node.module)
    assert core_imports <= {"core.app_controller", "core.errors"}


def test_frontend_does_not_rederive_reconciliation_posting_rules() -> None:
    text = (ROOT / "ui" / "web" / "app.js").read_text(encoding="utf-8")
    assert "postingKindsForRow" not in text
    assert "row.postingCapabilities" in text


def test_transport_contract_is_explicit_not_suffix_driven() -> None:
    controller = (CORE / "app_controller.py").read_text(encoding="utf-8")
    transport = (CORE / "transport.py").read_text(encoding="utf-8")
    assert "_transport_money" not in controller
    assert ".endswith(" not in transport
    assert "_FINANCIAL_INTEGER_FIELDS" in transport


def test_database_schema_is_owned_by_migrations_module() -> None:
    database = (CORE / "database.py").read_text(encoding="utf-8")
    migrations = (CORE / "migrations.py").read_text(encoding="utf-8")
    assert "_SCHEMA_V" not in database
    assert "MIGRATIONS" in migrations


def test_strategic_review_is_part_of_definition_of_done() -> None:
    directive = (ROOT / "STRATEGIC_PROGRAMMING.md").read_text(encoding="utf-8")
    assert "Mandatory milestone strategic review" in directive
    assert "BLOCKED" in directive
    assert "Green tests without the review are not milestone completion" in directive
